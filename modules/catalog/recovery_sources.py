"""Relocate a frozen, local PyIceberg SQL catalog; binary data stays unchanged."""
from io import BytesIO
from pathlib import Path
import sqlite3
from urllib.parse import unquote

import fastavro

from modules.common.contracts import digest, encoded, require


def relocate(originals, source, destination, roots):
    """Return relocated source bytes only, preserving Iceberg IDs and data files."""
    rewritten, visiting = {}, set()
    roots = [Path(root) for root in roots]

    def relative_uri(value):
        if not isinstance(value, str) or not value.startswith('file://'):
            return None
        path = Path(unquote(value[7:]))
        if any(path.is_relative_to(root) for root in roots):
            require(path.is_relative_to(source) and '..' not in path.parts, 'unsafe_path')
            relative = path.relative_to(source).as_posix()
            require(relative in originals or any(p.startswith(relative + '/') for p in originals), 'unsafe_path')
            return relative
        return None

    def transform(value):
        if isinstance(value, list):
            return [transform(item) for item in value]
        if isinstance(value, dict):
            result = {k: transform(v) for k, v in value.items()}
            if 'manifest_path' in value:
                relative = relative_uri(value['manifest_path'])
                require(relative is not None, 'unsafe_path', 'manifest outside managed source root')
                result['manifest_length'] = len(convert(relative))
            return result
        relative = relative_uri(value)
        if relative is not None:
            return (destination/relative).as_uri()
        return value

    def convert(relative):
        if relative in rewritten:
            return rewritten[relative]
        require(relative not in visiting, 'backup_corrupt')
        visiting.add(relative)
        raw = originals[relative]
        if relative.endswith('.json'):
            import json
            raw = encoded(transform(json.loads(raw)))
        elif relative.endswith('.avro'):
            reader = fastavro.reader(BytesIO(raw))
            schema, codec = reader.writer_schema, reader.codec
            metadata = {k: v for k, v in reader.metadata.items() if not k.startswith('avro.')}
            records, decoded_bytes = [], 0
            for row in reader:
                decoded_bytes += len(repr(row).encode())
                require(len(records) < 10000 and decoded_bytes <= 64 << 20, 'resource_limit')
                records.append(transform(row))
            output = BytesIO()
            fastavro.writer(output, schema, records, codec=codec, metadata=metadata)
            raw = output.getvalue()
        rewritten[relative] = raw
        visiting.remove(relative)
        return raw

    for relative in originals:
        if any((source/relative).is_relative_to(root) for root in roots):
            convert(relative)
    return rewritten


def relocate_sqlite(path, source, destination):
    """Update SQL catalog URI fields in a newly copied SQLite database only."""
    with sqlite3.connect(path) as conn:
        check = conn.execute('PRAGMA integrity_check').fetchone()
        require(check == ('ok',), 'backup_corrupt')
        require(conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone() is None, 'incompatible_backup')
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require(tables <= {'iceberg_tables', 'iceberg_namespace_properties'}, 'incompatible_backup')
        if 'iceberg_tables' in tables:
            for column in ('metadata_location', 'previous_metadata_location'):
                conn.execute(f'UPDATE iceberg_tables SET {column}=replace({column}, ?, ?)',
                             (source.as_uri()+'/', destination.as_uri()+'/'))
        require(conn.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'backup_corrupt')
