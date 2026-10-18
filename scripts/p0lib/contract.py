"""Frozen synthetic P0 inputs and measurement metadata; no business baseline."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import random
import subprocess

SEED = 17
INITIAL_ROWS = 256
APPEND_ROWS = 16
DIMENSIONS = 16
MODEL = 'm2-test-17'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def document(i):
    # Preserve the original 256 rows; appended batches add nullable-field coverage.
    return {'id': i, 'title': None if i >= INITIAL_ROWS and i % 16 == 0 else
            ['alpha alpha beta', 'beta', 'gamma database', 'database alpha'][i % 4],
            'active': None if i >= INITIAL_ROWS and i % 16 == 1 else i % 2 == 0}


def input_vectors(rows):
    rng = random.Random(SEED)
    return {r['id']: [rng.uniform(-1, 1) for _ in range(DIMENSIONS)] for r in rows}


def query_pairs(vectors, dataset, graph_dataset):
    vector = {'vector': vectors[19], 'model': MODEL, 'top_k': 10, 'candidate_limit': 100}
    graph = {'source_field': 'source', 'target_field': 'target', 'type_field': 'kind',
             'seeds': ['0', '2'], 'type': 'link', 'max_edges': 100, 'max_fanout': 100}
    return [
        (('search', dict(vector, text='alpha'), dataset),
         ('export', {'seed': 'local-p0'}, dataset)),
        (('search', dict(vector, vector_index='ann', nprobes=4), dataset),
         ('graph', graph, graph_dataset)),
        (('search', {'text': 'alpha beta', 'top_k': 10, 'candidate_limit': 100}, dataset),
         ('scan', {'limit': 1000}, dataset)),
        (('search', dict(vector, text='alpha', filter={'field': 'active', 'equals': True}), dataset),
         ('search', {'text': 'beta', 'top_k': 10, 'candidate_limit': 100,
                     'filter': {'field': 'title', 'equals': 'beta'}}, dataset)),
        (('search', dict(vector, filter={'field': 'title', 'equals': None}), dataset),
         ('search', dict(vector, filter={'field': 'active', 'equals': False}), dataset))]


def population(rows):
    sizes = [len((r['title'] or '').encode()) for r in rows]
    return {'rows': len(rows), 'unique_keys': len({r['id'] for r in rows}),
            'nulls': {name: sum(r[name] is None for r in rows) for name in ('title', 'active')},
            'text_utf8_bytes': {'min': min(sizes), 'max': max(sizes), 'total': sum(sizes)},
            'title_counts': dict(Counter(str(r['title']) for r in rows)),
            'filter_counts': {'active_true': sum(r['active'] is True for r in rows),
                              'active_false': sum(r['active'] is False for r in rows),
                              'title_beta': sum(r['title'] == 'beta' for r in rows),
                              'title_null': sum(r['title'] is None for r in rows)},
            'media_objects': 0, 'media_bytes': 0}


def workload_contract(duration, requested_updates, offsets, transport):
    rows = [document(i) for i in range(INITIAL_ROWS + APPEND_ROWS * len(offsets))]
    vectors = input_vectors(rows)
    pairs = query_pairs(vectors, 'documents', 'relations')
    # JSON object keys are strings: freeze that form before sorting and hashing.
    inputs = {'documents': rows, 'vectors': {str(key): vector for key, vector in vectors.items()},
              'relations': [{'id': i, 'source': i % 10, 'target': (i + 1) % 13,
                             'kind': 'link' if i % 2 == 0 else 'other'} for i in range(60)]}
    scripts = Path(__file__).resolve().parents[1]
    drivers = {p.relative_to(scripts).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted([scripts/'p0_acceptance.py', *(scripts/'p0lib').glob('*.py'),
                                scripts/'m0lib/kit.py', scripts/'m1lib/fixtures.py', scripts/'m2lib/fixtures.py'])}
    value = {'id': 'a0-synthetic-p0-v1', 'input_provenance': 'synthetic', 'driver_digests': drivers,
             'measurement_status': 'candidate-only; not a regression baseline',
             'seed': SEED, 'initial_rows': INITIAL_ROWS, 'append_rows': APPEND_ROWS,
             'requested_updates': requested_updates, 'effective_updates': len(offsets),
             'duration_seconds': duration, 'update_offsets_seconds': offsets,
             'initial_population': population(rows[:INITIAL_ROWS]), 'final_population': population(rows),
             'vector': {'dimensions': DIMENSIONS, 'distribution': 'CPython Random(17) uniform[-1,1)',
                        'model': MODEL, 'metric': 'squared_l2', 'preprocessing': 'identity-v1',
                        'query_record_id': 19, 'ann_partitions': 4, 'nprobes': 4},
             'text': {'analyzer': 'ASCII alnum lowercase', 'bm25': 'global-v2 k1=1.2 b=0.75',
                      'rrf_k': 60, 'skew': 'repeated titles; correlated active/title; exact counts recorded'},
             'query_pairs': pairs, 'query_concurrency': 2, 'writer_concurrency': 1,
             'worker_count': 3, 'transport': transport,
             'budgets': {'latency_ms': 10000, 'coordinator_rss_bytes': 512 << 20,
                         'worker_rss_bytes': 512 << 20, 'required_recall_at_10': 1.0,
                         'top_k': 10, 'candidate_limit': 100, 'writer_batches': 32,
                         'writer_rows': 10000, 'catalog_runs': 128},
             'cache_cases': {'uncontrolled_os_cache': 'measured', 'true_cold': 'not_run',
                             'controlled_warm': 'not_run', 'partial': 'not_run',
                             'over_total_cache_capacity': 'not_run'},
             'dataset_digest': sha(inputs), 'query_digest': sha(pairs)}
    value['workload_digest'] = sha(value)
    return value, inputs


def environment(root, pg_image):
    hardware = {'machine': platform.machine(), 'processor': platform.processor()}
    if platform.system() == 'Darwin':
        for name in ('hw.model', 'hw.memsize', 'hw.ncpu'):
            hardware[name] = subprocess.check_output(['sysctl', '-n', name], text=True).strip()
    locks = {name: hashlib.sha256((Path(root)/name).read_bytes()).hexdigest()
             for name in ('requirements-dev.lock', 'requirements-m0.lock', 'requirements-m1.lock', 'Cargo.lock')}
    return {'hardware': hardware, 'os': platform.platform(), 'python': platform.python_version(),
            'topology': 'one host, three local workers; no multi-machine claim',
            'object_store': 'local filesystem Iceberg/PyIceberg SQLite; PG18 Docker control',
            'pg_image': pg_image,
            'docker': json.loads(subprocess.check_output(['docker', 'version', '--format', '{{json .}}'], text=True)),
            'dependency_locks': locks, 'dependency_lock_digest': sha(locks),
            'unmeasured': ['OS/remote cache residency', 'native-child peak RSS',
                           'HTTP wire bytes', 'export coordinator I/O counters (not in public manifest)',
                           'remote S3 GET/HEAD (local source only)']}


def tree_bytes(root):
    return sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())
