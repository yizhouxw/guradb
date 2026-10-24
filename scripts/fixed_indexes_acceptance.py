#!/usr/bin/env python3
"""P06 module-only physical build/reopen/independent truth and bounded cost evidence."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def reopen(request):
    """Fresh process: no builder objects, no source-derived scoring or oracle evaluation."""
    from modules.common.cf1a_wire import Contract, canonical
    from modules.index.fixed_candidates import FixedArtifactReader
    from tests.index_support.fixed_fixture import LocalObjects, new_scope
    binding = Contract(canonical(request['binding']))
    query = Contract(canonical(request['query']))
    objects = LocalObjects()
    for item in request['registry']:
        objects.register(item['ref'], item['path'])
    scope = new_scope(binding)
    reader = FixedArtifactReader(objects.port(), scope)
    started = time.perf_counter()
    batch = reader.port().candidates(binding, query)
    cold_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    repeated = reader.port().candidates(binding, query)
    repeated_ms = (time.perf_counter() - started) * 1000
    assert batch.value['rows'] == repeated.value['rows']
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss if sys.platform == 'darwin' else rss * 1024
    return {'batch': batch.document, 'repeated_batch': repeated.document,
            'application_cold_ms': cold_ms, 'repeated_ms': repeated_ms, 'peak_rss_bytes': rss_bytes,
            'usage': scope.snapshot(), 'metrics': scope.metrics, 'requests': objects.requests,
            'cache_note': 'fresh reader/process; OS cache not cleared; no application content cache'}


def functional(output, enforce_costs=False, expected_source=None):
    from tests.index_support.fixed_audit import all_row_audit, compare_candidates
    from tests.index_support.fixed_fixture import build_pair, prepare, query_for
    fixture = prepare(output / 'physical')
    started = time.perf_counter()
    binding, indexes = build_pair(fixture)
    build_ms = (time.perf_counter() - started) * 1000
    # All source cells/features/tf/statistics checked independently before top-k.
    audit = all_row_audit(fixture, binding, indexes)
    write_json(output / 'binding.json', binding.document)
    write_json(output / 'all-row-audit.json', audit)
    query_results = []
    registry = [{'ref': ref, 'path': str(path)} for ref, path in fixture['objects'].registry.values()]
    for artifact in indexes:
        for suffix, ids, top_k in (('all', None, 100), ('window', None, 2),
                                   ('selected', ['r-a1-copy', 'r-a2'], 100), ('empty', [], 100)):
            query = query_for(binding, artifact, ids=ids, top_k=top_k)
            request = {'binding': binding.document, 'query': query.document, 'registry': registry,
                       'expected_source': expected_source}
            label = artifact['kind'] + '-' + suffix
            request_path, raw_path = output / (label + '-request.json'), output / (label + '-raw.json')
            write_json(request_path, request)
            child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--mode', 'reopen',
                                    '--input', str(request_path)], capture_output=True, text=True, timeout=30)
            (output / (label + '.stderr.log')).write_text(child.stderr)
            raw_path.write_text(child.stdout)
            assert child.returncode == 0, f'fresh reader failed: {label}; see stderr log'
            actual = json.loads(child.stdout)
            expected = (fixture['oracle'].bm25(['权限', '缓存']) if artifact['kind'] == 'bm25'
                        else fixture['oracle'].exact_l2([0, 0, 0]))
            if ids is not None:
                expected = [row for row in expected if row['record_id'] in ids]
            expected = expected[:top_k]
            comparison = compare_candidates(actual['batch'], expected, fixture)
            assert actual['metrics']['scanned_rows'] == 2 * (11 if artifact['kind'] == 'bm25' else 10)
            assert actual['usage']['object_requests'] == 4
            assert [attempt['key'] for attempt in actual['requests']] == [
                artifact['shards'][0]['key'], fixture['processing_ref']['key']] * 2
            if enforce_costs:
                assert actual['application_cold_ms'] <= 1000 and actual['repeated_ms'] <= 1000
                assert actual['peak_rss_bytes'] <= 512 << 20
            query_results.append({'label': label, 'scores': comparison,
                                  **{key: actual[key] for key in ('application_cold_ms', 'repeated_ms',
                                      'peak_rss_bytes', 'usage', 'metrics', 'cache_note')}})
    if enforce_costs:
        assert all(item['pipeline_ms'] <= 5000 for item in fixture['build_metrics'])
        assert all(artifact['build_usage']['elapsed_ms'] <= 5000 and
                   artifact['shards'][0]['size_bytes'] <= 1 << 20 for artifact in indexes)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    parent_rss = rss if sys.platform == 'darwin' else rss * 1024
    if enforce_costs:
        assert parent_rss <= 512 << 20
    for ref, path in fixture['objects'].registry.values():
        raw = path.read_bytes()
        assert len(raw) == ref['size_bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256']
    return {'status': 'pass', 'mode': 'performance' if enforce_costs else 'functional',
            'scope': 'single-source trusted processing/locator fixture; P03/P04/B-L/PG/I1 pending',
            'fixture_manifest_sha256': fixture['oracle'].documents['manifest_sha256'],
            'build_pair_pipeline_ms': build_ms, 'build_usage': [a['build_usage'] for a in indexes],
            'build_metrics': fixture['build_metrics'],
            'builder_driver_peak_rss_bytes': parent_rss,
            'all_row_audit': audit, 'queries': query_results}


def source_manifest():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                    cwd=ROOT).split(b'\0')
    files = {name.decode(): hashlib.sha256((ROOT / name.decode()).read_bytes()).hexdigest()
             for name in names if name and (ROOT / name.decode()).is_file()}
    return {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'checkout_sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            'files': files}


def environment():
    locks = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
             ('requirements-dev.lock', 'requirements-m0.lock', 'requirements-m1.lock', 'Cargo.lock')}
    return {'python': sys.version, 'pyarrow': importlib.metadata.version('pyarrow'),
            'platform': platform.platform(), 'machine': platform.machine(), 'cpu_count': os.cpu_count(),
            'dependency_locks': locks, 'topology': 'one local process plus fresh reader subprocesses; no cloud'}


def run(output, mode):
    output = output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('evidence directory must be within checkout')
    output.mkdir(parents=True, exist_ok=False)
    before = {'head': 'unavailable', 'checkout_sha256': 'unavailable', 'files': {}}
    result = {'status': 'failed', 'mode': mode}
    failed = False
    try:
        before = source_manifest()
        write_json(output / 'source-before.json', before)
        write_json(output / 'environment.json', environment())
        if mode == 'fault':
            from tests.index_support.fixed_faults import run_faults
            result = run_faults(output)
        else:
            result = functional(output, mode == 'performance', before)
    except BaseException:
        failed = True
        (output / 'failure.log').write_text(traceback.format_exc())
    finally:
        try:
            after = source_manifest()
        except Exception as error:
            after = {'manifest_error_type': type(error).__name__}
        write_json(output / 'source-after.json', after)
        result['unchanged_source'] = before == after
        result['git_head'] = before['head']
        result['checkout_sha256'] = before['checkout_sha256']
        if before != after or failed:
            result['status'] = 'failed'
        if before != after and not (output / 'failure.log').exists():
            (output / 'failure.log').write_text('checkout/source changed during verification; compare source-before/after.json\n')
        files = {path.relative_to(output).as_posix(): {'size_bytes': path.stat().st_size,
                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                 for path in sorted(output.rglob('*')) if path.is_file()}
        evidence = {'status': result['status'], 'git_head': before['head'],
                    'checkout_sha256': before['checkout_sha256'], 'files': files}
        manifest = output / 'evidence-manifest.json'
        write_json(manifest, evidence)
        result['evidence_manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        write_json(output / 'report.json', result)
    if result['status'] != 'pass':
        raise RuntimeError('fixed indexes verification failed; see retained evidence')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('functional', 'performance', 'fault', 'reopen'), required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    arguments = parser.parse_args()
    if arguments.mode == 'reopen':
        before = source_manifest()
        request = json.loads(arguments.input.read_text())
        try:
            if before != request['expected_source']:
                raise RuntimeError('fresh reader source differs from parent')
            result = reopen(request)
        finally:
            after = source_manifest()
            print(json.dumps({'reader_source_before': before['checkout_sha256'],
                              'reader_source_after': after['checkout_sha256'], 'head': after['head']}), file=sys.stderr)
        if before != after:
            raise RuntimeError('fresh reader source changed during query')
        result['unchanged_source'] = True
        result['checkout_sha256'] = before['checkout_sha256']
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return
    if arguments.output is None:
        parser.error('--output is required')
    result = run(arguments.output, arguments.mode)
    print(json.dumps({'status': result['status'], 'report': str(arguments.output / 'report.json')}))


if __name__ == '__main__':
    main()
