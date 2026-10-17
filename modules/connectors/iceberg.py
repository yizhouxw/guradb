"""Iceberg v2 fixed metadata/snapshot import, deliberately fail-closed."""
from io import BytesIO
import json
from pathlib import Path
import uuid

import fastavro
import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.contracts import MAX_BYTES, MAX_FILES, MAX_ROWS, decode_json, digest, encoded, identifier, key, require
from modules.storage.objects import put


def avro(raw):
    reader = fastavro.reader(BytesIO(raw))
    require(reader.codec in ('null', 'deflate'), message='unsupported Avro codec')
    rows = []
    for row in reader:
        require(len(rows) < 4096, 'resource_limit', 'too many metadata entries')
        rows.append(row)
    return reader.metadata, rows


def snapshot(objects, metadata_uri, metadata_sha256, snapshot_id, dataset_id, table_name, key_field, output):
    require(identifier(table_name) and identifier(key_field), 'invalid_request')
    uuid.UUID(dataset_id)
    require(type(snapshot_id) is int and snapshot_id > 0, 'invalid_request')
    require(isinstance(metadata_sha256, str) and len(metadata_sha256) == 64, 'invalid_request')
    raw = objects.read(metadata_uri, expected=metadata_sha256)
    meta = decode_json(raw)
    require(meta.get('format-version') == 2)
    uuid.UUID(meta['table-uuid'])
    require(len(meta.get('schemas', [])) == 1 and len(meta.get('partition-specs', [])) == 1)
    require(meta['partition-specs'][0]['fields'] == [] and meta.get('default-spec-id') == meta['partition-specs'][0]['spec-id'])
    require(all(order['fields'] == [] for order in meta.get('sort-orders', [])))
    schema = meta['schemas'][0]
    require(meta['current-schema-id'] == schema['schema-id'] and schema['type'] == 'struct')
    fields = schema['fields']
    require(0 < len(fields) <= 64)
    require(len({f['id'] for f in fields}) == len(fields) and all(type(f['id']) is int and f['id'] > 0 for f in fields))
    require(len({f['name'] for f in fields}) == len(fields))
    require(all(identifier(f['name']) and f['type'] in ('long', 'string', 'boolean') and
                type(f['required']) is bool and 'initial-default' not in f and 'write-default' not in f for f in fields))
    primary = next((f for f in fields if f['name'] == key_field), None)
    require(primary is not None and primary['type'] in ('long', 'string'), 'invalid_key')
    selected = [s for s in meta.get('snapshots', []) if s['snapshot-id'] == snapshot_id]
    require(len(selected) == 1, 'snapshot_unavailable', 'explicit snapshot absent or expired')
    selected = selected[0]
    require(selected.get('schema-id') == schema['schema-id'])
    _, manifests = avro(objects.read(selected['manifest-list']))
    files, seen = [], set()
    # Inspect all metadata before any data GET. Never ignore deletes after planning.
    for manifest in manifests:
        require(manifest['content'] == 0 and manifest['partition_spec_id'] == meta['default-spec-id'])
        require(0 < manifest['manifest_length'] <= 4 << 20, 'resource_limit')
        manifest_raw = objects.read(manifest['manifest_path'])
        require(len(manifest_raw) == manifest['manifest_length'], 'source_invalid')
        header, entries = avro(manifest_raw)
        require(header.get('format-version') == '2' and header.get('content', 'data') == 'data')
        require(json.loads(header['schema']) == schema and json.loads(header['partition-spec']) == [])
        for entry in entries:
            require(entry['status'] in (0, 1, 2))
            data = entry['data_file']
            require(data['content'] == 0 and data['file_format'] == 'PARQUET' and data['partition'] == {})
            require(data.get('sort_order_id') in (None, 0) and not data.get('key_metadata'))
            if entry['status'] == 2:
                continue  # Iceberg DELETED data entries are not live rows.
            require(data['file_path'] not in seen and len(files) < MAX_FILES, 'source_invalid')
            seen.add(data['file_path'])
            require(type(data['record_count']) is int and 0 <= data['record_count'] <= MAX_ROWS, 'resource_limit')
            require(0 < data['file_size_in_bytes'] <= MAX_BYTES, 'resource_limit')
            files.append(data)
    require(files, 'unsupported_source', 'empty snapshot not yet supported')
    rows, keys, fragments = [], set(), []
    decoded_bytes = copied_bytes = 0
    arrow_fields = [pa.field(f['name'], {'long': pa.int64(), 'string': pa.string(), 'boolean': pa.bool_()}[f['type']],
                             nullable=not f['required']) for f in fields]
    expected = pa.schema(arrow_fields)
    for n, data in enumerate(files):
        objects.budget.check()
        raw = objects.read(data['file_path'], MAX_BYTES)
        require(len(raw) == data['file_size_in_bytes'], 'source_invalid')
        parquet = pq.ParquetFile(BytesIO(raw))
        actual = parquet.schema_arrow
        require(len(actual) == len(fields) and parquet.metadata.num_rows == data['record_count'], 'source_invalid')
        require(sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.metadata.num_row_groups)) <= 64 << 20,
                'resource_limit')
        for actual_field, field, expected_field in zip(actual, fields, expected):
            require(actual_field.name == field['name'] and actual_field.type == expected_field.type and
                    actual_field.nullable == expected_field.nullable and
                    (actual_field.metadata or {}).get(b'PARQUET:field_id') == str(field['id']).encode(), 'source_invalid',
                    'Parquet field ID/type/nullability differs from Iceberg schema')
        table = parquet.read()
        decoded_bytes += table.nbytes
        require(decoded_bytes <= 64 << 20 and len(rows) + len(table) <= MAX_ROWS, 'resource_limit')
        for row in table.to_pylist():
            logical = key(row[key_field], primary['type'])
            require(logical not in keys, 'invalid_key', 'NULL or duplicate logical key')
            require(all(not field['required'] or row[field['name']] is not None for field in fields), 'source_invalid')
            keys.add(logical)
            rows.append({'logical_key': logical, 'values': row})
        # Normalize only Arrow metadata; field-ID checks above prevent rename/reorder guessing.
        sink = BytesIO()
        pq.write_table(pa.Table.from_pylist(table.to_pylist(), schema=expected), sink, compression='snappy')
        payload = sink.getvalue()
        copied_bytes += len(payload)
        require(copied_bytes <= MAX_BYTES, 'resource_limit')
        name = digest(payload) + '.parquet'
        put(Path(output) / name, payload)
        fragments.append({'fragment_id': f'fragment_{n}', 'key': name, 'size_bytes': len(payload), 'sha256': digest(payload)})
    manifest = {'schema_version': 1, 'dataset_id': dataset_id, 'table_name': table_name,
                'schema': [{'name': f['name'], 'data_type': {'long': 'int8', 'string': 'text', 'boolean': 'bool'}[f['type']],
                            'nullable': not f['required']} for f in fields],
                'backend': {'kind': 'local', 'root': str(Path(output).resolve())}, 'files': fragments,
                'retention_mode': 'best-effort'}
    source = {'format': 'iceberg-v2', 'table_uuid': meta['table-uuid'], 'snapshot_id': str(snapshot_id),
              'metadata_uri': metadata_uri, 'metadata_sha256': metadata_sha256,
              'schema_id': schema['schema-id'], 'key_field': key_field, 'key_type': primary['type'],
              'dependencies': objects.dependencies}
    return {'manifest': manifest, 'source': source, 'rows': sorted(rows, key=lambda r:r['logical_key']),
            'stats': {'source_reads': objects.budget.reads, 'source_bytes': objects.budget.bytes}}
