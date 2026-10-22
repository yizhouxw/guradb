"""Actual loopback transport faults and independently sealed invalid sources.

sealed-v1 is an explicit fault-fixture identity, never a claimed S3 VersionId.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import threading
import time

from modules.common.cf1a_primitives import ContractFailure
from tests.source_support.fixed_acceptance import instance
from tests.source_support.fixed_fixture import (encoded, envelope, facts, make_fixture,
    make_multisource_fixture, reseal_multisource, sha)
from tests.source_support.fixed_evidence import observation
from tests.storage_support.acceptance import rss_bytes, scope_snapshot
from tests.storage_support.fault_server import FaultServer, Response


def reseal(fixture, *, metadata_change=None, data_change=None):
    metadata = deepcopy(fixture['metadata'])
    objects = {}
    for ordinal, entry in enumerate(metadata['files']):
        raw = fixture['objects'][encoded(entry['object'])]
        if data_change is not None:
            raw = data_change(raw, ordinal)
        entry['object'] = {**entry['object'], 'size_bytes': len(raw), 'sha256': sha(raw)}
        objects[encoded(entry['object'])] = raw
    if metadata_change:
        metadata_change(metadata)
    raw = encoded(metadata)
    value = fixture['binding'].value
    ref = {**value['revision']['sources'][0]['metadata'], 'size_bytes': len(raw), 'sha256': sha(raw)}
    objects[encoded(ref)] = raw
    value['revision']['sources'][0]['metadata'] = ref
    value['revision']['objects'] = [ref, *[entry['object'] for entry in metadata['files']]]
    fixture.update(metadata=metadata, objects=objects, binding=envelope(value))
    return fixture


def responses(fixture):
    source = fixture['binding'].value['revision']['sources'][0]
    refs = [source['metadata'], *[entry['object'] for entry in fixture['metadata']['files']]]
    return [Response(body=fixture['objects'][encoded(ref)], version=ref['version']) for ref in refs]


def response_plan(server):
    return [{'body_sha256': sha(reply.body), 'body_size_bytes': len(reply.body),
        'version': reply.version, 'status': reply.status, 'header_delay_s': reply.header_delay,
        'body_delay_s': reply.body_delay, 'eof_delay_s': reply.eof_delay} for reply in server.responses]


def rejected(case, fixture, server, code, *, budget=None, timeout=10000, cancel_event=None, located=False):
    cancelled = cancel_event.is_set if cancel_event is not None else lambda: False
    reader = instance(fixture, server.endpoint, cancelled=cancelled, budget=budget, timeout=timeout)
    saved = Path(fixture['evidence_root'])/'case-inputs'/case
    saved.mkdir(parents=True, exist_ok=False)
    (saved/'binding.json').write_bytes(reader.scope.binding.encoded)
    (saved/'metadata.json').write_bytes(encoded(fixture['metadata']))
    if 'source_metadata' in fixture:
        (saved/'metadata-list.json').write_bytes(encoded(fixture['source_metadata']))
    inputs = []
    for number, (ref, raw) in enumerate(fixture['objects'].items()):
        name = f'object-{number}.bin'
        (saved/name).write_bytes(raw)
        inputs.append({'path': name, 'reference': json.loads(ref),
                       'sha256': sha(raw), 'size_bytes': len(raw)})
    (saved/'objects.json').write_bytes(encoded(inputs))
    scope, started = reader.scope, time.monotonic()
    original_deadline = scope.deadline
    stopped, trigger, watcher = threading.Event(), {}, None
    primary = None
    returned = None
    try:
        if cancel_event is not None:
            def cancel_in_data():
                until = time.monotonic() + .5
                while not stopped.is_set() and time.monotonic() < until:
                    requests = server.snapshot()['requests']
                    if requests >= 2:
                        trigger.update(requests_at_cancel=requests, monotonic_s=time.monotonic())
                        cancel_event.set()
                        return
                    stopped.wait(.001)
                trigger['data_admission_missing'] = True
            watcher = threading.Thread(target=cancel_in_data, name='p04-data-cancel-witness')
            watcher.start()
        try:
            if located:
                reader.read_located_batch(scope.binding, 0)
            else:
                reader.port.read_batch(scope.binding, 0)
        except ContractFailure as error:
            assert error.code == code, (case, error.code, code)
        else:
            raise AssertionError('invalid source produced a ReadBatch')
        returned = time.monotonic()
        assert reader._state is None and reader._failed
        assert scope.deadline <= original_deadline
        assert server.wait_idle() and server.active == 0
        elapsed = (returned - started) * 1000
        assert elapsed < (100 if code == 'cancelled' else 1000)
        if cancel_event is not None:
            assert trigger.get('requests_at_cancel') == 2
            assert started <= trigger['monotonic_s'] <= returned
            assert not trigger.get('data_admission_missing')
        assert rss_bytes() <= 512 << 20
        return {'case': case, 'rejected_as': code, 'returned_envelope': False,
            'elapsed_ms': elapsed, 'rss_peak_bytes': rss_bytes(), 'state_cleared': True,
            'original_query_deadline_monotonic_s': original_deadline,
            'scope_io': scope_snapshot(scope, returned), 'usage': scope.usage(), 'trace': scope.trace,
            'server': server.snapshot(), 'response_plan': response_plan(server), 'cancel_trigger': trigger,
            'input_directory': str(saved), 'identity_scope': 'sealed-v1 fault fixture; not backend version proof'}
    except BaseException as error:
        primary = error
        raise
    finally:
        stopped.set()
        if watcher is not None:
            watcher.join(1)
        observation(saved/'call-observation.json', reader=reader, server=server, primary=primary,
                    external_started_monotonic_s=started, external_returned_monotonic_s=returned,
                    cancel_trigger=trigger, cancel_thread_alive=watcher.is_alive() if watcher else False,
                    response_plan=response_plan(server))


def run_case(directory, case, fixture, replies, code, **arguments):
    fixture['evidence_root'] = directory
    server, primary = FaultServer(replies), None
    try:
        with server:
            return rejected(case, fixture, server, code, **arguments)
    except BaseException as error:
        primary = error
        raise
    finally:
        # FaultServer.__exit__ has already closed/joined even on call failures.
        observation(directory/('cleanup-' + case + '.json'), server=server, primary=primary,
                    response_plan=response_plan(server),
                    listener_alive=getattr(server, 'acceptor', None).is_alive() if hasattr(server, 'acceptor') else False,
                    connection_threads_alive=sum(thread.is_alive() for thread in server._threads))


def faults(directory):
    cases = []
    base = make_fixture(directory/'input')
    base['evidence_root'] = directory
    mutations = [
        ('snapshot-mismatch', 'corrupt_object', lambda m: m.update(snapshot_id='wrong-fixed-snapshot')),
        ('schema-digest', 'corrupt_object', lambda m: m['source_schema'][0].update(name='renamed')),
        ('unknown-metadata-field', 'invalid_contract', lambda m: m.update(unknown=True)),
        ('unknown-metadata-version', 'unsupported_version', lambda m: m.update(manifest_version='p04-fixed/2')),
        ('delete-files', 'unsupported_capability', lambda m: m.update(delete_files=['unsupported-delete'])),
        ('schema-evolution', 'unsupported_capability', lambda m: m.update(schema_evolution='rename')),
        ('wrong-row-group-coverage', 'corrupt_object', lambda m: m['files'][0]['row_group_rows'].__setitem__(0, 3)),
    ]
    for name, code, mutate in mutations:
        fixture = reseal(deepcopy(base), metadata_change=mutate)
        cases.append(run_case(directory, name, fixture, responses(fixture), code))
    for name, mutate in [('bad-parquet-magic', lambda raw, _: b'FAIL' + raw[4:]),
                         ('bad-footer-length', lambda raw, _: raw[:-8] + b'\xff\xff\xff\xffPAR1')]:
        fixture = reseal(deepcopy(base), data_change=mutate)
        cases.append(run_case(directory, name, fixture, responses(fixture), 'corrupt_object'))
    for number, options in enumerate(({'compression': 'SNAPPY'}, {'use_dictionary': True},
                                      {'data_page_version': '2.0'})):
        fixture = make_fixture(directory/f'unsupported-{number}', writer_options=options)
        fixture['evidence_root'] = directory
        cases.append(run_case(directory, 'unsupported-encoding-' + str(number), fixture,
                              responses(fixture), 'unsupported_capability'))
    rows = facts()
    duplicate = make_fixture(directory/'duplicate', rows=rows + [deepcopy(rows[0])],
                             split=[rows, [deepcopy(rows[0])]])
    duplicate['evidence_root'] = directory
    cases.append(run_case(directory, 'duplicate-in-later-file', duplicate, responses(duplicate), 'corrupt_object'))
    for name, index, attribute in [('slow-metadata-header', 0, 'header_delay'),
                                    ('slow-metadata-body', 0, 'body_delay'),
                                    ('slow-data-header', 1, 'header_delay'),
                                    ('slow-data-body', 1, 'body_delay'),
                                    ('slow-data-eof', 1, 'eof_delay')]:
        replies = responses(base)
        replies[index] = replace(replies[index], **{attribute: 2})
        cases.append(run_case(directory, name, base, replies, 'deadline'))
    replies = responses(base)
    replies[1] = replace(replies[1], body_delay=2)
    cases.append(run_case(directory, 'cancel-in-data-io', base, replies, 'cancelled',
                          cancel_event=threading.Event()))
    for name, budget in [('memory-before-io', {'memory_bytes': 1}),
                          ('request-cap-before-second-get', {'object_requests': 1}),
                          ('output-before-envelope', {'output_bytes': 1})]:
        cases.append(run_case(directory, name, base, responses(base), 'resource_limit', budget=budget))
    cases.append(run_case(directory, 'original-parent-deadline-shorter', base, responses(base),
                          'deadline', timeout=200))
    cases.extend(multisource_faults(directory))
    cases.extend(located_faults(directory))
    assert all(not case['returned_envelope'] and case['server']['active_connections'] == 0 for case in cases)
    return {'passed': True, 'mode': 'fault', 'cases': cases,
        'missing': ['real cloud faults', 'PG deadline pairing', 'B-L', 'I1'],
        'scope': 'actual local TCP faults and synthetic sealed invalid-source identities'}


def multisource_responses(fixture):
    sources = fixture['binding'].value['revision']['sources']
    refs = [source['metadata'] for source in sources]
    refs += [entry['object'] for metadata in fixture['source_metadata'] for entry in metadata['files']]
    return [Response(body=fixture['objects'][encoded(ref)], version=ref['version']) for ref in refs]


def multisource_faults(directory):
    fixture = make_multisource_fixture(directory/'two-source-input')
    broken = reseal_multisource(deepcopy(fixture), 1,
        metadata_change=lambda metadata: metadata.update(snapshot_id='wrong-mirror-snapshot'))
    cases = [run_case(directory, 'second-source-metadata-mismatch', broken,
                      multisource_responses(broken), 'corrupt_object')]
    broken = reseal_multisource(deepcopy(fixture), 1,
        data_change=lambda raw, _: b'FAIL' + raw[4:])
    cases.append(run_case(directory, 'second-source-data-corrupt', broken,
                          multisource_responses(broken), 'corrupt_object'))
    rows = facts()
    main = [row for row in rows if row['source_id'] == 'source-main']
    duplicate = {**deepcopy(main[0]), 'source_id': 'source-mirror'}
    broken = make_multisource_fixture(directory/'cross-source-duplicate', source_rows=[
        ('source-main', 'p04-main-v2', main), ('source-mirror', 'p04-mirror-v2', [duplicate])])
    cases.append(run_case(directory, 'duplicate-across-sources', broken,
                          multisource_responses(broken), 'corrupt_object'))
    return cases


def located_faults(directory):
    fixture = make_multisource_fixture(directory/'located-second-data-input')
    reseal_multisource(fixture, 1, data_change=lambda raw, _: b'FAIL' + raw[4:])
    cases = [run_case(directory, 'located-second-source-data-corrupt', fixture,
                      multisource_responses(fixture), 'corrupt_object', located=True)]
    single = make_fixture(directory/'located-cancel-input')
    replies = responses(single)
    replies[1] = replace(replies[1], body_delay=2)
    cases.append(run_case(directory, 'located-cancel-in-data-io', single, replies, 'cancelled',
                          cancel_event=threading.Event(), located=True))
    return cases
