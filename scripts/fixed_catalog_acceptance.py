#!/usr/bin/env python3
"""Real PG18 fixed-catalog module evidence; never a cloud/HA/I1 certification."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import socket
import subprocess
import sys
import time
import traceback
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PG = 'postgres:18-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c'


def docker(*arguments, check=True):
    return subprocess.run(['docker', *arguments], capture_output=True, text=True, check=check, timeout=30)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def source_manifest():
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).split(b'\0')
    files = {name.decode(): hashlib.sha256((ROOT / name.decode()).read_bytes()).hexdigest()
             for name in paths if name and (ROOT / name.decode()).is_file()}
    return {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'files': files, 'checkout_sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def choose_loopback_port():
    # Docker receives an explicit published port so restart keeps the endpoint.
    # The selection is not a reservation; a competing bind must fail closed.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def runtime_components():
    # Regular imports execute only after source-before, inside run's lifecycle.
    import psycopg
    from modules.catalog import cf1a_store
    from tests.catalog_support.fixed_fixture import new_catalog, request
    from tests.catalog_support.pg_cases import Cases
    from tests.catalog_support.pg_transport import blackhole, paused_and_locked
    return psycopg, cf1a_store, new_catalog, request, Cases, blackhole, paused_and_locked


def preserve(result, stage, operation):
    """Evidence failures must not skip cleanup or turn missing artifacts green."""
    try:
        operation()
    except BaseException as error:
        result['status'] = 'failed'
        result['evidence_errors'].append({'stage': stage, 'error_type': type(error).__name__})
        return False
    return True


def run(output, mode):
    output = output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('evidence directory must be within checkout')
    output.mkdir(parents=True, exist_ok=False)
    started, name = time.monotonic(), 'gura-cf1a-' + uuid.uuid4().hex[:12]
    before = None
    result = {'status': 'failed', 'mode': mode, 'seed': 20261021,
        'scope': 'local PG18 trusted fixture component; real P03/P04/P06/HA/I1 pending',
        'cache_note': 'new adapter connection per operation; OS/PG caches uncontrolled', 'pg_image': PG,
        'python': platform.python_version(), 'platform': platform.platform(),
        'trace': [], 'successful_adapter_connections': [], 'evidence_errors': [],
        'connection_measurement_scope': 'successful adapter connects only; excludes failed attempts and independent SQL oracle connections'}
    created = False
    cases = None
    failure = None
    try:
        before = source_manifest()
        write(output / 'source-before.json', before)
        psycopg, cf1a_store, new_catalog, request, Cases, blackhole, paused_and_locked = runtime_components()
        result['psycopg'] = importlib.metadata.version('psycopg')
        requested_port = choose_loopback_port()
        result['published_ports'] = {'requested': requested_port}
        created = True  # Own the unique name before a possibly ambiguous docker response.
        docker('run', '-d', '--name', name, '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
               '-e', 'POSTGRES_DB=gura', '-e', 'POSTGRES_USER=gura', '-p', f'127.0.0.1:{requested_port}:5432', PG)
        port = int(docker('port', name, '5432').stdout.strip().rsplit(':', 1)[1])
        result['published_ports']['before_restart'] = port
        if port != requested_port:
            raise RuntimeError('owned PG published endpoint differs from request')
        dsn = f'host=127.0.0.1 port={port} dbname=gura user=gura sslmode=disable application_name=gura-fixed-catalog'
        ready = time.monotonic() + 15
        while True:
            try:
                with psycopg.connect(dsn, connect_timeout=2):
                    break
            except psycopg.Error:
                if time.monotonic() >= ready:
                    raise RuntimeError('PG readiness deadline exceeded') from None
                time.sleep(.05)
        catalog, authority, principal, _ = new_catalog(dsn)
        original_connect = cf1a_store.connect
        def observed_connect(*args):
            start = time.monotonic()
            connection = original_connect(*args)
            result['successful_adapter_connections'].append({'connect_ms': (time.monotonic() - start) * 1000, 'reused': False})
            return connection
        with patch.object(cf1a_store, 'connect', side_effect=observed_connect):
            catalog.initialize(); catalog.initialize()
            cases = Cases(catalog, authority, principal, dsn)
            if mode == 'control':
                from tests.catalog_support.pg_control_cases import controlled
                result['control'] = controlled(cases, name, docker, output)
                cases.audit_metadata()
                result['sql_state'] = cases.sql('SELECT dataset,generation,policy_epoch,owner_epoch,metadata_bytes '
                                                'FROM gura_cf1a.datasets ORDER BY dataset')
                write(output / 'actual-pg-records.json', cases.dump(output))
            else:
                cases.functional()
                cases.race_and_fence()
                if mode in ('all', 'fault'):
                    cases.admin_and_unknown()
                    cases.fresh_time_and_expired_cleanup()
                    result['transport'] = [blackhole(principal), *paused_and_locked(catalog, principal, dsn, name, docker)]
                if mode in ('all', 'performance'):
                    cases.capacity(); cases.byte_capacity()
                if mode == 'performance':
                    from tests.catalog_support.pg_quota_cases import remaining_capacities
                    remaining_capacities(cases)
                cases.audit_metadata()
                # New connections after a real PG restart recover immutable persisted bytes.
                stable = catalog.port(principal).bind(request(principal, 'restart-query', dataset='dataset-functional'))
                docker('restart', name)
                result['published_ports']['after_restart'] = int(docker('port', name, '5432').stdout.strip().rsplit(':', 1)[1])
                if result['published_ports']['after_restart'] != port:
                    raise RuntimeError('owned PG published endpoint changed after restart')
                ready = time.monotonic() + 15
                while True:
                    try:
                        catalog.initialize()
                        break
                    except Exception:
                        if time.monotonic() >= ready:
                            raise
                        time.sleep(.05)
                assert catalog.port(principal).bind(request(principal, 'restart-query', dataset='dataset-functional')).encoded == stable.encoded
                catalog.port(principal).release_pin(stable)
                cases.event('real-pg-restart-immutable-binding', state='pass', binding_sha256=stable.sha256)
                result['sql_state'] = cases.sql('SELECT dataset,generation,policy_epoch,owner_epoch,metadata_bytes '
                                                'FROM gura_cf1a.datasets ORDER BY dataset')
                write(output / 'restart-binding.json', stable.document)
                write(output / 'actual-pg-records.json', cases.dump(output))
        result['image_identity'] = json.loads(docker('inspect', '--format', '{{json .Image}}', name).stdout)
        result['status'] = 'pass'
    except BaseException:
        failure = traceback.format_exc()
        preserve(result, 'failure-log', lambda: (output / 'failure.log').write_text(failure))
    finally:
        if cases is not None:
            result['trace'] = cases.trace
            result['fixture_now_unix_ms'] = cases.now
            preserve(result, 'actual-inputs', lambda: write(output / 'actual-inputs.json', cases.inputs))
        if created:
            cleanup_errors = []
            for action in ('unpause', 'logs', 'remove'):
                try:
                    if action == 'unpause':
                        docker('unpause', name, check=False)
                    elif action == 'logs':
                        logs = docker('logs', name, check=False)
                        result['service_logs_returncode'] = logs.returncode
                        if logs.returncode:
                            cleanup_errors.append({'action': 'logs', 'returncode': logs.returncode})
                        filename = 'postgres.log' if logs.returncode == 0 else 'postgres-log-extraction-error.log'
                        preserve(result, 'service-log-write', lambda: (output / filename).write_text(logs.stdout + logs.stderr))
                    else:
                        result['service_cleanup_returncode'] = docker('rm', '-fv', name, check=False).returncode
                except BaseException as error:
                    cleanup_errors.append({'action': action, 'error_type': type(error).__name__})
            result['cleanup_errors'] = cleanup_errors
        try:
            after = source_manifest()
        except BaseException as error:
            after = {'manifest_error_type': type(error).__name__}
            result['evidence_errors'].append({'stage': 'source-after-capture', 'error_type': type(error).__name__})
        preserve(result, 'source-after-write', lambda: write(output / 'source-after.json', after))
        result['unchanged_source'] = before is not None and before == after
        result['elapsed_seconds'] = time.monotonic() - started
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result['driver_peak_rss_bytes'] = rss if sys.platform == 'darwin' else rss * 1024
        result['unmeasured'] = ['native PG process peak RSS', 'OS cache residency', 'production latency/QPS']
        if (not result['unchanged_source'] or result['elapsed_seconds'] > 120 or result.get('service_cleanup_returncode', 0)
                or result.get('cleanup_errors') or result['evidence_errors']):
            result['status'] = 'failed'
        def evidence_hashes():
            result['evidence_files'] = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted(output.rglob('*')) if p.is_file()}
        preserve(result, 'evidence-hashes', evidence_hashes)
        preserve(result, 'final-report', lambda: write(output / 'report.json', result))
    if failure or result['status'] != 'pass':
        raise RuntimeError('fixed catalog verification failed; see retained evidence')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--mode', choices=('all', 'functional', 'performance', 'fault', 'control'), default='all')
    args = parser.parse_args()
    result = run(args.run_dir, args.mode)
    print(json.dumps({'status': result['status'], 'elapsed_seconds': result['elapsed_seconds'],
                      'report': str(args.run_dir / 'report.json')}))


if __name__ == '__main__':
    main()
