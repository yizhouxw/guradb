"""Real Parquet generated/read with locked PyArrow, independently of P04.

Mock fetch is for unit-level source/accounting tests only. It does not prove S3,
deadline, signing, or network costs; the real acceptance driver must do that.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.cf1a_wire import Contract
from modules.connectors.fixed_source_scope import SourceScope
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
from tests.outline_oracles.truth import OutlineOracle

ROOT = Path(__file__).resolve().parents[2]
FIELDS = [
    {'field_id': 1, 'name': 'record_id', 'type': 'text', 'nullable': False, 'role': 'logical_id'},
    {'field_id': 2, 'name': 'record_version', 'type': 'text', 'nullable': False, 'role': 'record_version'},
    {'field_id': 3, 'name': 'title', 'type': 'text', 'nullable': True, 'role': 'value'},
    {'field_id': 4, 'name': 'active', 'type': 'bool', 'nullable': True, 'role': 'value'},
    {'field_id': 5, 'name': 'priority', 'type': 'int8', 'nullable': True, 'role': 'value'},
    {'field_id': 6, 'name': 'tokens_text', 'type': 'text', 'nullable': True, 'role': 'value'}]
SOURCE_FIELDS = [{'source_field_id': 100 + field['field_id'],
                  **{key: field[key] for key in ('name', 'type', 'nullable')}} for field in FIELDS]


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def envelope(value):
    value = deepcopy(value)
    for name, column in (('revision', 'content_sha256'), ('view', 'descriptor_sha256')):
        value[name][column] = sha(encoded({key: child for key, child in value[name].items() if key != column}))
    return Contract(encoded({'contract_version': 'cf1a/1.0',
        'required_capabilities': ['fixed_read', 'typed_json_v1', 'strong_integrity'],
        'payload': {'read_binding': value}}))


def reference(raw, name):
    return {'backend_id': 'p04_fixture', 'bucket': 'm0-data', 'key': name, 'version': 'sealed-v1',
            'size_bytes': len(raw), 'sha256': sha(raw),
            'integrity': {'mode': 'whole_sha256', 'block_size': 0, 'block_sha256': [], 'proof_ref': ''}}


def facts():
    oracle = OutlineOracle()
    return [{**row, 'tokens_text': ' '.join(row['tokens']) if row['title'] is not None else None}
            for _, row in sorted(oracle.rows.items(), reverse=True)]


def make_fixture(directory, *, rows=None, split=None, writer_options=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = facts() if rows is None else deepcopy(rows)
    chunks = [rows] if split is None else split
    if not rows and split is None:
        chunks = []
    # A different physical order from both Resource and canonical source schema.
    order = [4, 1, 5, 0, 3, 2]
    physical = [SOURCE_FIELDS[index] for index in order]
    schema = pa.schema([pa.field(field['name'],
        {'text': pa.string(), 'int8': pa.int64(), 'bool': pa.bool_()}[field['type']],
        nullable=field['nullable'], metadata={b'PARQUET:field_id': str(field['source_field_id']).encode()})
        for field in physical])
    options = {'compression': 'NONE', 'use_dictionary': False, 'data_page_version': '1.0',
               'write_statistics': False, 'store_schema': False, 'row_group_size': 4}
    options.update(writer_options or {})
    objects, entries, expected_locations = {}, [], {}
    for ordinal, chunk in enumerate(chunks):
        path = directory / f'source-{ordinal}.parquet'
        table = pa.Table.from_pylist([{field['name']: row[field['name']] for field in physical}
                                     for row in chunk], schema=schema)
        pq.write_table(table, path, **options)
        raw, reader = path.read_bytes(), pq.ParquetFile(path)
        ref = reference(raw, path.name)
        groups = [reader.metadata.row_group(index).num_rows for index in range(reader.num_row_groups)]
        actual = [{'source_field_id': int(field.metadata[b'PARQUET:field_id']), 'name': field.name,
                   'type': {'string': 'text', 'int64': 'int8', 'bool': 'bool'}[str(field.type)],
                   'nullable': field.nullable} for field in reader.schema_arrow]
        assert actual == physical and sum(groups) == len(chunk)
        for group in range(reader.num_row_groups):
            for offset, row in enumerate(reader.read_row_group(group).to_pylist()):
                # Duplicate-ID negative fixtures deliberately leave two entries.
                expected_locations.setdefault(row['record_id'], []).append(
                    {'object': ref, 'row_group': group, 'row_offset': offset, 'row': row})
        objects[encoded(ref)] = raw
        entries.append({'object': ref, 'row_group_rows': groups})
    metadata = {'manifest_version': 'p04-fixed/1', 'source_id': 'p04-source',
        'source_version_id': 'p04-source-v2', 'snapshot_id': 'p04-snapshot-v2',
        'source_schema': SOURCE_FIELDS, 'files': entries, 'delete_files': [], 'schema_evolution': 'none'}
    raw = encoded(metadata)
    (directory/'metadata.json').write_bytes(raw)
    ref = reference(raw, 'metadata.json')
    objects[encoded(ref)] = raw
    value = deepcopy(json.loads((ROOT/'api/cf1a/golden.json').read_text())[0]['payload']['read_binding'])
    resource, revision, view, context = (value[key] for key in ('resource', 'revision', 'view', 'context'))
    resource.update(dataset_id='p04-fixture', schema_id='p04-schema', fields=deepcopy(FIELDS),
                    schema_sha256=sha(encoded(FIELDS)))
    source = revision['sources'][0]
    source.update(source_id='p04-source', source_version_id='p04-source-v2', format='manifest',
        format_version='1', snapshot_id='p04-snapshot-v2', metadata=ref,
        source_schema_sha256=sha(encoded(SOURCE_FIELDS)), resource_schema_sha256=resource['schema_sha256'],
        field_mapping=[{'source_field_id': 100 + field['field_id'], 'resource_field_id': field['field_id'],
                        'type': field['type'], 'source_type': field['type'], 'transform': 'identity'} for field in FIELDS])
    revision.update(dataset_id='p04-fixture', schema_id='p04-schema', data_revision_id='p04-revision-v2',
                    objects=[ref, *[entry['object'] for entry in entries]], sources=[source], parent_revision_ids=[])
    view.update(read_view_id='p04-view-v2', data_revision_id='p04-revision-v2',
                required_artifact_ids=[], index_requirements=[])
    value['indexes'] = []
    now = time.time_ns() // 1000000
    context.update(dataset_id='p04-fixture', schema_id='p04-schema', data_revision_id='p04-revision-v2',
        read_view_id='p04-view-v2', source_version_ids=['p04-source-v2'], artifact_ids=[],
        bound_at_unix_ms=now, deadline_unix_ms=now + 10000, remaining_ttl_ms=10000)
    context['auth'].update(dataset_id='p04-fixture', policy_epoch=1, expires_unix_ms=now + 60000)
    context['pin'].update(data_revision_id='p04-revision-v2', read_view_id='p04-view-v2',
                          expires_unix_ms=now + 60000)
    source['protected_until_unix_ms'] = now + 60000
    context['budget'].update(memory_bytes=8 << 20, object_bytes=8 << 20, object_requests=32,
                             output_bytes=8 << 20, concurrency=1, temp_bytes=1)
    return {'binding': envelope(value), 'objects': objects, 'metadata': metadata, 'rows': rows,
            'locations': expected_locations, 'directory': directory}


def unit_objects(fixture, **scope_arguments):
    scope = SourceScope(fixture['binding'], **scope_arguments)
    backend = FixedBackend('p04_fixture', 'm0-data', 'http://127.0.0.1:1',
                           CredentialSnapshot('fixture-key', 'fixture-secret'), True)
    objects = FixedObjects(scope, {'p04_fixture': backend}, lambda _: 1)
    attempts = []

    def fetched(scope, backend, ref, offset, length):
        scope.request(length)
        raw = fixture['objects'][encoded(ref)][offset:offset + length]
        scope.received(len(raw))
        attempts.append({'key': ref['key'], 'bytes': len(raw)})
        return raw
    return objects, fetched, attempts


def make_multisource_fixture(directory, *, source_rows=None, source_splits=None, writer_options=None):
    """Two actual files/manifests; P01 origin membership is never inferred from position."""
    directory = Path(directory)
    if source_rows is None:
        rows = facts()
        source_rows = [('source-main', 'p04-main-v2', [row for row in rows if row['source_id'] == 'source-main']),
                       ('source-mirror', 'p04-mirror-v2', [row for row in rows if row['source_id'] == 'source-mirror'])]
        assert [len(group[2]) for group in source_rows] == [10, 1]
    all_objects, all_locations, origins, all_rows, metadata, sources = {}, {}, {}, [], [], []
    value = None
    for number, (source_id, version, rows) in enumerate(source_rows):
        part = make_fixture(directory/str(number), rows=rows,
            split=None if source_splits is None else source_splits[number], writer_options=writer_options)
        if number:
            remap_physical_fields(part, number * 100, writer_options)
        part_value = part['binding'].value
        value = part_value if value is None else value
        source = deepcopy(part_value['revision']['sources'][0])
        source.update(source_id=source_id, source_version_id=version, snapshot_id=version + '-snapshot')
        current = deepcopy(part['metadata'])
        current.update(source_id=source_id, source_version_id=version, snapshot_id=source['snapshot_id'])
        replacements = {}
        for entry in current['files']:
            old = entry['object']
            ref = {**old, 'key': source_id + '/' + old['key']}
            replacements[encoded(old)] = ref
            all_objects[encoded(ref)] = part['objects'][encoded(old)]
            entry['object'] = ref
        raw = encoded(current)
        ref = reference(raw, source_id + '/metadata.json')
        source['metadata'] = ref
        all_objects[encoded(ref)] = raw
        for identifier, locations in part['locations'].items():
            for location in locations:
                updated = {**location, 'object': replacements[encoded(location['object'])],
                           'source_id': source_id, 'source_version_id': version}
                all_locations.setdefault(identifier, []).append(updated)
        for row in rows:
            origins[row['record_id']] = {'record_version': row['record_version'],
                'source_id': source_id, 'source_version_id': version}
        (directory/str(number)/'metadata.json').write_bytes(raw)
        metadata.append(current)
        sources.append(source)
        all_rows.extend(deepcopy(rows))
    assert value is not None
    value['revision'].update(sources=sources, objects=[ref for source, meta in zip(sources, metadata)
        for ref in [source['metadata'], *[entry['object'] for entry in meta['files']]]])
    value['context']['source_version_ids'] = [source['source_version_id'] for source in sources]
    fixture = {'binding': envelope(value), 'objects': all_objects, 'metadata': metadata[0],
        'source_metadata': metadata, 'rows': all_rows, 'locations': all_locations,
        'source_origins': origins, 'directory': directory}
    (directory/'fixed-binding.json').write_bytes(fixture['binding'].encoded)
    return fixture


def remap_physical_fields(fixture, shift, writer_options=None):
    """Independent writer changes actual field IDs, never a reader-side inferred mapping."""
    metadata, value, objects = deepcopy(fixture['metadata']), fixture['binding'].value, {}
    for field in metadata['source_schema']:
        field['source_field_id'] += shift
    source = value['revision']['sources'][0]
    for mapping in source['field_mapping']:
        mapping['source_field_id'] += shift
    source['source_schema_sha256'] = sha(encoded(metadata['source_schema']))
    for entry in metadata['files']:
        old = entry['object']
        reader = pq.ParquetFile(pa.BufferReader(fixture['objects'][encoded(old)]))
        table = reader.read()
        schema = pa.schema([field.with_metadata({b'PARQUET:field_id':
            str(int(field.metadata[b'PARQUET:field_id']) + shift).encode()}) for field in reader.schema_arrow])
        table = pa.Table.from_arrays(table.columns, schema=schema)
        options = {'compression': 'NONE', 'use_dictionary': False, 'data_page_version': '1.0',
                   'write_statistics': False, 'store_schema': False,
                   'row_group_size': entry['row_group_rows'][0]}
        options.update(writer_options or {})
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, **options)
        raw = sink.getvalue().to_pybytes()
        actual = pq.ParquetFile(pa.BufferReader(raw))
        assert [actual.metadata.row_group(i).num_rows for i in range(actual.num_row_groups)] == entry['row_group_rows']
        assert [int(field.metadata[b'PARQUET:field_id']) for field in actual.schema_arrow] == [
            int(field.metadata[b'PARQUET:field_id']) for field in schema]
        ref = reference(raw, old['key'])
        entry['object'] = ref
        objects[encoded(ref)] = raw
        (fixture['directory']/old['key']).write_bytes(raw)
        for locations in fixture['locations'].values():
            for location in locations:
                if location['object'] == old:
                    location['object'] = ref
    raw = encoded(metadata)
    ref = reference(raw, 'metadata.json')
    source['metadata'] = ref
    value['revision']['objects'] = [ref, *[entry['object'] for entry in metadata['files']]]
    objects[encoded(ref)] = raw
    fixture.update(metadata=metadata, binding=envelope(value), objects=objects)
    (fixture['directory']/'metadata.json').write_bytes(raw)


def reseal_multisource(fixture, index, *, metadata_change=None, data_change=None):
    """Seal deliberate negative fixtures; expected records remain independent."""
    value = fixture['binding'].value
    source = value['revision']['sources'][index]
    metadata = deepcopy(fixture['source_metadata'][index])
    objects = dict(fixture['objects'])
    objects.pop(encoded(source['metadata']))
    for number, entry in enumerate(metadata['files']):
        old = entry['object']
        raw = objects.pop(encoded(old))
        if data_change is not None:
            raw = data_change(raw, number)
        ref = {**old, 'size_bytes': len(raw), 'sha256': sha(raw)}
        entry['object'] = ref
        objects[encoded(ref)] = raw
    if metadata_change is not None:
        metadata_change(metadata)
    raw = encoded(metadata)
    source['metadata'] = {**source['metadata'], 'size_bytes': len(raw), 'sha256': sha(raw)}
    objects[encoded(source['metadata'])] = raw
    fixture['source_metadata'][index] = metadata
    fixture['metadata'] = fixture['source_metadata'][0]
    references = [ref for source, current in zip(
        value['revision']['sources'], fixture['source_metadata'])
        for ref in [source['metadata'], *[entry['object'] for entry in current['files']]]]
    # A DataRevision stores an immutable object once even in deliberately
    # cross-shared negative metadata. The source reader must reject that sharing.
    value['revision']['objects'] = list({encoded(ref): ref for ref in references}.values())
    members = {encoded(ref) for ref in value['revision']['objects']}
    fixture.update(binding=envelope(value), objects={key: raw for key, raw in objects.items() if key in members})
    return fixture
