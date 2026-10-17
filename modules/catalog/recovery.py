"""Offline, bounded local recovery into an empty independent PostgreSQL database."""
from contextlib import ExitStack
import fcntl
import json
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from modules.catalog.recovery_sources import relocate, relocate_sqlite
from modules.common.contracts import digest, encoded, require
from modules.storage.objects import put

TABLES = ('version', 'datasets', 'runs', 'pins', 'principals', 'grants', 'jobs')
MAX_FILE = 64 << 20
MAX_TOTAL = 512 << 20


def _files(root):
    require(root.is_dir() and not root.is_symlink(), 'unsafe_path')
    paths = sorted(root.rglob('*'))
    require(len(paths) <= 4096, 'resource_limit')
    require(all(not p.is_symlink() and (p.is_file() or p.is_dir()) for p in paths), 'unsafe_path')
    return [p for p in paths if p.is_file()]


def _read(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_FILE + 1)
    require(len(raw) <= MAX_FILE, 'resource_limit')
    return raw


def _closure(value, source, physical, files):
    """Validate artifact references against the explicit copied dependency set."""
    def reference(path, expected):
        path = Path(path)
        require(path.is_absolute() and path.is_relative_to(source) and '..' not in path.parts, 'unsafe_path')
        relative = path.relative_to(source).as_posix()
        require(relative in files, 'backup_incomplete', 'artifact outside copied dependency closure')
        require(digest(_read(physical/relative)) == expected, 'backup_corrupt')

    if isinstance(value, list):
        for item in value:
            _closure(item, source, physical, files)
    elif isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            reference(value['path'], value['sha256'])
        if isinstance(value.get('backend'), dict) and value['backend'].get('kind') == 'local':
            for fragment in value.get('files', []):
                key = Path(fragment['key'])
                require(not key.is_absolute() and '..' not in key.parts, 'unsafe_path')
                reference(Path(value['backend']['root'])/key, fragment['sha256'])
        for key, item in value.items():
            if key != 'values':
                _closure(item, source, physical, files)


def _validate_closure(catalog, source, physical, entries):
    files = {entry['path'] for entry in entries}
    _closure(catalog, source, physical, files)
    for relative in files:
        if relative.endswith('.json'):
            _closure(json.loads(_read(physical/relative)), source, physical, files)


