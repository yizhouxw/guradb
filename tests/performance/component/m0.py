"""Initial component baseline under frozen absolute budgets, never self-compare."""
import hashlib
import json
import platform
import time
from m0lib.kit import docker, laboratory, truth


def run(directory):
    samples = []
    with laboratory(directory, count=8192) as lab:
        lab.s3()
        expected = truth(lab.rows[:1000])
        source_bytes = sum(f['size_bytes'] for f in lab.manifest['files'])
        for replica in range(5):
            lab.start()
            for mode in ['cold-process', 'warm-process']:
                start = time.perf_counter()
                handle, page = lab.query()
                elapsed = (time.perf_counter() - start)*1000
                rss = lab.rss()
                assert page['rows'] == expected and page['truncated'] is True
                assert handle['stats']['source_reads'] == 2
                assert handle['stats']['source_bytes'] == source_bytes
                assert elapsed <= 10000 and rss <= 512*1024*1024, (elapsed, rss)
                samples.append({'replica': replica, 'mode': mode, 'latency_ms': elapsed, 'scan_bytes_per_second': source_bytes/(elapsed/1000), 'rss_peak_bytes': rss, **handle['stats']})
        lab.event('performance_passed', samples=len(samples))
        return {'suite': 'performance-smoke', 'passed': True, 'state': 'baseline-established', 'scope': 'M0 bounded full scan, not whole-product baseline',
                'workload': {'rows': 8192, 'files': 2, 'seed': 0, 'manifest_sha256': hashlib.sha256((lab.directory/'manifest.json').read_bytes()).hexdigest(),
                             'object_bytes': source_bytes, 'objects': lab.manifest['files'], 'result_rows': 1000, 'sql': 'SELECT * FROM documents ORDER BY id'},
                'budgets': {'latency_ms': 10000, 'rss_bytes': 512*1024*1024, 'logical_reads': 2},
                'environment': {'host': platform.platform(), 'docker': {key: json.loads(docker('info', '--format', '{{json .'+key+'}}').stdout) for key in ['ServerVersion','Architecture','NCPU','MemTotal','KernelVersion']},
                                'profile': 'dev debug=0; jobs=2; engine pool=32MiB; no data cache; backend/OS caches not flushed'}, 'samples': samples}
