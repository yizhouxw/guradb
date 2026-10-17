"""Validate a bounded complete append chain; never infer changes from listings."""
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from modules.common.contracts import MAX_FILES, Failure, decode_json, require
from modules.connectors.iceberg import avro


def live_files(objects, meta, selected):
    schema = meta['schemas'][0]
    _, manifests = avro(objects.read(selected['manifest-list']))
    files = {}
    for manifest in manifests:
        require(manifest['content'] == 0 and manifest['partition_spec_id'] == meta['default-spec-id'])
        raw = objects.read(manifest['manifest_path'])
        require(len(raw) == manifest['manifest_length'], 'source_invalid')
        header, entries = avro(raw)
        require(header.get('format-version') == '2' and header.get('content', 'data') == 'data')
        require(json.loads(header['schema']) == schema and json.loads(header['partition-spec']) == [])
        for entry in entries:
            require(entry['status'] in (0, 1), 'unsupported_change', 'deleted manifest entry in append chain')
            data = entry['data_file']
            require(data['content'] == 0 and data['file_format'] == 'PARQUET' and data['partition'] == {})
            require(data['file_path'] not in files and len(files) < MAX_FILES, 'source_invalid')
            files[data['file_path']] = data
    require(files, 'unsupported_source')
    return files


def validate(objects, base, target):
    """Return durable append proof and check old source storage identities."""
    source = base['source']
    old = decode_json(objects.read(source['metadata_uri'], expected=source['metadata_sha256']))
    new = decode_json(objects.read(target['metadata_uri'], expected=target['metadata_sha256']))
    require(old['format-version'] == new['format-version'] == 2)
    require(old['table-uuid'] == new['table-uuid'] == source['table_uuid'], 'unsupported_change', 'table identity changed')
    for field in ('schemas', 'current-schema-id', 'partition-specs', 'default-spec-id', 'sort-orders', 'default-sort-order-id'):
        require(old.get(field) == new.get(field), 'unsupported_change', 'schema or layout changed')
    require(len(new['schemas']) == 1 and len(new['partition-specs']) == 1 and
            new['partition-specs'][0]['fields'] == [], 'unsupported_change')
    require(target['snapshot_id'] == new['current-snapshot-id'], 'unsupported_change', 'target must be metadata HEAD')
    base_id = int(source['snapshot_id'])
    snapshots = new.get('snapshots', [])
    require(len({s['snapshot-id'] for s in snapshots}) == len(snapshots), 'source_invalid')
    by_id = {s['snapshot-id']: s for s in snapshots}
    old_selected = next((s for s in old['snapshots'] if s['snapshot-id'] == base_id), None)
    require(old_selected is not None and by_id.get(base_id) == old_selected, 'history_gap', 'base history changed or expired')
    chain, cursor, visited = [], target['snapshot_id'], set()
    while cursor != base_id:
        require(cursor not in visited and len(chain) < 32, 'history_gap')
        visited.add(cursor)
        item = by_id.get(cursor)
        require(item is not None, 'history_gap', 'parent snapshot expired or target is not descendant')
        require(item.get('summary', {}).get('operation') == 'append', 'unsupported_change', 'only append commits supported')
        require(item.get('schema-id') == source['schema_id'], 'unsupported_change')
        chain.append(item)
        cursor = item.get('parent-snapshot-id')
    require(chain, 'unsupported_change', 'target must advance base snapshot')
    previous = live_files(objects, old, old_selected)
    old_paths = set(previous)
    for item in reversed(chain):
        current = live_files(objects, new, item)
        require(all(path in current and current[path] == data for path, data in previous.items()),
                'unsupported_change', 'append removed or rewrote a live file')
        require(set(current) > set(previous), 'unsupported_change', 'append must add files')
        previous = current
    dependencies = {d['uri']: d for d in source['dependencies']}
    for path in old_paths:
        require(path in dependencies, 'source_invalid')
        verify_identity(objects, dependencies[path])
    return {'base_snapshot': str(base_id), 'target_snapshot': str(target['snapshot_id']),
            'chain': [str(s['snapshot-id']) for s in reversed(chain)],
            'old_files': sorted(old_paths),
            'added_files': sorted(set(previous) - old_paths),
            'dependencies': objects.dependencies,
            'validation_stats': {'source_reads': objects.budget.reads, 'source_bytes': objects.budget.bytes},
            'execution': 'append_data_and_index_rebuild'}


def verify_identity(objects, dependency):
    """Reject mutable old paths without leaking external storage errors."""
    try:
        return _verify_identity(objects, dependency)
    except Failure:
        raise
    except Exception:
        raise Failure('source_unavailable', 'old source object is unavailable or unreadable') from None


def _verify_identity(objects, dependency):
    identity = dependency.get('identity')
    require(identity is not None, 'unsupported_change', 'base lacks immutable identity; rebuild snapshot')
    uri = urlsplit(dependency['uri'])
    objects.budget.check()
    require(objects.budget.reads < 128, 'resource_limit')
    if identity['kind'] == 'file-stat-v1':
        path = Path(unquote(uri.path))
        require(not path.is_symlink() and path.resolve(strict=True).is_relative_to(objects.local), 'source_invalid')
        current = path
        while current != objects.local:
            require(not current.is_symlink(), 'source_invalid')
            current = current.parent
        stat = path.stat()
        actual = {'kind': 'file-stat-v1', 'device': stat.st_dev, 'inode': stat.st_ino,
                  'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns}
    else:
        require(identity['kind'] == 's3-head-v1' and identity.get('etag'), 'unsupported_change')
        objects.budget.account(0)
        response = objects.s3.head_object(Bucket=uri.netloc, Key=unquote(uri.path).lstrip('/'))
        actual = {'kind': 's3-head-v1', 'etag': response.get('ETag'),
                  'version': response.get('VersionId'), 'size': response['ContentLength']}
    objects.budget.check()
    require(actual == identity, 'source_invalid', 'old source object identity changed')
