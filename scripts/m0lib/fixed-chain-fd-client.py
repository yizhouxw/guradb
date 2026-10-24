"""Actual PG/SDK fixture assembly and one Rust attempt per fixed case.

Artifact prototype: not executed. Root must review/copy into runtime Source.
No Python SQL execution/filter is used for the query. The oracle below reads
fixture rows only. Missing actual source observations fail closed.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import struct
import subprocess
import sys
import time
import uuid

P04 = Path('/p04')
EVIDENCE = Path('/evidence')
BINARY = Path('/query/fixed-chain-fd-binary')
PROFILE = Path('/run/gura-worker-profile/sha256.bin')
RUNTIME_SHA = '3b246ebb3671212aa7fc38b0adf045838e2fe1787eacb1d3d3fc4715eefb267b'
PROFILE_SHA = '2209c379e98051bf70814293776b750add62eb5331fcf8a5708b90d33ecbaef3'
ARENA = 15760640  # Historical logical candidate; NOT W/PG/native proof.
SQL = {'full11': 'SELECT number AS priority, active, title FROM records ORDER BY id ASC',
       'dual130': 'SELECT number FROM records WHERE number >= $1 ORDER BY number DESC LIMIT 2'}


def need(value):
    if not value:
        raise ValueError('fixed chain observation contract')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def durable(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def bounded(path, cap):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= cap)
        raw = bytearray(info.st_size)
        view = memoryview(raw)
        while view:
            count = os.readv(fd, [view])
            need(count > 0)
            view = view[count:]
        need(os.read(fd, 1) == b'' and os.fstat(fd).st_size == info.st_size)
        return bytes(raw)
    finally:
        os.close(fd)


def file_sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            value.update(block)
    return value.hexdigest()


def json_value(path, cap):
    raw = bounded(path, cap)
    value = json.loads(raw)
    need(canonical(value) == raw)  # Also rejects duplicate keys/NaN/trailing data.
    return value


def config_bytes(principal, target):
    texts = [principal.tenant_id, principal.subject_id, principal.delegation_ref,
             'postgres', 'postgres', '', 'p04_fixture', 'm0-test-key', 'm0-test-secret', '']
    raw = [value.encode('utf-8') for value in texts]
    length = 96 + sum(map(len, raw))
    protection = min(source['protected_until_unix_ms'] for source in target.value['revision']['sources'])
    need(length <= 4096 and protection > time.time_ns() // 1000000 + 10000)
    return struct.pack('>4sHHIHH10HQQ12s32s', b'PCF2', 2, 0, length, 5432, 8333,
                       *map(len, raw), 0, protection, b'\0' * 12, bytes.fromhex(target.sha256)) + b''.join(raw)


def cell(kind, value):
    return {'type': 'null' if value is None else kind,
            'value': str(value) if kind == 'int8' and value is not None else value}


def truth(case, rows):
    fields = [(3, 'priority', 'int8', 'priority'), (4, 'active', 'bool', 'active'),
              (17, 'title', 'text', 'title')] if case == 'full11' else [(3, 'number', 'int8', 'priority')]
    columns = [{'output_ordinal': index, 'name': name, 'source_field_id': field,
                'type': kind, 'nullable': True} for index, (field, name, kind, key) in enumerate(fields)]
    candidates = {row['record_id']: row for row in rows}
    need(len(candidates) == len(rows))
    selected = sorted(rows, key=lambda row: row['record_id']) if case == 'full11' else sorted(
        [row for row in rows if row['priority'] is not None and row['priority'] >= 64],
        key=lambda row: row['priority'], reverse=True)[:2]
    expected = [[cell(kind, row[key]) for field, name, kind, key in fields] for row in selected]
    return columns, candidates, selected, expected


def verify_output(case, rows, result, binding_sha):
    need(set(result) == {'version', 'binding_sha256', 'request_sha256', 'columns', 'rows', 'complete'})
    need(result['version'] == 'p05-m1-result/v1' and result['complete'] is True
         and result['binding_sha256'] == binding_sha)
    query = {'version': 'p05-fixed-prepare/v1', 'binding_sha256': binding_sha, 'sql': SQL[case],
             'parameters': [] if case == 'full11' else [cell('int8', 64)],
             'limits': {'sql_bytes': 16384, 'request_bytes': 65536, 'parameters': 64, 'prepare_ms': 10000}}
    need(result['request_sha256'] == digest(canonical(query)))
    columns, candidates, selected, expected = truth(case, rows)
    need(result['columns'] == columns and [row['cells'] for row in result['rows']] == expected)
    seen = set()
    for index, row in enumerate(result['rows']):
        need(set(row) == {'cells', 'lineage'} and set(row['lineage']) == {'record_id', 'record_version'})
        key = row['lineage']['record_id']
        need(key in candidates and key not in seen)
        seen.add(key)
        source = candidates[key]
        need(row['lineage']['record_version'] == source['record_version'])
        if case == 'full11':
            need(key == selected[index]['record_id'])
        else:
            # Original ORDER BY number has no tie-breaker: validate every actual
            # lineage, not one arbitrary ID among identical highest values.
            need(cell('int8', source['priority']) == expected[index][0])


def stop_and_reap(process, record, cutoff):
    if process.poll() is None:
        if record.get('pgid') == process.pid:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()  # Direct owned Child only; unverified group is not signalled.
    try:
        remaining = max(0, cutoff - time.monotonic())
        if process.poll() is None and remaining > 0:
            process.wait(timeout=remaining)
    finally:
        record['binary_reaped'] = process.returncode is not None
        record['binary_exit'] = process.returncode
    need(record['binary_reaped'])
    # This direct-child wait does NOT prove separately grouped worker/cleanup
    # child reaping. Only the real Rust Child owners can supply that evidence.


def adopted_pending(case_dir, launcher_pid, cutoff, receipts):
    """PID1 may reap only exact pending children proved adopted by waitpid.

    The trusted launcher supplies durable typed evidence. A positive PID in a
    file alone never grants signal authority. Missing evidence, ECHILD, another
    group or exhausted original15s keeps HOLD. No generic orphan collection.
    """
    need(os.getpid() == 1 and time.monotonic() < cutoff)
    evidence = json_value(case_dir / 'process.evidence.json', 16384)
    pending = evidence['pending_children']
    need(type(pending) is list and len(pending) <= 2)
    seen_roles, seen_pids = set(), set()
    for item in pending:
        need(type(item) is dict and set(item) == {'role', 'pid', 'pgid'})
        role, pid, pgid = item['role'], item['pid'], item['pgid']
        need(role in ('worker', 'cleanup') and role not in seen_roles
             and type(pid) is int and 1 < pid < 1 << 31 and pid != launcher_pid
             and type(pgid) is int and pgid == pid and pid not in seen_pids)
        need(pid == evidence[role + '_pid'] and evidence[role + '_reaped'] is False)
        seen_roles.add(role)
        seen_pids.add(pid)
    for item in pending:
        role, pid, pgid = item['role'], item['pid'], item['pgid']
        need(time.monotonic() < cutoff)
        # ECHILD is a hard refusal, even if kill(pid,0) would report absence.
        observed, status = os.waitpid(pid, os.WNOHANG)
        signalled = False
        if observed == 0:
            # waitpid(0) proves it is our live child; group check now protects
            # only this owned/adopted group before any signal is sent.
            need(os.getpgid(pid) == pgid and time.monotonic() < cutoff)
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # Still require actual waitpid of the owned zombie below.
            signalled = True
            while observed == 0:
                need(time.monotonic() < cutoff)
                observed, status = os.waitpid(pid, os.WNOHANG)
                if observed == 0:
                    time.sleep(min(.001, max(0, cutoff - time.monotonic())))
        need(observed == pid and time.monotonic() < cutoff)
        receipts.append({'role': role, 'pid': pid, 'pgid': pgid, 'adopted_waitpid': True,
                         'wait_status': status, 'group_kill_after_adoption': signalled,
                         'reaped_within_original_watchdog': True})
    return receipts


def invoke(case_dir):
    record = {'phase': 'before-spawn', 'binary_reaped': False, 'hold': True}
    process, primary = None, None
    need(os.getpid() == 1)
    cutoff = time.monotonic() + 15  # Original query10s + at most cleanup5s, no restart.
    durable(case_dir / 'binary-intent.json', canonical({'argv': [str(BINARY), '--job', str(case_dir / 'job.json')],
                                                      'cutoff_monotonic': cutoff}))
    try:
        with (case_dir / 'binary.stdout').open('xb') as out, (case_dir / 'binary.stderr').open('xb') as err:
            process = subprocess.Popen([str(BINARY), '--job', str(case_dir / 'job.json')],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True,
                env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH': '/p04',
                     'PYTHONDONTWRITEBYTECODE': '1'}, cwd=P04)
            record.update(phase='spawned', pid=process.pid, pgid=os.getpgid(process.pid))
            need(record['pgid'] == process.pid)
            durable(case_dir / 'binary-started.json', canonical(record))
            process.wait(timeout=max(0, cutoff - time.monotonic()))
            need(time.monotonic() < cutoff and process.returncode == 0)
            record['hold'] = False
    except BaseException as error:
        primary = error
        record.update(error_class=type(error).__name__, hold=True)
        raise
    finally:
        try:
            if process is not None:
                stop_and_reap(process, record, cutoff)
                record['adopted_pending'] = []
                adopted_pending(case_dir, process.pid, cutoff, record['adopted_pending'])
                # Original launcher failure remains failure even if exact
                # pending descendants were successfully collected by PID1.
                need(not record['adopted_pending'] or primary is not None)
        except BaseException as error:
            record.update(reap_error_class=type(error).__name__, hold=True)
            if primary is None:
                raise
        finally:
            try:
                durable(case_dir / 'binary-terminal.json', canonical(record))
            except BaseException:
                if primary is None:
                    raise
                # Keep the first subprocess failure; missing terminal evidence
                # still prevents any success and stays visible to Root audit.


def verify_report(case, report, request_sha, binding_sha, object_output_bytes, result_bytes):
    need(report['version'] == 1 and report['case'] == case
         and report['status'] == 'normal-chain-executed-not-certified'
         and report['request_sha256'] == request_sha and report['binding_sha256'] == binding_sha)
    need(report['memory_certified'] is False and report['provider_output_pregrant_certified'] is False)
    need(report['original_t0_ns'] < report['absolute_cutoff_ns'])
    query, process = report['query'], report['process']
    family = case.removesuffix('-finish-only')
    need(family in ('full11', 'dual130'))
    expected_rows, expected_pages = (11, [11]) if family == 'full11' else (130, [64, 64, 2])
    # These MUST be observed by the provider. Null/missing currently fails; never
    # replace them with fixture constants or settled_attempts alone.
    source, pg, transport = query['source'], query['pg'], query['transport']
    need(source['actual_declared_rows'] == expected_rows
         and source['actual_declared_pages'] == len(expected_pages)
         and source['read_page_rows'] == expected_pages)
    need(source['read_attempts'] == source['settled_attempts'] == len(expected_pages)
         and source['known'] is True and source['pending_credit_bytes'] == 0
         and source['close_acked'] is True and source['cleanup_failed'] is False)
    need(pg['known'] is True and len(pg['counts']) == len(pg['phase_us']) == 11
         and pg['pending_sequence'] is None and pg['native_memory_bytes'] is None)
    need(pg['sequence'] == (15 if family == 'full11' else 25))
    recovery = query['finish_reconcile']
    integers = ('attempts', 'successes', 'operation_seq', 'pg_sequence', 'ordinal',
                'initial_data_receives', 'data_replays', 'settlement_attempts',
                'settlements', 'pending_bytes')
    booleans = ('requested', 'first_raw_discarded', 'unknown')
    need(set(recovery) == set(integers + booleans) | {'first_digest', 'cached_digest'}
         and all(type(recovery[key]) is int and 0 <= recovery[key] < 1 << 53 for key in integers)
         and all(type(recovery[key]) is bool for key in booleans))
    if case.endswith('-finish-only'):
        for key in ('first_digest', 'cached_digest'):
            digest = recovery[key]
            need(type(digest) is list and len(digest) == 32
                 and all(type(byte) is int and 0 <= byte < 256 for byte in digest))
        need(recovery['requested'] is True and recovery['first_raw_discarded'] is True
             and recovery['unknown'] is False and recovery['first_digest'] == recovery['cached_digest']
             and recovery['attempts'] == recovery['successes'] == 1
             and recovery['operation_seq'] == 2 and 0 < recovery['pg_sequence'] <= pg['sequence']
             and recovery['ordinal'] == 0 and recovery['initial_data_receives'] == 1
             and recovery['data_replays'] == 0
             and recovery['settlement_attempts'] == recovery['settlements'] == 1
             and 0 < recovery['pending_bytes'] <= 65536)
    else:
        need(all(recovery[key] == 0 for key in integers)
             and all(recovery[key] is False for key in booleans)
             and recovery['first_digest'] is None and recovery['cached_digest'] is None)
    need(transport['unknown'] is False and transport['application_pending'] == 0
         and transport['resident_pending'] == 0 and transport['wire_observed'] <= 8 << 20)
    producer = transport['producer_output']
    counters = ('pregranted', 'object_pending', 'a_unassigned', 'a_inflight',
                'object_observed', 'a_observed', 'observed_total', 'unused_released')
    need(set(producer) == set(counters) | {'final_close', 'unknown', 'released'})
    need(all(type(producer[key]) is int and 0 <= producer[key] < 1 << 53 for key in counters))
    need(producer['pregranted'] == (4 << 20) + 65536 + (8 << 20) + (768 << 10)
         and producer['object_observed'] == object_output_bytes
         and 0 < producer['a_observed'] <= (8 << 20) + (768 << 10)
         and producer['observed_total'] == producer['object_observed'] + producer['a_observed']
         and producer['observed_total'] == source['output_bytes']
         and producer['pregranted'] == producer['observed_total'] + producer['unused_released'])
    need(producer['object_pending'] == producer['a_unassigned'] == producer['a_inflight'] == 0
         and producer['final_close'] is True and producer['unknown'] is False
         and producer['released'] is True)
    sql_output = query['local']['sql_output_bytes']
    need(type(sql_output) is int and 0 < sql_output == result_bytes <= 2 << 20)
    need(source['output_bytes'] + sql_output + transport['extra_reserved']
         + producer['object_pending'] + producer['a_unassigned']
         + transport['application_pending'] <= 32 << 20)
    before_open = report['transport']['producer_output']
    need(set(before_open) == set(producer)
         and all(type(before_open[key]) is int and 0 <= before_open[key] < 1 << 53
                 for key in counters))
    need(before_open['pregranted'] == producer['pregranted']
         and before_open['object_pending'] == (4 << 20) + 65536
         and before_open['a_unassigned'] == (8 << 20) + (768 << 10)
         and before_open['a_inflight'] == before_open['observed_total']
         == before_open['object_observed'] == before_open['a_observed'] == 0
         and before_open['unused_released'] == 0 and before_open['final_close'] is False
         and before_open['unknown'] is False and before_open['released'] is False)
    need(process['worker_reaped'] is True and process['worker_exit'] == 0
         and process['cleanup_reaped'] is True and process['cleanup_exit'] == 0
         and process['pin_confirmed'] is True and process['cleanup_incomplete'] is False)
    need(process['pending_children'] == [])


def audit(catalog, request, target, binding, case_dir, setup_cutoff):
    from modules.catalog.cf1a_control import CatalogReadControl
    cutoff = min(setup_cutoff, time.monotonic() + 5)

    def checkpoint():
        need(time.monotonic() < cutoff)
        return cutoff

    control = CatalogReadControl(checkpoint, time.monotonic)
    primary = None
    try:
        with catalog.store.transaction(checkpoint(), control) as connection:
            row, original, stored = catalog.bindings.stored(connection, target.value['resource']['dataset_id'],
                                                          request.value['query_id'])
            need(original.encoded == request.encoded and stored.encoded == binding.encoded and row['released'] is True)
            need((row['pin_id'], row['lease_id']) == (binding.value['context']['pin']['pin_id'],
                                                   binding.value['context']['pin']['lease_id']))
        checkpoint()
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            durable(case_dir / 'independent-audit-pg.json', canonical(control.invoice))
        except BaseException:
            if primary is None:
                raise


def main():
    os.umask(0o077)
    setup_cutoff = time.monotonic() + 90  # Host original90s remains earlier authority.
    summary = {'passed': False, 'hold': True, 'scope': 'actual fixed chain prototype; NOT_CERTIFIED',
               'memory_certified': False, 'cases': []}
    try:
        need(len(sys.argv) == 1 and os.getpid() == 1)
        sys.path.insert(0, str(P04))
        import boto3
        from botocore.config import Config
        from modules.catalog.cf1a_codec import contract
        from modules.common.cf1a_wire import Contract
        from modules.connectors.fixed_fd_entry import observe_runtime
        from tests.catalog_support.fixed_fixture import new_catalog, request
        from tests.source_support.fixed_acceptance import upload_multisource
        from tests.source_support.fixed_backend_cases import many_rows
        from tests.source_support.fixed_catalog_pair import prepare_target
        from tests.source_support.fixed_fd_fixture import sql_target_from_uploaded

        def checkpoint():
            need(time.monotonic() < setup_cutoff)
            return setup_cutoff

        need(observe_runtime(checkpoint).hex() == RUNTIME_SHA and file_sha(PROFILE) == PROFILE_SHA)
        binary_sha = file_sha(BINARY)
        private = EVIDENCE / 'private'
        private.mkdir(mode=0o700, exist_ok=False)
        client = boto3.client('s3', endpoint_url='http://127.0.0.1:8333', region_name='us-east-1',
            aws_access_key_id='m0-test-key', aws_secret_access_key='m0-test-secret',
            config=Config(signature_version='s3v4', proxies={}, retries={'max_attempts': 0},
                          connect_timeout=1, read_timeout=2, s3={'addressing_style': 'path'}))
        client.create_bucket(Bucket='m0-data')
        client.put_bucket_versioning(Bucket='m0-data', VersioningConfiguration={'Status': 'Enabled'})
        need(client.get_bucket_versioning(Bucket='m0-data')['Status'] == 'Enabled')
        catalog, authority, principal, _ = new_catalog('host=127.0.0.1 port=5432 dbname=postgres user=postgres sslmode=disable')
        catalog.initialize()
        for case in ('full11', 'dual130', 'full11-finish-only', 'dual130-finish-only'):
            checkpoint()
            family = case.removesuffix('-finish-only')
            directory = private / case
            directory.mkdir(mode=0o700)
            summary['current_case'] = case
            options = {}
            if family == 'dual130':
                rows = many_rows()
                options = {'source_rows': [('source-main', 'p04-main-v2', rows[:65]),
                                          ('source-mirror', 'p04-mirror-v2', rows[65:])],
                           'writer_options': {'row_group_size': 16}}
            fixture = upload_multisource(client, directory / 'original-fixture', **options)
            dataset = 'fd-' + case + '-' + uuid.uuid4().hex
            assembled = sql_target_from_uploaded(fixture, client, directory / 'new-target', dataset,
                'schema-' + uuid.uuid4().hex, protected_until_unix_ms=time.time_ns() // 1000000 + 300000)
            target = prepare_target(catalog, authority, principal, assembled['target'], dataset)
            durable(directory / 'target.canonical.json', target.encoded)
            durable(directory / 'all-input-cells.json', canonical(assembled['truth']))
            original = request(principal, query='query-' + uuid.uuid4().hex, timeout_ms=10000, dataset=dataset).value
            original['budget'] = fixture['binding'].value['context']['budget']
            original['budget'].update(memory_bytes=256 << 20, output_bytes=32 << 20)
            bind_request = contract('bind_request', original)
            durable(directory / 'request.json', bind_request.encoded)
            durable(directory / 'config.bin', config_bytes(principal, target))
            job = {'version': 1, 'case': case, 'request_path': str(directory / 'request.json'),
                   'config_path': str(directory / 'config.bin'), 'result_path': str(directory / 'result.json'),
                   'report_path': str(directory / 'report.json'), 'worker_profile_sha256': PROFILE_SHA,
                   'runtime_manifest_sha256': RUNTIME_SHA, 'query_binary_sha256': binary_sha, 'worker_arena_bytes': ARENA}
            raw = canonical(job)
            need(len(raw) <= 4096)
            durable(directory / 'job.json', raw)
            checkpoint()
            invoke(directory)
            binding = Contract(bounded(directory / 'binding.canonical.json', 65536))
            value = binding.value
            need(binding.kind == 'read_binding' and all(value[key] == target.value[key]
                 for key in ('resource', 'revision', 'view', 'indexes')))
            result = json_value(directory / 'result.json', 32 << 20)
            report = json_value(directory / 'report.json', 65536)
            need(json_value(directory / 'process.evidence.json', 16384) == report['process'])
            verify_report(case, report, bind_request.sha256, binding.sha256,
                          sum(ref['size_bytes'] for ref in value['revision']['objects']),
                          (directory / 'result.json').stat().st_size)
            verify_output(family, fixture['rows'], result, binding.sha256)
            audit(catalog, bind_request, target, binding, directory, setup_cutoff)
            summary['cases'].append({'case': case, 'input_rows': len(fixture['rows']),
                'request_sha256': bind_request.sha256, 'target_sha256': target.sha256,
                'binding_sha256': binding.sha256, 'result_sha256': file_sha(directory / 'result.json'),
                'report_sha256': file_sha(directory / 'report.json'), 'all_cells_sha256': file_sha(directory / 'all-input-cells.json')})
        need(file_sha(BINARY) == binary_sha and file_sha(PROFILE) == PROFILE_SHA)
        summary.update(passed=True, hold=False)
    except BaseException as error:
        summary['first_error_class'] = type(error).__name__
    try:
        durable(EVIDENCE / 'driver-summary.json', canonical(summary))
    except BaseException:
        return 1
    return 0 if summary['passed'] and not summary['hold'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
