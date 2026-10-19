"""Writer sequencing and outcome reconciliation around an independent Iceberg source."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pyarrow as pa

from modules.common.contracts import Failure, digest
from modules.connectors.writer import ARROW, Writer, validate


class IntentStore:
    """Test boundary only; source truth is the real SQLite Iceberg catalog."""
    def __init__(self):
        self.rows = {}
        self.generation = 0
        self.root = None

    def register(self, name, root):
        self.root = root

    def prepare(self, name, operation, fingerprint):
        if operation not in self.rows:
            self.generation += 1
            self.rows[operation] = {'name': name, 'operation': operation, 'fingerprint': fingerprint,
                                    'generation': self.generation, 'status': 'prepared'}
        elif self.rows[operation]['fingerprint'] != fingerprint:
            raise Failure('operation_conflict', 'different input')
        return self.rows[operation]

    def pending(self, name):
        return [r for r in self.rows.values() if r['status'] == 'committing']

    @contextmanager
    def committing(self, name, operation, root):
        yield None, self.rows[operation], self.generation

    def parent(self, conn, row, parent):
        row.update(parent=parent, status='committing')

    def confirmed(self, conn, row, snapshot, metadata, metadata_sha256):
        row.update(status='committed', snapshot=snapshot, metadata=metadata, metadata_sha256=metadata_sha256)

    def abort(self, name, operation):
        self.rows[operation]['status'] = 'aborted'


class WriterTest(unittest.TestCase):
    def test_source_commit_retry_and_crash_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = Writer(directory, 'docs')
            store = IntentStore()
            writer.initialize(store)
            writer.initialize(store)
            rows = [{'id': 1, 'title': '数据库', 'active': None}]
            result = writer.append(store, 'one', rows)
            self.assertEqual(writer.append(store, 'one', rows), result)
            self.assertEqual(writer.table().scan().to_arrow().to_pylist(), rows)
            more = [{'id': 2, 'title': None, 'active': True}]
            def interrupted(stage):
                if stage == 'after_source':
                    raise OSError('lost response')
            with self.assertRaises(OSError):
                writer.append(store, 'two', more, interrupted)
            recovered = writer.append(store, 'two', more)
            self.assertNotEqual(result['snapshot_id'], recovered['snapshot_id'])
            self.assertEqual(len(writer.table().scan().to_arrow()), 2)
            def before_source(stage):
                if stage == 'before_source':
                    raise OSError('before commit')
            with self.assertRaises(OSError):
                writer.append(store, 'three', [{'id': 3, 'title': 'x', 'active': False}], before_source)
            writer.append(store, 'four', [{'id': 4, 'title': 'x', 'active': False}])
            self.assertEqual(store.rows['three']['status'], 'aborted')
            with self.assertRaises(Failure) as caught:
                writer.append(store, 'duplicate', rows)
            self.assertEqual(caught.exception.code, 'duplicate_key')

    def test_missing_confirmed_snapshot_and_changed_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            writer, store = Writer(directory, 'docs'), IntentStore()
            writer.initialize(store)
            row = store.prepare('docs', 'one', validate([{'id': 1, 'title': 'a', 'active': True}]))
            row.update(status='committed', snapshot=1)
            with writer.locked(), self.assertRaises(Failure):
                writer._reconcile_locked(store, 'one')
            row['status'] = 'prepared'
            result = writer.append(store, 'one', [{'id': 1, 'title': 'a', 'active': True}])
            path = Path(result['metadata_uri'].removeprefix('file://'))
            original = path.read_bytes()
            with patch.object(writer, 'table', return_value=writer.table()):
                path.write_bytes(original+b' ')
                with self.assertRaises(Failure) as caught:
                    writer._reconcile_locked(store, 'one')
                self.assertEqual(caught.exception.code, 'source_conflict')
                path.write_bytes(original)
