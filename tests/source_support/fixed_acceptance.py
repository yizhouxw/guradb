"""Independent real-backend fixtures and external whole-call observations.

The fixture writer/reader is PyArrow. Production uses neither this module nor
its expected rows/locators. No mock fetch participates in these measurements.
"""
from copy import deepcopy
import time
import uuid

from modules.connectors.fixed_source_reader import FixedSourceReader
from modules.connectors.fixed_source_scope import SourceScope
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
from tests.source_support.fixed_fixture import encoded, envelope, make_fixture, make_multisource_fixture, sha
from tests.source_support.fixed_evidence import error_record, write
from tests.storage_support.acceptance import rss_bytes, scope_snapshot


def upload(client, directory, **arguments):
    fixture = make_fixture(directory, **arguments)
    prefix = 'p04-' + uuid.uuid4().hex
    refs = {}
    versions = []
    progress = []

    def put(raw, old):
        key = prefix + '/' + old['key']
        stage = {'key': key, 'size_bytes': len(raw), 'sha256': sha(raw), 'stage': 'first-put-started'}
        progress.append(stage)
        write(fixture['directory']/'upload-progress.json', progress)
        try:
            first = client.put_object(Bucket='m0-data', Key=key, Body=raw).get('VersionId')
            stage.update(stage='overwrite-started', fixed_version=first)
            second = client.put_object(Bucket='m0-data', Key=key, Body=b'later-unbound-version').get('VersionId')
            stage.update(stage='two-put-responses-received', later_version=second)
        except Exception as error:
            stage['primary_error'] = error_record(error)
            raise
        finally:
            write(fixture['directory']/'upload-progress.json', progress)
        assert first and second and first != 'null' and second != 'null' and first != second
        new = {**old, 'key': key, 'version': first}
        refs[encoded(old)] = new
        versions.append({'object': new, 'unbound_later_version': second})
        return new

    for entry in fixture['metadata']['files']:
        old = entry['object']
        entry['object'] = put(fixture['objects'][encoded(old)], old)
    metadata = encoded(fixture['metadata'])
    old_metadata = fixture['binding'].value['revision']['sources'][0]['metadata']
    metadata_ref = put(metadata, {**old_metadata, 'size_bytes': len(metadata), 'sha256': sha(metadata)})
    value = fixture['binding'].value
    value['revision']['objects'] = [metadata_ref, *[entry['object'] for entry in fixture['metadata']['files']]]
    value['revision']['sources'][0]['metadata'] = metadata_ref
    fixture['objects'] = {encoded(refs[old]): raw for old, raw in fixture['objects'].items()
                          if old in refs}
    fixture['objects'][encoded(metadata_ref)] = metadata
    for locations in fixture['locations'].values():
        for location in locations:
            location['object'] = refs[encoded(location['object'])]
    fixture['binding'] = envelope(value)
    fixture['versions'] = versions
    (fixture['directory']/'fixed-metadata.json').write_bytes(metadata)
    (fixture['directory']/'fixed-binding.json').write_bytes(fixture['binding'].encoded)
    return fixture


def refresh(fixture, *, budget=None, timeout=10000):
    """A distinct query gets its own scope; retained cache never grants access."""
    value = fixture['binding'].value
    now = time.time_ns() // 1000000
    context = value['context']
    context.update(query_id='p04-q-' + uuid.uuid4().hex, bound_at_unix_ms=now,
                   deadline_unix_ms=now + timeout, remaining_ttl_ms=timeout)
    context['auth']['expires_unix_ms'] = context['pin']['expires_unix_ms'] = now + 60000
    for source in value['revision']['sources']:
        source['protected_until_unix_ms'] = now + 60000
    if budget:
        context['budget'].update(budget)
    return envelope(value)


