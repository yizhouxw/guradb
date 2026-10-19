"""Offline backup/relocation units with real files and a scripted PG boundary."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import fastavro

from modules.catalog import recovery as r
from modules.catalog.recovery_sources import relocate, relocate_sqlite
from modules.common.contracts import Failure, digest, encoded
from modules.storage.objects import put
from support import Connection
from test_writer_units import IntentStore
from modules.connectors.writer import Writer


def context(conn):
    return Mock(__enter__=Mock(return_value=conn), __exit__=Mock(return_value=False))


class RecoveryTest(unittest.TestCase):
    def test_backup_verify_and_relocate_full_dependency_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root, backup, destination = base/'root', base/'backup', base/'restored'
            root.mkdir()
            writer, managed = Writer(root/'managed', 'docs'), IntentStore()
            writer.initialize(managed)
            source = writer.append(managed, 'append', [{'id': 1, 'title': 'alpha', 'active': None}])
            media = put(root/'media', b'media')
            artifact = put(root/'view.json', encoded({'root': str(root), 'index_path': str(root/'media'), 'references': [media],
                'values': {'path': '/business/path', 'sha256': 'opaque'}, 'metadata': source['metadata_uri']}))
            catalog = {t: [] for t in r.TABLES}
            catalog.update(version=[{'id': True, 'version': 1}], runs=[{'artifact': artifact}], jobs=[{'result': artifact}])
            managed_tables = [{'root': str(writer.root), 'name': 'docs'}]
            intent = deepcopy(managed.rows['append'])
            conn = Connection([('lock_timeout', None), ('advisory', (True,)), ('to_regclass', (True,)),
                ('ORDER BY root', [(str(writer.root),)]), ('LOCK TABLE', None), ('to_regclass', (True,)),
                ('LOCK TABLE', None), ('ORDER BY root', [(str(writer.root),)]), ('intents', None),
                ('pg_tables', [(t,) for t in r.TABLES]), ('SELECT version', [(1,)]), ('runs', None), ('jobs', None),
                *[(t, [(row,) for row in catalog[t]]) for t in r.TABLES],
                ('tables', [(managed_tables[0],)]), ('intents', [(intent,)])])
            conn.info = Mock(server_version=180000)
            with patch.object(r.psycopg, 'connect', return_value=context(conn)):
                result = r.backup('dsn', root, backup, frozen=True)
            conn.complete()
            self.assertGreater(result['files'], 5)
            self.assertEqual(r.verify(backup)['catalog'], catalog)
            # Restore performs one transaction; rows are observed independently after relocation.
            steps = [('advisory', None), ('pg_namespace', None), ('CREATE', None), ('DELETE', None),
                     *[('INSERT', None) for _ in range(sum(len(rows) for rows in catalog.values()))],
                     ('CREATE', None), ('INSERT', None), ('INSERT', None)]
            conn = Connection(steps)
            conn.info = Mock(server_version=180000)
            with patch.object(r.psycopg, 'connect', return_value=context(conn)):
                restored = r.restore('dsn', backup, destination)
            conn.complete()
            self.assertTrue(restored['restored'])
            view = json.loads((destination/'view.json').read_bytes())
            self.assertEqual(view['root'], str(destination))
            self.assertEqual(view['references'][0]['path'], str(destination/'media'))
            self.assertEqual(view['values'], {'path': '/business/path', 'sha256': 'opaque'})
            self.assertEqual(view['metadata'], source['metadata_uri'].replace(root.as_uri(), destination.as_uri()))
            self.assertEqual((destination/'media').read_bytes(), b'media')
            with sqlite3.connect(destination/'managed'/'catalog.db') as db:
                uri = db.execute('SELECT metadata_location FROM iceberg_tables').fetchone()[0]
                self.assertTrue(uri.startswith(destination.as_uri()))
            payload = backup/'objects'/'media'
            payload.write_bytes(b'corrupt')
            with self.assertRaises(Failure) as caught:
                r.verify(backup)
            self.assertEqual(caught.exception.code, 'backup_corrupt')

    def test_closure_manifest_file_paths_and_untrusted_business_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            data = put(root/'data.parquet', b'data')
            value = {'backend': {'kind': 'local', 'root': str(root)}, 'files': [
                {'key': 'data.parquet', 'sha256': data['sha256']}], 'values': {'path': '/outside', 'sha256': 'opaque'}}
            r._closure(value, root, root, {'data.parquet'})
            value['files'][0]['key'] = '../escape'
            with self.assertRaises(Failure):
                r._closure(value, root, root, {'data.parquet'})
            with self.assertRaises(Failure):
                r.backup('dsn', root, root/'backup', frozen=False)
            with self.assertRaises(Failure):
                r.backup('dsn', root, root/'backup', frozen=True)
            (root/'symlink').symlink_to(root/'data.parquet')
            with self.assertRaises(Failure):
                r._files(root)


class SourceRelocationTest(unittest.TestCase):
    def test_avro_manifest_lengths_paths_cache_and_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, destination = root/'source', root/'destination'
            schema = {'type': 'record', 'name': 'manifest', 'fields': [
                {'name': 'manifest_path', 'type': 'string'}, {'name': 'manifest_length', 'type': 'long'}]}
            nested = b'facts'
            sink = BytesIO()
            fastavro.writer(sink, schema, [{'manifest_path': (source/'managed'/'data').as_uri(), 'manifest_length': 0}], metadata={'custom': 'preserved'})
            originals = {'managed/data': nested, 'managed/list.avro': sink.getvalue(),
                         'managed/metadata.json': encoded({'list': [(source/'managed'/'list.avro').as_uri()], 'root': (source/'managed').as_uri()})}
            converted = relocate(originals, source, destination, [source/'managed'])
            reader = fastavro.reader(BytesIO(converted['managed/list.avro']))
            rows = list(reader)
            self.assertEqual(rows[0]['manifest_length'], len(nested))
            self.assertEqual(rows[0]['manifest_path'], (destination/'managed'/'data').as_uri())
            self.assertEqual(reader.metadata['custom'], 'preserved')
            cycle = {'managed/cycle.json': encoded({'manifest_path': (source/'managed'/'cycle.json').as_uri()})}
            with self.assertRaises(Failure):
                relocate(cycle, source, destination, [source/'managed'])
            outside = {'managed/bad.json': encoded({'manifest_path': 's3://outside/x'})}
            with self.assertRaises(Failure):
                relocate(outside, source, destination, [source/'managed'])

    def test_sqlite_unknown_tables_and_views_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'catalog.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE unknown (id INTEGER)')
            with self.assertRaises(Failure):
                relocate_sqlite(path, root, root/'new')
            with sqlite3.connect(path) as db:
                db.execute('CREATE VIEW leak AS SELECT * FROM unknown')
            with self.assertRaises(Failure):
                relocate_sqlite(path, root, root/'new')
