"""Rebuild lost derived indexes from a published immutable managed-copy view."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.contracts import Budget, Failure, MAX_BYTES, MAX_FILES, MAX_ROWS, decode_json, digest, encoded, key, require
from modules.index.ann import build as build_ann
from modules.index.bm25 import build as build_bm25
from modules.index.retrieval import ANALYZER, build, load_bundle
from modules.index.shards import build as build_shards
from modules.storage.objects import get, put


def _read(reference, budget):
    budget.check()
    try:
        raw = get(reference)
    except (OSError, KeyError):
        raise Failure('source_unavailable', 'required immutable fact copy is unavailable') from None
    budget.artifact(len(raw))
    return raw


def _facts(artifact, dataset, directory, budget):
    """Skip only derived files; verify all fact references and Parquet row truth."""
    bundle = decode_json(_read(artifact, budget))
    require(bundle['version'] in (1, 2) and bundle['retention_mode'] == 'managed-copy' and
            bundle['manifest']['dataset_id'] == str(dataset) and 0 < len(bundle['rows']) <= MAX_ROWS,
            'source_invalid')
    require(_read(bundle['manifest_reference'], budget) == encoded(bundle['manifest']), 'source_invalid')
    if 'incremental' in artifact:
        _read(artifact['incremental'], budget)
    copied = {}
    for dependency in bundle['source']['dependencies']:
        raw = _read(dependency['copy'], budget)
        require(digest(raw) == dependency['sha256'] and len(raw) == dependency['size_bytes'], 'source_invalid')
        copied[dependency['copy']['path']] = put(directory/'dependencies'/digest(raw), raw)
        dependency['copy'] = copied[dependency['copy']['path']]
    rows = {row['logical_key']: row for row in bundle['rows']}
    require(len(rows) == len(bundle['rows']), 'invalid_key')
    for row in bundle['rows']:
        row.setdefault('record_version', bundle['revision'])
        for media in row['media']:
            raw = _read(media['copy'], budget)
            require(digest(raw) == media['sha256'] and len(raw) == media['size_bytes'], 'source_invalid')
            media['copy'] = put(directory/'dependencies'/digest(raw), raw)
    manifest = bundle['manifest']
    require(manifest['backend']['kind'] == 'local', 'source_invalid')
    files = manifest['files']
    require(0 < len(files) <= MAX_FILES, 'resource_limit')
    expected = pa.schema([pa.field(field['name'], {'int8': pa.int64(), 'text': pa.string(), 'bool': pa.bool_()}[field['data_type']],
                                   nullable=field['nullable']) for field in manifest['schema']])
    seen, decoded, total = set(), 0, 0
    for fragment in files:
        require(Path(fragment['key']).name == fragment['key'], 'source_invalid')
        raw = _read({'path': str(Path(manifest['backend']['root'])/fragment['key']), 'sha256': fragment['sha256']}, budget)
        require(len(raw) == fragment['size_bytes'], 'source_invalid')
        total += len(raw)
        require(total <= MAX_BYTES, 'resource_limit')
        parquet = pq.ParquetFile(BytesIO(raw))
        require(parquet.schema_arrow.equals(expected, check_metadata=False) and
                sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.metadata.num_row_groups)) <= 64 << 20,
                'source_invalid')
        table = parquet.read()
        decoded += table.nbytes
        require(decoded <= 64 << 20 and len(seen)+len(table) <= MAX_ROWS, 'resource_limit')
        for values in table.to_pylist():
            logical = key(values[bundle['source']['key_field']], bundle['source']['key_type'])
            require(logical not in seen and logical in rows and rows[logical]['values'] == values,
                    'source_invalid', 'managed Parquet differs from immutable row mapping')
            seen.add(logical)
        put(directory/'objects'/fragment['key'], raw)
    require(seen == set(rows), 'source_invalid', 'fact fragments do not cover immutable row mapping')
    manifest['backend'] = {'kind': 'local', 'root': str((directory/'objects').resolve())}
    bundle['manifest_reference'] = put(directory/'manifest.json', encoded(manifest))
    return bundle


def rebuild(control, dataset, operation, root):
    """Return a ready run; publish separately using the existing epoch/generation CAS."""
    require(isinstance(operation, str) and 0 < len(operation) <= 128, 'invalid_request')
    with control.transaction() as conn:
        locked = conn.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 7101712)) AS locked',
                              (str(dataset)+':'+operation,)).fetchone()['locked']
        require(locked, 'operation_busy')
        previous = conn.execute('SELECT * FROM gura_m1.runs WHERE dataset=%s AND operation=%s',
                                (dataset, operation)).fetchone()
        if previous:
            require(set(previous['target']) == {'rebuild'} and previous['target']['rebuild'].get('version') == 1,
                    'operation_conflict')
            return previous
        ds = control.dataset(dataset)
        require(ds['published'] is not None, 'not_ready')
        base = control.run(ds['published'])
        target = {'rebuild': {'version': 1, 'base_run': str(base['id']), 'artifact_sha256': base['artifact']['sha256']}}
        run = control.begin(dataset, operation, target)
        owner, pinned = 'rebuild:'+str(run['id']), False
        try:
            control.pin(base['id'], owner)
            pinned = True
            directory = Path(root).resolve()/str(run['id'])
            directory.mkdir(parents=True, exist_ok=False)
            budget = Budget()
            bundle = _facts(base['artifact'], dataset, directory, budget)
            context = deepcopy(bundle['context'])
            context['read_view_id'] = 'view_'+str(run['id'])
            context['index_versions'] = [
                {'index_id': str(dataset)+':bm25-global-v2:'+ANALYZER, 'version': str(run['id'])},
                {'index_id': str(dataset)+':exact-vector:'+digest(encoded(bundle['model'])), 'version': str(run['id'])}]
            bundle['context'] = context
            bundle['index_path'] = str(directory/'tantivy')
            bundle['index_files'] = build(directory/'tantivy', bundle['rows'], ds['definition']['text_field'], budget)
            bundle['bm25'] = build_bm25(directory/'bm25', bundle['rows'], ds['definition']['text_field'], budget)
            if 'ann' in bundle:
                partitions = bundle['ann']['partitions']
                bundle['ann'] = build_ann(directory/'lance', bundle['rows'], bundle['revision'], bundle['model'],
                                          {'partitions': partitions}, budget)
                context['index_versions'].append({'index_id': str(dataset)+':lance-ivf-flat', 'version': str(run['id'])})
            bundle['version'] = 2
            bundle['shards'] = build_shards(bundle, directory/'shards', budget)
            bundle['rebuild_from'] = str(base['id'])
            bundle['stats'] = {'source_reads': 0, 'source_bytes': 0, 'artifact_reads': budget.artifact_reads,
                               'artifact_bytes': budget.artifact_bytes, 'execution': 'managed-copy-index-rebuild'}
            payload = encoded(bundle)
            require(len(payload) <= MAX_BYTES, 'resource_limit')
            reference = put(directory/'bundle.json', payload)
            reference['context'] = context
            load_bundle(reference, budget)
            control.ready(run['id'], reference)
            return control.run(run['id'])
        except Exception as error:
            control.fail(run['id'], error.code if isinstance(error, Failure) else 'build_failed')
            raise
        finally:
            if pinned:
                control.unpin(base['id'], owner)