def instance(fixture, endpoint, *, cache=None, cancelled=lambda: False,
             authorize=lambda _: 1, budget=None, timeout=10000):
    binding = refresh(fixture, budget=budget, timeout=timeout)
    scope = SourceScope(binding, cancelled)
    backend = FixedBackend('p04_fixture', 'm0-data', endpoint,
                           CredentialSnapshot('m0-test-key', 'm0-test-secret'), True)
    objects = FixedObjects(scope, {'p04_fixture': backend}, authorize, cache=cache)
    reader = FixedSourceReader(objects)
    reader.acceptance_cohort_started = None
    reader.acceptance_journal = []
    reader.acceptance_directory = None
    return reader


def expected_rows(fixture):
    if 'expected_rows' in fixture:
        return fixture['expected_rows']
    return [{'record_id': row['record_id'], 'record_version': row['record_version'],
             'values': [row['record_id'], row['record_version'], row['title'], row['active'],
                        None if row['priority'] is None else str(row['priority']), row['tokens_text']]}
            for row in sorted(fixture['rows'], key=lambda item: item['record_id'])]


def batch_rows(batch):
    value = batch.value
    return [{'record_id': row['record_id'], 'record_version': row['record_version'],
             'values': [cell['value'] for cell in row['cells']]} for row in value['rows']]


def save_case_input(reader, fixture, directory):
    directory.mkdir(parents=True, exist_ok=False)
    reader.acceptance_directory = directory
    reader.acceptance_journal = []
    reader.acceptance_cohort_started = None
    (directory/'binding.json').write_bytes(reader.scope.binding.encoded)
    write(directory/'input-manifest.json', {'query_id': reader.scope.context['query_id'],
        'binding_sha256': reader.scope.binding.sha256, 'fixture_directory': str(fixture['directory']),
        'source_metadata': fixture.get('source_metadata', fixture['metadata']), 'expected_rows': expected_rows(fixture),
        'independent_locations': fixture['locations']})


def measured(reader, ordinal):
    scope = reader.scope
    before = scope.usage()
    start = time.monotonic()
    if reader.acceptance_cohort_started is None:
        reader.acceptance_cohort_started = start
    batch, sample, primary = None, None, None
    returned = None
    try:
        batch = reader.port.read_batch(scope.binding, ordinal)
        returned = time.monotonic()
        after, observed = scope.usage(), deepcopy(reader.last_observation)
        value, usage = batch.value, batch.value['usage']
        # Materialize observations before any acceptance assertion can fail.
        sample = {'ordinal': ordinal, 'context_sha256': scope.binding.sha256,
            'batch_sha256': batch.sha256, 'wire_bytes': len(batch.encoded), 'rows': batch_rows(batch),
            'last': value['last'], 'truncated': value['truncated'], 'usage': usage,
            'before': before, 'after': after, 'external_started_monotonic_s': start,
            'external_returned_monotonic_s': returned, 'page_elapsed_ms': (returned - start) * 1000,
            'cohort_elapsed_ms': (returned - reader.acceptance_cohort_started) * 1000,
            'finalization_tail_ms': (returned - observed['observed_monotonic_s']) * 1000,
            'post_precommit_tail_ms': (returned - observed['precommit_monotonic_s']) * 1000,
            'source_last_observation': observed, 'rss_peak_bytes': rss_bytes()}
        for key in ('object_requests', 'object_bytes', 'output_bytes'):
            assert usage[key] == after[key] - before[key], key
        assert 0 <= usage['elapsed_ms'] <= (returned - start) * 1000 + 1
        assert 0 < usage['memory_bytes'] <= 8 << 20
        assert len(value['rows']) <= 64 and len(batch.encoded) <= 768 << 10
        assert observed['observed_monotonic_s'] <= observed['precommit_monotonic_s'] <= returned
        assert (returned - start) < 1 and returned - reader.acceptance_cohort_started < 5
        assert scope.wire_bytes == scope.header_bytes + scope.object_bytes
        assert scope.deadline <= scope.started + scope.context['remaining_ttl_ms'] / 1000
        assert rss_bytes() <= 512 << 20
        sample['scope_io'] = scope_snapshot(scope, returned)
        return batch, sample
    except BaseException as error:
        primary = error
        raise
    finally:
        entry = {'ordinal': ordinal, 'context_sha256': scope.binding.sha256,
            'query_id': scope.context['query_id'], 'returned_envelope': batch is not None,
            'external_started_monotonic_s': start, 'external_returned_monotonic_s': returned,
            'after': scope.usage(), 'last_observation': deepcopy(reader.last_observation),
            'sample': sample, 'primary_error': error_record(primary) if primary is not None else None}
        reader.acceptance_journal.append(entry)
        if reader.acceptance_directory is not None:
            if batch is not None:
                (reader.acceptance_directory/f'call-{len(reader.acceptance_journal)-1}.json').write_bytes(batch.encoded)
            write(reader.acceptance_directory/'pages-journal.json', reader.acceptance_journal)


