"""Versioned metadata observations; never content reads or deletion authority."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import stat
import sys
import time

VERSION = 1
MAX_BYTES = 32 << 20
META = ('dev', 'ino', 'mode', 'size', 'mtime_ns', 'ctime_ns', 'nlink')

class RecordError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise RecordError(message)

def metadata(st):
    return dict(zip(META, (st.st_dev, st.st_ino, st.st_mode, st.st_size,
                           st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)))

def absolute(path):
    value = os.fspath(path)
    require(os.path.isabs(value) and '..' not in Path(value).parts, 'explicit absolute path required')
    return Path(value)

def directory(path):
    path = absolute(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise

def totals(entries):
    regular = [e for e in entries if e['type'] == 'file']
    unique = {}
    for entry in regular:
        key = (entry['dev'], entry['ino'])
        require(key not in unique or unique[key] == entry['size'], 'inconsistent hardlink sizes')
        unique[key] = entry['size']
    return {'entries': len(entries), 'files': len(regular),
            'directories': sum(e['type'] == 'directory' for e in entries),
            'symlinks': sum(e['type'] == 'symlink' for e in entries),
            'other': sum(e['type'] == 'other' for e in entries),
            'logical_file_bytes': sum(e['size'] for e in regular),
            'unique_inode_file_bytes': sum(unique.values())}

def open_root(root):
    if root == Path('/'):
        return directory(root)
    parent = directory(root.parent)
    try:
        before = os.stat(root.name, dir_fd=parent, follow_symlinks=False)
        require(stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode), 'root must be a physical file or directory')
        fd = os.open(root.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC |
                     (os.O_DIRECTORY if stat.S_ISDIR(before.st_mode) else 0), dir_fd=parent)
        if metadata(os.fstat(fd)) != metadata(before):
            os.close(fd)
            raise RecordError('root changed while opening')
        return fd
    finally:
        os.close(parent)

def snapshot(root, max_entries=50000, max_depth=32, max_bytes=MAX_BYTES, timeout=30):
    for value, maximum in [(max_entries, 50000), (max_depth, 32), (max_bytes, MAX_BYTES), (timeout, 30)]:
        require(type(value) is int and 1 <= value <= maximum, 'invalid snapshot bound')
    root = absolute(root)
    started = time.monotonic_ns()
    deadline = started + timeout * 1_000_000_000
    entries = []
    estimated = 0
    rootfd = open_root(root)
    def walk(fd, prefix, depth):
        nonlocal estimated
        before = metadata(os.fstat(fd))
        with os.scandir(fd) as iterator:
            for item in iterator:
                require(time.monotonic_ns() < deadline, 'snapshot deadline exceeded; no complete output')
                require(len(entries) < max_entries, 'entry limit exceeded; no complete output')
                require(depth <= max_depth, 'depth limit exceeded; no complete output')
                name = item.name
                path = f'{prefix}/{name}' if prefix else name
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                kind = ('file' if stat.S_ISREG(st.st_mode) else 'directory' if stat.S_ISDIR(st.st_mode)
                        else 'symlink' if stat.S_ISLNK(st.st_mode) else 'other')
                entry = {'path': path, 'type': kind, **metadata(st)}
                if kind == 'symlink':
                    entry['target'] = os.readlink(name, dir_fd=fd)
                estimated += len(json.dumps(entry, ensure_ascii=True, separators=(',', ':')).encode()) + 1
                require(estimated <= max_bytes, 'output byte limit exceeded; no complete output')
                entries.append(entry)
                if kind == 'directory':
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                    try:
                        require((os.fstat(child).st_dev, os.fstat(child).st_ino) == (st.st_dev, st.st_ino), 'directory replaced during scan')
                        walk(child, path, depth + 1)
                    finally:
                        os.close(child)
        require(metadata(os.fstat(fd)) == before, 'directory metadata changed during scan')
    try:
        before = metadata(os.fstat(rootfd))
        if stat.S_ISDIR(before['mode']):
            walk(rootfd, '', 1)
        else:
            entries.append({'path': '.', 'type': 'file', **before})
        after = metadata(os.fstat(rootfd))
    finally:
        os.close(rootfd)
    result = {'schema_version': VERSION, 'kind': 'resource_snapshot', 'status': 'complete',
              'root': str(root), 'root_before': before, 'root_after': after,
              'observed_at_ns': time.time_ns(), 'duration_ns': time.monotonic_ns() - started,
              'atomic': False, 'historical_peak': 'UNKNOWN', 'exclusions': [],
              'limits': {'entries': max_entries, 'depth': max_depth, 'bytes': max_bytes, 'seconds': timeout},
              'entries': sorted(entries, key=lambda e: e['path']), 'totals': totals(entries)}
    require(time.monotonic_ns() < deadline, 'snapshot deadline exceeded; no complete output')
    require(len(encode(result)) <= max_bytes, 'output byte limit exceeded; no complete output')
    result['duration_ns'] = time.monotonic_ns() - started
    require(time.monotonic_ns() < deadline, 'snapshot deadline exceeded; no complete output')
    return result

def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode()

def write_new(path, value, roots=()):
    path = absolute(path)
    for root in roots:
        require(not path.is_relative_to(absolute(root)), 'output must be outside every scanned root')
    data = encode(value)
    require(len(data) <= MAX_BYTES, 'record exceeds output byte limit')
    parent = directory(path.parent)
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    finally:
        os.close(parent)

def exact(value, keys, name):
    require(type(value) is dict and set(value) == set(keys), f'{name}: missing or unknown fields')

def integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, f'{name}: integer required')

def valid_meta(value):
    exact(value, META, 'metadata')
    for key in META:
        if key in ('mtime_ns', 'ctime_ns'):
            require(type(value[key]) is int, f'{key}: integer required')
        else:
            integer(value[key], key)

def header(value, kind, status):
    require(type(value) is dict, 'record must be an object')
    require(type(value.get('schema_version')) is int and value['schema_version'] == VERSION, 'unsupported schema_version')
    require(value.get('kind') == kind and value.get('status') == status, 'unsupported kind/status')

def validate_snapshot(value):
    header(value, 'resource_snapshot', 'complete')
    exact(value, ('schema_version','kind','status','root','root_before','root_after','observed_at_ns','duration_ns','atomic','historical_peak','exclusions','limits','entries','totals'), 'snapshot')
    require(type(value['root']) is str and str(absolute(value['root'])) == value['root'], 'invalid root')
    for key in ('root_before', 'root_after'):
        valid_meta(value[key])
    require(value['root_before'] == value['root_after'], 'root changed during observation')
    require(value['atomic'] is False and value['historical_peak'] == 'UNKNOWN' and value['exclusions'] == [], 'unsupported observation claims')
    integer(value['observed_at_ns'], 'observed_at_ns', 1)
    integer(value['duration_ns'], 'duration_ns')
    exact(value['limits'], ('entries','depth','bytes','seconds'), 'limits')
    for key, maximum in [('entries',50000),('depth',32),('bytes',MAX_BYTES),('seconds',30)]:
        integer(value['limits'][key], key, 1)
        require(value['limits'][key] <= maximum, 'limit exceeds supported bound')
    require(value['duration_ns'] <= value['limits']['seconds'] * 1_000_000_000, 'observation exceeded deadline')
    require(type(value['entries']) is list and len(value['entries']) <= value['limits']['entries'], 'invalid entry count')
    seen = set()
    for entry in value['entries']:
        require(type(entry) is dict, 'invalid entry')
        kind = entry.get('type')
        require(kind in ('file','directory','symlink','other'), 'invalid entry type')
        exact(entry, ('path','type',*META, *(('target',) if kind == 'symlink' else ())), 'entry')
        valid_meta({key: entry[key] for key in META})
        path = entry['path']
        require(type(path) is str and path and not Path(path).is_absolute() and '..' not in Path(path).parts and path not in seen, 'invalid or duplicate relative path')
        require(str(Path(path)) == path and len(Path(path).parts) <= value['limits']['depth'], 'noncanonical or too-deep entry')
        seen.add(path)
        mode = entry['mode']
        expected = 'file' if stat.S_ISREG(mode) else 'directory' if stat.S_ISDIR(mode) else 'symlink' if stat.S_ISLNK(mode) else 'other'
        require(expected == kind, 'mode/type mismatch')
        if kind == 'symlink':
            require(type(entry['target']) is str, 'link target must be text')
    root_is_file = stat.S_ISREG(value['root_before']['mode'])
    require(root_is_file or stat.S_ISDIR(value['root_before']['mode']), 'unsupported root mode')
    if root_is_file:
        require(len(value['entries']) == 1 and value['entries'][0]['path'] == '.' and value['entries'][0]['type'] == 'file', 'file root must include its complete file')
        require(all(value['entries'][0][key] == value['root_before'][key] for key in META), 'root/file metadata differs')
    else:
        require('.' not in seen, 'directory root cannot contain dot entry')
        directories = {e['path'] for e in value['entries'] if e['type'] == 'directory'}
        require(all(all(str(parent) in directories for parent in Path(e['path']).parents if str(parent) != '.') for e in value['entries']), 'missing parent directory')
    valid_totals(value['totals'], value['entries'])
    require(len(encode(value)) <= value['limits']['bytes'], 'snapshot exceeds encoded bound')
    return value

def valid_totals(value, entries):
    expected = totals(entries)
    exact(value, expected.keys(), 'totals')
    for key, count in value.items():
        integer(count, key)
    require(value == expected, 'contradictory totals')

def validate_owner(value):
    header(value, 'resource_owner', 'observed')
    exact(value, ('schema_version','kind','status','owner','declared_roots','components','totals','historical_peak','scope','attribution','deletion_authorized'), 'owner')
    require(type(value['owner']) is str and 1 <= len(value['owner']) <= 128 and all(c.isascii() and (c.isalnum() or c in '._-') for c in value['owner']), 'invalid owner')
    require(value['historical_peak'] == 'UNKNOWN' and value['scope'] == 'declared_roots_only' and value['attribution'] == 'unattributed' and value['deletion_authorized'] is False, 'unsupported ownership/peak/authority claim')
    exact(value['declared_roots'], ('retained_package','consumer_tree'), 'declared_roots')
    for declared in value['declared_roots'].values():
        require(type(declared) is str and str(absolute(declared)) == declared, 'invalid declared root')
    components = value['components']
    require(type(components) is list and 2 <= len(components) <= 16, 'incomplete components')
    roles = []
    roots = []
    all_entries = []
    for component in components:
        exact(component, ('role','snapshot'), 'component')
        require(component['role'] in ('retained_package','consumer_tree','shared_cache','other'), 'unknown component')
        scan = validate_snapshot(component['snapshot'])
        root = absolute(scan['root'])
        require(not any(root.is_relative_to(old) or old.is_relative_to(root) for old in roots), 'overlapping component roots')
        roots.append(root)
        roles.append(component['role'])
        if component['role'] in value['declared_roots']:
            require(scan['root'] == value['declared_roots'][component['role']], 'component is not the complete declared root')
        all_entries.extend(scan['entries'])
    require(roles.count('retained_package') == 1 and roles.count('consumer_tree') == 1, 'required retained_package/consumer_tree missing or duplicated')
    consumer = next(c['snapshot'] for c in components if c['role'] == 'consumer_tree')
    require(stat.S_ISDIR(consumer['root_before']['mode']), 'consumer_tree must be a complete directory root')
    valid_totals(value['totals'], all_entries)
    return value

def read_record(path):
    path = absolute(path)
    parent = directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            require(stat.S_ISREG(info.st_mode), 'record must be a regular file')
            require(info.st_size <= MAX_BYTES, 'record byte limit exceeded before read')
            raw = source.read(MAX_BYTES + 1)
    finally:
        os.close(parent)
    require(len(raw) <= MAX_BYTES, 'record byte limit exceeded')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(RecordError('nonfinite JSON')))

def compare(before, after, allow_root_rename=False):
    validate_snapshot(before)
    validate_snapshot(after)
    require(type(allow_root_rename) is bool, 'rename flag must be boolean')
    left = before['root_before']
    right = after['root_before']
    require((left['dev'], left['ino']) == (right['dev'], right['ino']), 'baseline root identity differs')
    require(before['root'] == after['root'] or allow_root_rename, 'root rename requires explicit opt-in')
    old = {e['path']: e for e in before['entries']}
    new = {e['path']: e for e in after['entries']}
    changes = {key: [] for key in ('new','removed','replaced','same_inode_growth','metadata_changed')}
    for path in sorted(set(old) | set(new)):
        a, b = old.get(path), new.get(path)
        if a is None:
            kind = 'new'
        elif b is None:
            kind = 'removed'
        elif (a['dev'], a['ino']) != (b['dev'], b['ino']):
            kind = 'replaced'
        elif a['type'] == b['type'] == 'file' and b['size'] > a['size']:
            kind = 'same_inode_growth'
        elif a != b:
            kind = 'metadata_changed'
        else:
            continue
        changes[kind].append({'path': path, 'before': a, 'after': b, 'attribution': 'unattributed'})
    return {'schema_version': VERSION, 'kind': 'resource_diff', 'status': 'complete',
            'root_before': before['root'], 'root_after': after['root'],
            'root_renamed': before['root'] != after['root'], 'changes': changes,
            'attribution': 'unattributed', 'historical_peak': 'UNKNOWN',
            'deletion_authorized': False}

def account(owner, components, retained_package, consumer_root):
    require(type(components) is list and 2 <= len(components) <= 16, 'incomplete components')
    for component in components:
        exact(component, ('role','snapshot'), 'component')
        validate_snapshot(component['snapshot'])
    value = {'schema_version': VERSION, 'kind': 'resource_owner', 'status': 'observed',
             'owner': owner, 'declared_roots': {'retained_package': str(absolute(retained_package)), 'consumer_tree': str(absolute(consumer_root))}, 'components': components,
             'totals': totals([e for c in components for e in c['snapshot']['entries']]),
             'historical_peak': 'UNKNOWN', 'scope': 'declared_roots_only',
             'attribution': 'unattributed', 'deletion_authorized': False}
    return validate_owner(value)

def cli(argv):
    parser = argparse.ArgumentParser(prog='harness.py resources')
    commands = parser.add_subparsers(dest='action', required=True)
    scan = commands.add_parser('snapshot')
    scan.add_argument('--root', type=Path, required=True)
    scan.add_argument('--out', type=Path, required=True)
    scan.add_argument('--max-entries', type=int, default=50000)
    scan.add_argument('--max-depth', type=int, default=32)
    scan.add_argument('--max-bytes', type=int, default=MAX_BYTES)
    scan.add_argument('--timeout', type=int, default=30)
    valid = commands.add_parser('validate')
    valid.add_argument('--record', type=Path, required=True)
    diff = commands.add_parser('compare')
    diff.add_argument('--baseline', type=Path, required=True)
    diff.add_argument('--current', type=Path, required=True)
    diff.add_argument('--out', type=Path, required=True)
    diff.add_argument('--allow-root-rename', action='store_true')
    ledger = commands.add_parser('account')
    ledger.add_argument('--owner', required=True)
    ledger.add_argument('--retained-package', type=Path, required=True)
    ledger.add_argument('--consumer-root', type=Path, required=True)
    ledger.add_argument('--component', action='append', required=True, help='role=/absolute/snapshot.json')
    ledger.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'validate':
            result = validate_owner(read_record(args.record))
            print(encode(result).decode(), end='')
            return 0
        if args.action == 'compare':
            before, after = read_record(args.baseline), read_record(args.current)
            result = compare(before, after, args.allow_root_rename)
            write_new(args.out, result, [Path(before['root']), Path(after['root'])])
            print(encode(result).decode(), end='')
            return 0
        if args.action == 'account':
            components = []
            for item in args.component:
                role, separator, path = item.partition('=')
                require(bool(separator), 'component must be role=/absolute/snapshot.json')
                components.append({'role': role, 'snapshot': validate_snapshot(read_record(Path(path)))})
            result = account(args.owner, components, args.retained_package, args.consumer_root)
            write_new(args.out, result, [Path(c['snapshot']['root']) for c in components])
            print(json.dumps({'schema_version': 1, 'kind': 'resource_account_result', 'status': 'observed', 'out': str(args.out), 'totals': result['totals'], 'historical_peak': 'UNKNOWN', 'deletion_authorized': False}))
            return 0
        result = snapshot(args.root, args.max_entries, args.max_depth, args.max_bytes, args.timeout)
        validate_snapshot(result)
        write_new(args.out, result, [args.root])
        print(json.dumps({'schema_version': 1, 'kind': 'resource_snapshot_result', 'status': 'complete',
                          'out': str(args.out), 'totals': result['totals'], 'duration_ns': result['duration_ns'],
                          'historical_peak': 'UNKNOWN'}))
        return 0
    except (RecordError, OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        print(json.dumps({'schema_version': 1, 'kind': 'resource_error', 'status': 'rejected', 'error': str(error)}), file=sys.stderr)
        return 2
