"""Same-input bounded reference comparison; no competitor DB/native FTS claim."""
import argparse
import io
import importlib.metadata
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from m1_preview import Installed, ROOT, SQL, THREAD_ENV, checked_work, media_summary, read_json, save, sha
from m1_reference import Reference, tokens
from collections import Counter


def reference(work, version):
    row = next(v for v in read_json(work/'inputs.json')['manifest']['versions'] if v['name'] == version)
    directory = work/'data'/version
    return Reference(directory/'config.json', directory/'features.jsonl', row['features_sha256'])


def same_ranks(actual, expected):
    # Tolerance applies only to score values, never to rank/tie decisions.
    if [r['doc_id'] for r in actual] != [r['doc_id'] for r in expected]:
        raise ValueError('complete ranked Doc order differs')
    error = 0.0
    for left, right in zip(actual, expected):
        if not math.isclose(left['score'], right['score'], rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError('score differs beyond frozen numerical contract')
        error = max(error, abs(left['score']-right['score']))
    return error


def framework_reference(ref, membership, expected):
    import torch
    from PIL import Image
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    Image.MAX_IMAGE_PIXELS = 4_000_000
    documents = {r['doc_id']: r for r in ref.docs}
    consumed = 0
    start = time.perf_counter()

    class Samples(torch.utils.data.Dataset):
        def __init__(self, ids):
            self.ids = ids

        def __len__(self):
            return len(self.ids)

        def __getitem__(self, index):
            nonlocal consumed
            row = documents[self.ids[index]]
            evidence = ref.media(str(row['image_id']))
            raw = evidence['bytes']
            consumed += len(raw)
            if consumed > 32 << 20 or time.perf_counter()-start > 120:
                raise ValueError('reference reader exceeds data/time budget')
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != 'JPEG' or image.width*image.height > 4_000_000:
                    raise ValueError('unsupported bounded image')
                pixels = image.convert('RGB').resize((32, 32), Image.Resampling.BILINEAR).tobytes()
            tensor = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(32, 32, 3).permute(2, 0, 1).contiguous()
            return dict(doc_id=row['doc_id'], text=row['text'], asset_id=str(row['image_id']),
                media_sha256=sha(raw), media_bytes=len(raw), pixel_sha256=sha(tensor.numpy().tobytes()), image=tensor)

    epochs = []
    for epoch in range(2):
        for split in ('train', 'validation'):
            loader = torch.utils.data.DataLoader(Samples(membership[split]), batch_size=4,
                                                num_workers=0, shuffle=False, drop_last=False)
            batches = []
            for batch in loader:
                batches.append(dict(doc_ids=batch['doc_id'], texts=batch['text'], asset_ids=batch['asset_id'],
                    media_sha256=batch['media_sha256'], media_bytes=batch['media_bytes'].tolist(),
                    pixel_sha256=batch['pixel_sha256'], tensor_shape=list(batch['image'].shape),
                    tensor_dtype=str(batch['image'].dtype)))
            epochs.append(dict(epoch=epoch, split=split, members=len(membership[split]), batches=batches))
    if epochs != expected['epochs']:
        raise ValueError('same membership/framework bytes, pixels or tails differ')
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 4 << 30:
        raise ValueError('reference reader RSS exceeds 4 GiB')
    return dict(epochs=epochs, media_payload_bytes=consumed, elapsed_s=time.perf_counter()-start,
                rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, threads=torch.get_num_threads())


def comparison(work):
    if (work/'comparison.json').exists():
        raise ValueError('comparison output already exists; refusing overwrite')
    installed = Installed(work)
    state = read_json(work/'inputs.json')
    views = read_json(work/'views.json')
    refs = {}
    rows = []
    query_results = {}
    samples = {}
    materializations = []
    for version in ('A', 'B'):
        start = time.perf_counter()
        ref = reference(work, version)
        refs[version] = ref
        materializations.append(dict(version=version, elapsed_s=time.perf_counter()-start))
        projection = installed.view('query', views[version], '--sql', SQL)['result']
        expected = ref.query()
        if projection['rows'] != [[r['doc_id'], r['text']] for r in expected] or projection['truncated']:
            raise ValueError('projection differs')
        query_results[version] = expected
        samples[version] = ref.sample(work/'data'/version/'selection.json')
        actual_sample = installed.view('sample', views[version], '--selection', '/data/'+version+'/selection.json')['result']
        for split in ('train', 'validation'):
            if [r['doc_id'] for r in actual_sample[split]] != samples[version][split]:
                raise ValueError('group membership differs')
        by_id = {row['doc_id']: row for row in ref.docs}
        corpus_tokens = {key: Counter(tokens(row['text'])) for key, row in by_id.items()}
        for query in state['queries']:
            ranked_reference = {}
            qpath = work/'data'/version/'queries'/(query['id']+'.json')
            for mode in ('bm25', 'vector', 'hybrid'):
                start = time.perf_counter()
                if mode == 'bm25':
                    expected = ref.search(query['text'], 20)
                elif mode == 'vector':
                    expected = ref.vector(qpath, 20)
                else:
                    expected = ref.hybrid(qpath, query['text'], 20)
                ranked_reference[mode] = expected
                ref_seconds = time.perf_counter()-start
                if mode == 'bm25':
                    # View search is Top10. The pinned direct config exposes Top20,
                    # permitting full A15 ranking comparison without changing SQL.
                    actual = installed.call('search', '--config', '/data/'+version+'/config.json',
                                            '--query', query['text'], '--top-k', '20')
                else:
                    args = ['--query', '/data/'+version+'/queries/'+query['id']+'.json', '--top-k', '20']
                    if mode == 'hybrid':
                        args += ['--text-query', query['text']]
                    actual = installed.view(mode, views[version], *args)['result']
                if actual['source_sha256'] != ref.source_sha:
                    raise ValueError('result source identity differs')
                if mode != 'bm25' and (actual['features_sha256'] != ref.feature_sha or actual['space'] != ref.space
                        or actual['query_sha256'] != sha(qpath.read_bytes())):
                    raise ValueError('result feature/space/query identity differs')
                error = same_ranks(actual['hits'], expected)
                lexical = {row['doc_id']: (rank, row['score']) for rank, row in enumerate(ranked_reference['bm25'], 1)}
                vector_ranks = {row['doc_id']: (rank, row['score']) for rank, row in enumerate(ranked_reference.get('vector', []), 1)}
                lengths = {key: sum(value.values()) for key, value in corpus_tokens.items()}
                avg = sum(lengths.values()) / len(lengths)
                for hit in actual['hits']:
                    key = hit['doc_id']
                    original = by_id[key]
                    if hit['text'] != original['text'] or hit['media'] != dict(asset_id=str(original['image_id']),
                            image_path=original['image_path'], media_sha256=original['media_sha256'],
                            media_bytes=original['media_bytes'], media_version=original['media_version']):
                        raise ValueError('hit text/media identity differs from original row')
                    if mode == 'bm25':
                        if hit['dl'] != lengths[key]:
                            raise ValueError('BM25 document length differs')
                        for term in hit['terms']:
                            word = term['term']
                            df = sum(table[word] > 0 for table in corpus_tokens.values())
                            tf = corpus_tokens[key][word]
                            idf = math.log(1+(len(lengths)-df+.5)/(df+.5))
                            score = idf*tf*2.2/(tf+1.2*(.25+.75*lengths[key]/avg))
                            if term['tf'] != tf or not math.isclose(term['contribution'], score, abs_tol=1e-12, rel_tol=1e-12):
                                raise ValueError('BM25 explanation differs')
                    else:
                        vrank, vscore = vector_ranks[key]
                        brank, bscore = lexical.get(key, (None, None)) if mode == 'hybrid' else (None, None)
                        if hit['vector_rank'] != vrank or hit['bm25_rank'] != brank:
                            raise ValueError('component rank differs')
                        for field, value in (('vector_score', vscore), ('bm25_score', bscore),
                            ('vector_rrf', 1/(60+vrank)), ('bm25_rrf', 1/(60+brank) if brank else 0)):
                            observed = hit[field]
                            if (observed is None) != (value is None) or (value is not None and not math.isclose(observed, value, abs_tol=1e-12, rel_tol=1e-12)):
                                raise ValueError('fusion/cosine explanation differs')
                rows.append(dict(version=version, query=query['id'], mode=mode, source_sha256=ref.source_sha,
                    features_sha256=ref.feature_sha, complete_result=not actual['truncated'],
                    max_abs_score_difference=error, doc_ids=[r['doc_id'] for r in expected],
                    scores=[r['score'] for r in expected], reference_reused_materialization_s=ref_seconds,
                    rust_fresh_cli_s=installed.calls[-1]['elapsed_s']))
                if actual['truncated']:
                    raise ValueError('TopK must cover complete accepted output')
        for asset in sorted(set(str(r['image_id']) for r in ref.docs)):
            expected = ref.media(asset)
            actual = media_summary(installed.view('media', views[version], '--asset-id', asset))
            if actual['asset_id'] != asset or actual['media_sha256'] != expected['sha256'] or actual['media_bytes'] != len(expected['bytes']):
                raise ValueError('exact media differs')
    cold_process = []
    for query in state['queries'][:2]:
        start = time.perf_counter()
        p = subprocess.run([sys.executable, str(Path(__file__)), '--work-dir', str(work),
                            '--cold-query', query['id']], capture_output=True, timeout=20,
                           env={**os.environ, **THREAD_ENV})
        if p.returncode:
            raise ValueError('reference cold process failed: '+p.stderr[-1000:].decode())
        cold_process.append(dict(query=query['id'], elapsed_s=time.perf_counter()-start,
                                 result=json.loads(p.stdout), stdout_bytes=len(p.stdout)))
    algorithm_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    original = read_json(work/'reader/epochs.json')
    reader = framework_reference(refs['A'], samples['A'], original)
    # A tiny explicit application coordinator retains both version directories and
    # only publishes after full identity/Docset/media validation. This is app glue,
    # not a capability attributed to Arrow, NumPy or PyTorch.
    application = dict(format_version=1, current='B', retained={name: dict(source_sha256=ref.source_sha,
                       features_sha256=ref.feature_sha) for name, ref in refs.items()})
    save(work/'application-current.pending', application)
    os.replace(work/'application-current.pending', work/'application-current.json')
    report = dict(scope='same small-input accepted operations only; no platform/performance superiority',
        quality_equivalence=True, ranking_cases=rows, reference_algorithm_rss_bytes=algorithm_rss, projections=query_results, sample_members=samples,
        media_assets_per_version=3, reader=reader, application_coordinator=application,
        reference_io={name: ref.io for name, ref in refs.items()}, reference_materialization=materializations, reference_cold_process=cold_process,
        rust_calls=installed.calls, logical_output_bytes=sum(c['stdout_bytes'] for c in installed.calls),
        rust_cli_requests=len(installed.calls), physical_disk_io_bytes='UNKNOWN', os_and_container_cache='UNKNOWN',
        historical_integration_person_hours='UNKNOWN', inference_and_embedding_cost='EXCLUDED; identical existing features',
        timing_limit='fresh Rust CLI processes versus reused reference materializations; not a speed comparison',
        publication_limit='reference application retains immutable source/features and publishes a pointer; no crash/fencing platform certification')
    save(work/'comparison.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--cold-query')
    args = parser.parse_args()
    expected_versions = {'pyarrow': '22.0.0', 'numpy': '2.5.4', 'torch': '2.15.0', 'Pillow': '13.0.0'}
    if sys.version_info[:2] != (3, 12) or any(importlib.metadata.version(k) != v for k, v in expected_versions.items()):
        raise ValueError('comparison requires the explicitly frozen existing framework environment')
    work = checked_work(args.work_dir)
    if not work.is_dir():
        raise ValueError('existing prepared WORK required')
    work.relative_to(ROOT/'artifacts')
    os.environ.update(THREAD_ENV)
    if args.cold_query:
        query = next(row for row in read_json(work/'inputs.json')['queries'] if row['id'] == args.cold_query)
        ref = reference(work, 'A')
        result = dict(source_sha256=ref.source_sha, features_sha256=ref.feature_sha,
                      hits=ref.search(query['text'], 20), logical_io=ref.io)
    else:
        result = comparison(work)
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
