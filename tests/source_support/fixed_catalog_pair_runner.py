"""Explicit pair driver with a 120s external watchdog; original modes unchanged."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from unittest.mock import patch

from tests.source_support.fixed_evidence import error_record, lab_record, write

ROOT = Path(__file__).resolve().parents[2]


def bounded(directory):
    """Parent process enforces the entire worker window, including cleanup."""
    private = ROOT/'artifacts'/'private'/('c3-watchdog-' + uuid.uuid4().hex)
    private.mkdir(parents=True)
    started = time.monotonic()
    command = [sys.executable, '-m', 'tests.source_support.fixed_catalog_pair_runner',
               '--worker', '--run-dir', str(directory)]
    process, timed_out, status, failure = None, False, 1, None
    try:
        with (private/'stdout.log').open('wb') as stdout, (private/'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(command, cwd=ROOT, start_new_session=True,
                                       stdout=stdout, stderr=stderr)
            try:
                status = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
    except BaseException as error:
        failure = error_record(error)
    finally:
        write(directory/'watchdog.json', {'budget_ms': 120000, 'timeout': timed_out,
            'elapsed_ms': (time.monotonic() - started) * 1000,
            'worker_returncode': None if process is None else process.returncode,
            'primary_error': failure, 'raw_logs_private': str(private), 'command': command})
    if timed_out or failure is not None:
        write(directory/'failure.json', {'passed': False,
            'code': 'pair_watchdog_timeout' if timed_out else 'pair_worker_start_or_wait_failed',
            'primary_error': failure, 'cleanup_confirmed': False,
            'state': 'HOLD; inspect owned-resources.json and private log pointer'})
    return int(status != 0 or timed_out or failure is not None)


def run(directory):
    from scripts.fixed_sources_acceptance import identity
    from scripts.m0lib.kit import PG, S3, docker, laboratory
    from tests.catalog_support.fixed_fixture import new_catalog
    from tests.source_support.fixed_acceptance import upload_multisource
    from tests.source_support.fixed_backend_cases import many_rows, start_fixture
    from tests.source_support.fixed_catalog_pair import PairQuery, positive, prepare
    from tests.source_support.fixed_catalog_pair_faults import cases as faults
    from tests.storage_support.log_capture import PrivateLogs
    from tests.storage_support.recording_proxy import RecordingProxy
    from modules.storage.fixed_cache import VerifiedCache
    import psycopg

    started, before = time.monotonic(), None
    private = ROOT/'artifacts'/'private'/('c3-' + uuid.uuid4().hex)
    result, failure, lifecycle, logs, lab = {}, None, None, None, None
    ownership = {'private_lab': str(private/'lab'), 'private_trace': str(private/'lab'/'trace.json'),
                 'network_attempts': [], 'container_attempts': [], 'cleanup_confirmed': False}
    write(directory/'owned-resources.json', ownership)
    def observed_docker(*arguments, **keywords):
        # Record only owner IDs before ambiguous creation; never persist env,
        # credentials, mounted config content or the full Docker argv publicly.
        if arguments[:2] == ('network', 'create'):
            ownership['network_attempts'].append(arguments[2])
        elif arguments and arguments[0] == 'run' and '--name' in arguments:
            ownership['container_attempts'].append(arguments[arguments.index('--name') + 1])
        write(directory/'owned-resources.json', ownership)
        return docker(*arguments, **keywords)
    def stop(signum, frame):
        raise TimeoutError('pair soft watchdog preserves cleanup window')
    previous = signal.signal(signal.SIGALRM, stop)
    previous_term = signal.signal(signal.SIGTERM, stop)
    signal.alarm(110)
    try:
        before = identity()
        write(directory/'source-before.json', before)
        with patch('scripts.m0lib.kit.docker', side_effect=observed_docker), PrivateLogs() as captured:
            try:
                with laboratory(private/'lab') as lab:
                    client, certification = start_fixture(lab, directory)
                    client.put_bucket_versioning(Bucket='m0-data', VersioningConfiguration={'Status': 'Enabled'})
                    assert client.get_bucket_versioning(Bucket='m0-data')['Status'] == 'Enabled'
                    pg = lab.container(PG, options=('-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
                                                   '-p', '127.0.0.1::5432'))
                    requested, actual = json.loads(docker('inspect', '--format',
                        '[{{json .Config.Image}},{{json .Image}}]', pg).stdout)
                    image = json.loads(docker('image', 'inspect', '--format',
                        '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}},'
                        '"repo_digests":{{json .RepoDigests}}}', actual).stdout)
                    assert requested == PG and image['id'] == actual
                    write(directory/'pg-image.json', {'requested_image': PG,
                        'actual_image_id': image['id'], 'container_image_id': actual,
                        'os': image['os'], 'architecture': image['architecture'],
                        'repo_digests': image['repo_digests'],
                        'scope': 'Docker-reported local requested index/actual ID/platform'})
                    dsn = ('host=127.0.0.1 port=' + lab.port(pg, 5432) +
                           ' dbname=postgres user=postgres sslmode=disable application_name=c3-pair')
                    def ready():
                        with psycopg.connect(dsn, connect_timeout=1):
                            return True
                    lab.wait(ready, seconds=15)
                    catalog, authority, principal, _ = new_catalog(dsn)
                    catalog.initialize()
                    full = upload_multisource(client, directory/'inputs-full11')
                    rows = many_rows()
                    dual = upload_multisource(client, directory/'inputs-dual130', source_rows=[
                        ('source-main', 'p04-main-v2', rows[:65]),
                        ('source-mirror', 'p04-mirror-v2', rows[65:])],
                        writer_options={'row_group_size': 16})
                    fixtures = {'full11': (full, 'c3-full11'), 'dual130': (dual, 'c3-dual130')}
                    for fixture, dataset in fixtures.values():
                        prepare(catalog, authority, principal, fixture, dataset)
                    samples = []
                    with RecordingProxy(client.meta.endpoint_url) as proxy:
                        for label, (fixture, dataset) in fixtures.items():
                            for located in (False, True):
                                cache = VerifiedCache(256 << 10)
                                for temperature in ('cold', 'warm'):
                                    case = f'{label}-{"located" if located else "ordinary"}-{temperature}'
                                    query = PairQuery(catalog, principal, fixture, dataset, proxy.endpoint,
                                                      directory/case, cache=cache)
                                    entry = {'case': case, 'passed': False}
                                    try:
                                        count = proxy.requests
                                        entry.update(positive(query, located=located,
                                            expected_sizes=(11,) if label == 'full11' else (64, 64, 2)))
                                        entry['get_requests'] = proxy.requests - count
                                        assert entry['get_requests'] == (4 if temperature == 'cold' else 0)
                                        entry['passed'] = True
                                    except BaseException as error:
                                        entry['primary_error'] = error_record(error)
                                        raise
                                    finally:
                                        try:
                                            entry['cleanup'] = query.finish()
                                        finally:
                                            samples.append(entry)
                                            write(directory/'positive-journal.json', samples)
                        negative = faults(catalog, principal, fixtures, proxy.endpoint, directory, pg, docker)
                    result = {'passed': True, 'positive': samples, 'fault': negative,
                        'fixture': certification, 'pg_image': PG, 's3_image': S3,
                        'scope': 'local actual PG to P03/P04, bounded component only',
                        'missing': ['PG server stop confirmation', 'complete PG server fees', 'PG/native memory',
                                    'cloud/HA/production scale', 'original-base full gates/remote CI/main']}
            finally:
                logs = captured.audit()
    except BaseException as error:
        failure = {'passed': False, 'primary_error': error_record(error)}
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        signal.signal(signal.SIGTERM, previous_term)
        after = None
        try:
            after = identity()
        except BaseException as error:
            failure = failure or {'passed': False, 'primary_error': error_record(error)}
        try:
            lifecycle = lab_record(lab, private, docker)
            owned = set(ownership['container_attempts'])
            ownership['cleanup_confirmed'] = (lifecycle['cleanup_confirmed'] is True and
                lab is not None and owned == lab.removed)
            write(directory/'owned-resources.json', ownership)
            if ownership['cleanup_confirmed'] is not True:
                lifecycle['cleanup_confirmed'] = False
        except BaseException as error:
            failure = failure or {'passed': False, 'primary_error': error_record(error)}
        if after != before or lifecycle is None or lifecycle['cleanup_confirmed'] is not True:
            failure = failure or {'passed': False, 'code': 'source_changed_or_cleanup_unconfirmed'}
        result = failure or result
        result.update(identity_before=before, identity_after=after, lifecycle=lifecycle, logging=logs,
                      elapsed_ms=(time.monotonic() - started) * 1000)
        write(directory/('failure.json' if failure else 'report.json'), result)
    return int(failure is not None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.run_dir.resolve()))