def backup(dsn, root, destination, frozen=False):
    require(frozen, 'writes_not_frozen', 'stop services and external writers before backup')
    root = Path(root).absolute()
    require(root.resolve(strict=True) == root, 'unsafe_path')
    destination = Path(destination).absolute()
    require(not destination.exists() and not destination.is_relative_to(root) and destination.parent.resolve(strict=True) == destination.parent, 'unsafe_path')
    destination.mkdir(parents=True)
    with ExitStack() as stack, psycopg.connect(dsn, connect_timeout=3) as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        require(conn.execute('SELECT pg_try_advisory_xact_lock(7101702)').fetchone()[0], 'recovery_busy', 'stop serving before backup')
        managed = conn.execute("SELECT to_regclass('gura_managed.tables')").fetchone()[0]
        managed_roots = []
        if managed:
            managed_roots = [r[0] for r in conn.execute('SELECT root FROM gura_managed.tables ORDER BY root')]
            for value in managed_roots:
                path = Path(value)
                require(path != root and path.is_relative_to(root) and path.resolve(strict=True) == path, 'unsafe_path', 'managed source must be a strict child directory of backup root')
                lock = stack.enter_context((path/'.committer.lock').open('a+b'))
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    require(False, 'recovery_busy')
        conn.execute(sql.SQL('LOCK TABLE {} IN SHARE MODE').format(sql.SQL(',').join(
            sql.Identifier('gura_m1', t) for t in TABLES)))
        managed = conn.execute("SELECT to_regclass('gura_managed.tables')").fetchone()[0]
        require(all(not Path(a).is_relative_to(Path(b)) for a in managed_roots for b in managed_roots if a != b), 'unsafe_path', 'managed source roots must not nest')
        if managed:
            conn.execute('LOCK TABLE gura_managed.tables,gura_managed.intents IN SHARE MODE')
            require([r[0] for r in conn.execute('SELECT root FROM gura_managed.tables ORDER BY root')] == managed_roots, 'backup_changed')
            require(conn.execute("SELECT 1 FROM gura_managed.intents WHERE status IN ('prepared','committing') LIMIT 1").fetchone() is None, 'recovery_busy')
        actual_tables = {row[0] for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='gura_m1'")}
        require(actual_tables == set(TABLES), 'incompatible_catalog')
        require(conn.execute('SELECT version FROM gura_m1.version').fetchall() == [(1,)], 'incompatible_catalog')
        require(conn.execute("SELECT 1 FROM gura_m1.runs WHERE status IN ('building','retiring') LIMIT 1").fetchone() is None,
                'recovery_busy')
        require(conn.execute("SELECT 1 FROM gura_m1.jobs WHERE status IN ('queued','running') LIMIT 1").fetchone() is None,
                'recovery_busy')
        catalog = {t: [row[0] for row in conn.execute(sql.SQL('SELECT to_jsonb(t) FROM {} t').format(
            sql.Identifier('gura_m1', t))).fetchall()] for t in TABLES}
        for table, column in (('runs', 'artifact'), ('jobs', 'result')):
            for row in catalog[table]:
                reference = row[column]
                if reference is not None:
                    require(not any(Path(reference['path']).is_relative_to(Path(r)) for r in managed_roots),
                            'unsafe_path', 'serving artifacts must be outside managed source directories')
        managed_catalog = {}
        if managed:
            for t in ('tables', 'intents'):
                managed_catalog[t] = [r[0] for r in conn.execute(sql.SQL('SELECT to_jsonb(t) FROM {} t').format(sql.Identifier('gura_managed', t)))]
        entries, total = [], 0
        paths = _files(root)
        for path in paths:
            raw = _read(path)
            total += len(raw)
            require(total <= MAX_TOTAL, 'resource_limit')
            relative = path.relative_to(root).as_posix()
            put(destination/'objects'/relative, raw)
            entries.append({'path': relative, 'sha256': digest(raw), 'size': len(raw)})
        # Catch accidental writers as well as missing/deleted files; operators must
        # still keep the service stopped for the complete backup operation.
        require(paths == _files(root) and all(digest(_read(root/e['path'])) == e['sha256'] for e in entries),
                'backup_changed')
        _validate_closure(catalog, root, destination/'objects', entries)
        raw = encoded({'version': 1, 'root': str(root), 'pg_major': conn.info.server_version // 10000, 'catalog': catalog, 'managed': managed_catalog, 'files': entries})
        put(destination/'manifest.json', raw)
        put(destination/'COMPLETE.json', encoded({'version': 1, 'manifest_sha256': digest(raw)}))
    return {'files': len(entries), 'bytes': total, 'manifest_sha256': digest(raw)}


def verify(directory):
    directory = Path(directory).absolute()
    require(directory.resolve(strict=True) == directory, 'unsafe_path')
    _files(directory)
    complete = json.loads(_read(directory/'COMPLETE.json'))
    raw = _read(directory/'manifest.json')
    require(complete == {'version': 1, 'manifest_sha256': digest(raw)}, 'backup_corrupt')
    manifest = json.loads(raw)
    require(manifest['version'] == 1 and set(manifest['catalog']) == set(TABLES), 'incompatible_backup')
    require(manifest['catalog']['version'] == [{'id': True, 'version': 1}], 'incompatible_catalog')
    require(len(manifest['files']) <= 4096, 'resource_limit')
    seen, total = set(), 0
    for entry in manifest['files']:
        relative = Path(entry['path'])
        require(not relative.is_absolute() and all(p not in ('', '.', '..') for p in entry['path'].split('/')),
                'unsafe_path')
        require(entry['path'] not in seen, 'backup_corrupt')
        seen.add(entry['path'])
        payload = _read(directory/'objects'/relative)
        require(len(payload) == entry['size'] and digest(payload) == entry['sha256'], 'backup_corrupt')
        total += len(payload)
        require(total <= MAX_TOTAL, 'resource_limit')
    _validate_closure(manifest['catalog'], Path(manifest['root']), directory/'objects', manifest['files'])
    return manifest


def restore(dsn, directory, destination):
    manifest = verify(directory)
    source = Path(manifest['root'])
    require(source.is_absolute(), 'unsafe_path')
    destination = Path(destination).absolute()
    require(not destination.exists() and destination != source and not destination.is_relative_to(source), 'unsafe_path')
    require(destination.parent.resolve(strict=True) == destination.parent, 'unsafe_path')
    originals = {entry['path']: _read(Path(directory)/'objects'/entry['path']) for entry in manifest['files']}
    source_roots = [row['root'] for row in manifest.get('managed', {}).get('tables', [])]
    rewritten = relocate(originals, source, destination, source_roots)
    visiting = set()

    def rewrite(value, field=None):
        if field == 'values':
            return value  # Business payload is never a relocation instruction.
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            result = {k: rewrite(v, k) for k, v in value.items()}
            if 'path' in value and 'sha256' in value:
                relative = local(value['path'])
                require(relative in originals and digest(originals[relative]) == value['sha256'], 'backup_corrupt')
                result['sha256'] = digest(materialize(relative))
            return result
        if field in ('root', 'metadata') and isinstance(value, str) and any(value == Path(r).as_uri() or value.startswith(Path(r).as_uri() + '/') for r in source_roots):
            return destination.as_uri() + value[len(source.as_uri()):]
        if field == 'root' and value == str(source):
            return str(destination)
        if field in ('path', 'index_path', 'root') and isinstance(value, str) and value.startswith(str(source) + '/'):
            relative = local(value)
            # Local absolute paths include index directories as well as files.
            require(relative in originals or any(p.startswith(relative + '/') for p in originals), 'unsafe_path')
            return str(destination/relative)
        return value

    def local(path):
        require(isinstance(path, str), 'unsafe_path')
        parsed = Path(path)
        require(parsed.is_absolute() and parsed.is_relative_to(source) and '..' not in parsed.parts, 'unsafe_path')
        return parsed.relative_to(source).as_posix()

    def materialize(relative):
        if relative in rewritten:
            return rewritten[relative]
        require(relative not in visiting, 'backup_corrupt', 'cyclic artifact references')
        visiting.add(relative)
        raw = originals[relative]
        if relative.endswith('.json'):
            raw = encoded(rewrite(json.loads(raw)))
        rewritten[relative] = raw
        visiting.remove(relative)
        return raw

    catalog = rewrite(manifest['catalog'])
    managed_catalog = rewrite(manifest.get('managed', {}))
    for intent in managed_catalog.get('intents', []):
        if intent['metadata']:
            relative = Path(intent['metadata'].removeprefix('file://')).relative_to(destination).as_posix()
            intent['metadata_sha256'] = digest(materialize(relative))
    for relative in originals:
        materialize(relative)
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        require(conn.info.server_version // 10000 == manifest.get('pg_major'), 'incompatible_catalog', 'PostgreSQL major-version migration is not supported')
        conn.execute('SELECT pg_advisory_xact_lock(7101714)')
        require(conn.execute("SELECT 1 FROM pg_namespace WHERE nspname IN ('gura_m1','gura_managed') LIMIT 1").fetchone() is None,
                'restore_not_empty')
        destination.mkdir()
        for relative, raw in rewritten.items():
            put(destination/relative, raw)
        for value in source_roots:
            sqlite_path = destination/Path(value).relative_to(source)/'catalog.db'
            require(sqlite_path.is_file(), 'backup_corrupt')
            relocate_sqlite(sqlite_path, source, destination)
        conn.execute(Path(__file__).with_name('schema.sql').read_text())
        conn.execute('DELETE FROM gura_m1.version')
        for table in TABLES:
            for row in catalog[table]:
                conn.execute(sql.SQL('INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{}, %s)').format(
                    sql.Identifier('gura_m1', table), sql.Identifier('gura_m1', table)), (Jsonb(row),))
        if managed_catalog:
            conn.execute(Path(__file__).with_name('managed.sql').read_text())
            for table in ('tables', 'intents'):
                for row in managed_catalog[table]:
                    conn.execute(sql.SQL('INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{}, %s)').format(
                        sql.Identifier('gura_managed', table), sql.Identifier('gura_managed', table)), (Jsonb(row),))
    return {'restored': True, 'files': len(rewritten), 'root': str(destination)}
