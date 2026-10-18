"""Bounded real PG SDK latency/RSS measurements against existing M0 budgets."""
import hashlib
import time

from m0lib.kit import laboratory
from m0lib.pgwire import LISTEN, client, expected


def run(directory):
    samples = []
    with laboratory(directory, count=8192) as lab:
        lab.s3()
        sql = 'SELECT * FROM documents ORDER BY id LIMIT 1000'
        for replica in range(5):
            lab.start(pg_listen=LISTEN)
            with client(lab) as sdk:
                assert sdk.connected['ok'], sdk.connected
                for mode in ['cold-process', 'warm-process']:
                    start = time.perf_counter()
                    result = sdk.query(sql, binary=True)
                    elapsed = (time.perf_counter() - start) * 1000
                    rss = lab.rss()
                    assert result['ok'] and result['rows'] == expected(lab.rows[:1000]), result
                    assert elapsed <= 10000 and rss <= 512 * 1024 * 1024, (elapsed, rss)
                    samples.append({'replica': replica, 'mode': mode, 'host_latency_ms': elapsed,
                                    'sdk_latency_ms': result['latency_ms'], 'rss_peak_bytes': rss,
                                    'returned_rows': len(result['rows'])})
        lab.event('pgwire_performance_passed', samples=len(samples))
        return {'passed': True, 'scope': 'PG wire bounded component smoke; no throughput or product baseline claim',
                'workload': {'rows': 8192, 'files': 2, 'seed': 0, 'sql': sql, 'result_rows': 1000,
                             'manifest_sha256': hashlib.sha256((lab.directory / 'manifest.json').read_bytes()).hexdigest(),
                             'object_bytes': sum(f['size_bytes'] for f in lab.manifest['files']), 'objects': lab.manifest['files']},
                'budgets': {'latency_ms': 10000, 'rss_bytes': 512 * 1024 * 1024},
                'environment': 'same isolated Docker engine and debug binary as enclosing M0 report; no OS/backend cache flush',
                'limitations': ['PG protocol does not expose source request/byte stats; object_bytes is fixture input size, not measured I/O',
                                'cold-process restarts server only; backend and OS caches remain uncontrolled'],
                'samples': samples}