def enumerate_all(reader, fixture):
    pages, rows, ordinal = [], [], 0
    while True:
        batch, sample = measured(reader, ordinal)
        pages.append(sample)
        rows.extend(batch_rows(batch))
        assert sample['truncated'] is False
        if sample['last']:
            break
        ordinal += 1
        assert ordinal <= 1000
    assert rows == expected_rows(fixture)
    locations = reader._state['locations']
    assert len(locations) == len(rows)
    for identifier, expected in fixture['locations'].items():
        assert len(expected) == 1
        actual = locations[identifier]
        assert actual == {key: expected[0][key] for key in ('object', 'row_group', 'row_offset')} | {
            'source_version_id': expected[0].get('source_version_id', 'p04-source-v2')}
    return pages


def upload_multisource(client, directory, *, source_rows=None, writer_options=None):
    """Use the same fixture SDK; each metadata/data gets a fixed version then overwrite."""
    fixture = make_multisource_fixture(directory, source_rows=source_rows, writer_options=writer_options)
    prefix, refs, versions, progress = 'p04-' + uuid.uuid4().hex, {}, [], []

    def put(raw, old):
        key = prefix + '/' + old['key']
        stage = {'key': key, 'size_bytes': len(raw), 'sha256': sha(raw), 'stage': 'first-put-started'}
        progress.append(stage)
        write(fixture['directory']/'upload-progress.json', progress)
        try:
            first = client.put_object(Bucket='m0-data', Key=key, Body=raw).get('VersionId')
            stage.update(stage='overwrite-started', fixed_version=first)
            second = client.put_object(Bucket='m0-data', Key=key, Body=b'later-unbound-version').get('VersionId')
            stage.update(stage='two-put-responses-received', later_version=second)
        except Exception as error:
            stage['primary_error'] = error_record(error)
            raise
        finally:
            write(fixture['directory']/'upload-progress.json', progress)
        assert first and second and first != 'null' and second != 'null' and first != second
        ref = {**old, 'key': key, 'version': first}
        refs[encoded(old)] = ref
        versions.append({'object': ref, 'unbound_later_version': second})
        return ref

    originals = fixture['objects']
    objects, value = {}, fixture['binding'].value
    for metadata in fixture['source_metadata']:
        for entry in metadata['files']:
            old = entry['object']
            raw = originals[encoded(old)]
            entry['object'] = put(raw, old)
            objects[encoded(entry['object'])] = raw
    for source, metadata in zip(value['revision']['sources'], fixture['source_metadata']):
        raw = encoded(metadata)
        source['metadata'] = put(raw, {**source['metadata'], 'size_bytes': len(raw), 'sha256': sha(raw)})
        objects[encoded(source['metadata'])] = raw
    value['revision']['objects'] = [ref for source, metadata in zip(
        value['revision']['sources'], fixture['source_metadata'])
        for ref in [source['metadata'], *[entry['object'] for entry in metadata['files']]]]
    for locations in fixture['locations'].values():
        for location in locations:
            location['object'] = refs[encoded(location['object'])]
    fixture.update(binding=envelope(value), objects=objects, versions=versions)
    (fixture['directory']/'fixed-binding.json').write_bytes(fixture['binding'].encoded)
    (fixture['directory']/'fixed-metadata-list.json').write_bytes(encoded(fixture['source_metadata']))
    return fixture
