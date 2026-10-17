"""Snapshot pipeline: external authority -> validated copy -> index bundle -> CAS."""
import json
from pathlib import Path
import shutil

from modules.common.contracts import Budget, Failure, decode_json, digest, encoded, require
from modules.connectors.iceberg import snapshot
from modules.index.ann import build as build_ann
from modules.index.bm25 import build as build_bm25
from modules.index.shards import build as build_shards
from modules.index.retrieval import ANALYZER, build, features, load_bundle
from modules.storage.objects import Objects, get, put


def construct(control, dataset, operation, target, root, s3=None, cancelled=lambda: False, inherited=None, added_files=None):
    require(isinstance(target, dict) and set(target) - {'ann'} == {'metadata_uri','metadata_sha256','snapshot_id','features_uri','features_sha256'}, 'invalid_request')
    require(all(isinstance(target[name], str) and len(target[name]) == 64 and
                all(c in '0123456789abcdef' for c in target[name])
                for name in ('metadata_sha256','features_sha256')), 'invalid_request', 'both source pins require canonical SHA-256')
    ds = control.dataset(dataset)
    definition = ds['definition']
    require(set(definition) == {'root','key_field','text_field'}, 'invalid_definition')
    run = control.begin(dataset, operation, target)
    if run['status'] != 'building':
        return run  # Operation ID reconciliation; failed operations are never silently retried.
    directory = Path(root).resolve() / str(run['id'])
    try:
        directory.mkdir(parents=True, exist_ok=False)
        budget = Budget(cancelled)
        objects = Objects(definition['root'], budget, s3, directory/'dependencies')
        result = snapshot(objects, target['metadata_uri'], target['metadata_sha256'], target['snapshot_id'],
                          str(ds['id']), ds['name'], definition['key_field'], directory/'objects', inherited, added_files)
        model = features(result['rows'], decode_json(objects.read(target['features_uri'], expected=target['features_sha256'])),
                         definition['text_field'])
        if inherited:
            require(model == inherited['model'], 'unsupported_change', 'append changed feature model')
            originals = {row['logical_key']: row for row in inherited['rows']}
            for row in result['rows']:
                if row['logical_key'] in originals:
                    previous = originals[row['logical_key']]
                    row['record_version'] = previous.get('record_version', inherited['revision'])
                    require(row['vector'] == previous['vector'] and
                            [{k:v for k,v in m.items() if k != 'copy'} for m in row['media']] ==
                            [{k:v for k,v in m.items() if k != 'copy'} for m in previous['media']],
                            'unsupported_change', 'append changed existing features')
            present = {d['uri'] for d in objects.dependencies}
            for dependency in inherited['source']['dependencies']:
                if dependency['uri'] in present:
                    continue
                raw = get(dependency['copy'])
                budget.artifact(len(raw))
                objects.dependencies.append(dict(dependency, copy=put(directory/'dependencies'/digest(raw), raw)))
        seen_media = {}
        if inherited:
            for old_row in inherited['rows']:
                for media in old_row['media']:
                    raw = get(media['copy'])
                    budget.artifact(len(raw))
                    seen_media[(media['uri'], media['sha256'], media['size_bytes'])] = put(directory/'dependencies'/digest(raw), raw)
        for row in result['rows']:
            for media in row['media']:
                identity = (media['uri'], media['sha256'], media['size_bytes'])
                if identity in seen_media:
                    media['copy'] = seen_media[identity]
                    continue
                raw = objects.read(media['uri'], expected=media['sha256'])
                require(len(raw) == media['size_bytes'], 'source_invalid')
                media['copy'] = objects.dependencies[-1]['copy']
                seen_media[identity] = media['copy']
        result['source']['dependencies'] = objects.dependencies
        version_source = dict(result['source'], dependencies=[{k:v for k,v in d.items() if k != 'copy'} for d in objects.dependencies])
        revision = 'rev_' + digest(encoded({'source': version_source, 'model': model, 'text_field': definition['text_field']}))
        for row in result['rows']:
            row.setdefault('record_version', revision)
        context = {'read_consistency': 'published', 'data_revision_id': revision,
                   'read_view_id': 'view_' + str(run['id']),
                   'source_versions': [{'source_id': str(ds['id']), 'format': 'iceberg-v2',
                                        'version': str(target['snapshot_id'])},
                                       {'source_id': str(ds['id'])+':metadata', 'format': 'iceberg-v2-metadata',
                                        'version': target['metadata_sha256']},
                                       {'source_id': model['model'], 'format': 'features-v1', 'version': target['features_sha256']}],
                   'index_versions': [{'index_id': str(ds['id'])+':bm25-global-v2:'+ANALYZER, 'version': str(run['id'])},
                                      {'index_id': str(ds['id'])+':exact-vector:'+digest(encoded(model)), 'version': str(run['id'])}]}
        index_files = build(directory/'tantivy', result['rows'], definition['text_field'], budget)
        bm25 = build_bm25(directory/'bm25', result['rows'], definition['text_field'], budget)
        manifest_ref = put(directory/'manifest.json', encoded(result['manifest']))
        bundle = {'version': 2, 'retention_mode': 'managed-copy', 'revision': revision, 'context': context, 'model': model, 'source': result['source'],
                  'manifest': result['manifest'], 'manifest_reference': manifest_ref, 'rows': result['rows'],
                  'index_path': str(directory/'tantivy'), 'index_files': index_files, 'bm25': bm25,
                  'stats': {'source_reads': budget.reads, 'source_bytes': budget.bytes}}
        if 'ann' in target:
            bundle['ann'] = build_ann(directory/'lance', result['rows'], revision, model, target['ann'], budget)
            context['index_versions'].append({'index_id': str(ds['id'])+':lance-ivf-flat', 'version': str(run['id'])})
        budget.check()
        bundle['shards'] = build_shards(bundle, directory/'shards', budget)
        payload = encoded(bundle)
        require(len(payload) <= 32 << 20, 'resource_limit')
        reference = put(directory/'bundle.json', payload)
        reference['context'] = context
        load_bundle(reference, budget)
        control.ready(run['id'], reference)
        return control.run(run['id'])
    except Exception as error:
        control.fail(run['id'], error.code if isinstance(error, Failure) else 'build_failed')
        raise


def publish(control, run, expected_epoch):
    candidate = control.run(run)
    if candidate['published_epoch'] is not None:
        return control.publish(run, expected_epoch)
    require(candidate['artifact'] is not None, 'not_ready')
    load_bundle(candidate['artifact'], Budget())
    return control.publish(run, expected_epoch)


def collect(control, run, root):
    row = control.retire(run)
    # Only this exact generated run directory; never source URIs or caller paths.
    base = Path(root).resolve(strict=True)
    directory = base / str(row['id'])
    require(not directory.is_symlink() and directory.resolve().parent == base, 'source_invalid')
    if directory.exists():
        shutil.rmtree(directory)
    with control.transaction() as conn:
        conn.execute("UPDATE gura_m1.runs SET status='retired' WHERE id=%s AND status='retiring'", (run,))
