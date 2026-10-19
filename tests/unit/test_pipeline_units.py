"""Snapshot, incremental and rebuild units against independent Iceberg fact files."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from modules.common.contracts import Budget, Failure, digest, encoded, key
from modules.connectors.writer import Writer
from modules.index.retrieval import load_bundle
from modules.query import snapshot, incremental, rebuild
from modules.storage.objects import get
from support import Connection, transaction
from test_writer_units import IntentStore

DATASET = '11111111-1111-1111-1111-111111111111'


class PipelineControl:
    def __init__(self, root):
        self.ds = {'id': DATASET, 'name': 'documents', 'published': None,
                   'definition': {'root': root.as_uri(), 'key_field': 'id', 'text_field': 'title'}}
        self.runs = {}
        self.connection = None
        self.pins = set()

    def dataset(self, _):
        return self.ds

    def begin(self, dataset, operation, target):
        if operation not in self.runs:
            self.runs[operation] = {'id': operation, 'status': 'building', 'target': target,
                                   'published_epoch': None, 'artifact': None, 'error': None}
        return self.runs[operation]

    def run(self, name):
        return self.runs[name]

    def ready(self, name, artifact):
        self.runs[name].update(status='ready', artifact=artifact)

    def fail(self, name, code):
        self.runs[name].update(status='failed', error=code)

    def publish(self, name, epoch):
        self.runs[name].update(status='published', published_epoch=epoch+1)
        self.ds['published'] = name
        return epoch+1

    def pin(self, name, owner):
        self.pins.add((name, owner))

    def unpin(self, name, owner):
        self.pins.remove((name, owner))

    def retire(self, name):
        return self.runs[name]

    def transaction(self):
        return transaction(self.connection)


class PipelineTest(unittest.TestCase):
    def test_real_snapshot_refresh_rebuild_media_and_idempotency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            writer = Writer(root/'source', 'documents')
            managed = IntentStore()
            writer.initialize(managed)
            rows = [{'id': i, 'title': 'alpha', 'active': True} for i in range(32)]
            first = writer.append(managed, 'first', rows)
            media = writer.root/'media.bin'
            media.write_bytes(b'pixels')
            def target(source, count):
                features = {'model': 'space', 'dimension': 2, 'metric': 'squared_l2', 'preprocessing': 'identity-v1',
                            'records': [{'logical_key': key(i, 'long'), 'vector': [float(i), 0.], 'media': [
                                {'uri': media.as_uri(), 'sha256': digest(b'pixels'), 'size_bytes': 6}]} for i in range(count)]}
                path = writer.root/f'features-{count}.json'
                path.write_bytes(encoded(features))
                return dict(source, features_uri=path.as_uri(), features_sha256=digest(path.read_bytes()), ann={'partitions': 1})
            control = PipelineControl(writer.root)
            first_target = target(first, 32)
            initial = snapshot.construct(control, DATASET, 'initial', first_target, root/'builds')
            self.assertEqual(snapshot.construct(control, DATASET, 'initial', first_target, root/'builds'), initial)
            self.assertEqual(snapshot.publish(control, 'initial', 0), 1)
            self.assertEqual(snapshot.publish(control, 'initial', 0), 1)
            second = writer.append(managed, 'second', [{'id': i, 'title': 'beta', 'active': False} for i in range(32, 48)])
            second_target = target(second, 48)
            control.connection = Connection([('advisory', {'locked': True}), ('runs', None)])
            delta = incremental.refresh(control, DATASET, 'delta', second_target, root/'builds')
            control.connection.complete()
            self.assertFalse(control.pins)
            self.assertEqual(incremental.progress(control, 'delta')['applied'], str(second['snapshot_id']))
            fixed = load_bundle(delta['artifact'], Budget())
            self.assertEqual([r['values'] for r in fixed['rows']], sorted(writer.table().scan().to_arrow().to_pylist(), key=lambda r: r['id']))
            old = load_bundle(initial['artifact'], Budget())
            self.assertEqual(fixed['rows'][0]['record_version'], old['rows'][0]['record_version'])
            control.connection = Connection([('advisory', {'locked': True}), ('runs', delta)])
            self.assertEqual(incremental.refresh(control, DATASET, 'delta', second_target, root/'builds'), delta)
            self.assertFalse(control.pins)
            snapshot.publish(control, 'delta', 1)
            control.connection = Connection([('advisory', {'locked': True}), ('runs', None)])
            recreated = rebuild.rebuild(control, DATASET, 'rebuilt', root/'builds')
            control.connection.complete()
            rebuilt = load_bundle(recreated['artifact'], Budget())
            self.assertEqual([r['values'] for r in rebuilt['rows']], [r['values'] for r in fixed['rows']])
            self.assertFalse(control.pins)
            control.connection = Connection([('advisory', {'locked': True}), ('runs', recreated)])
            self.assertEqual(rebuild.rebuild(control, DATASET, 'rebuilt', root/'builds'), recreated)
            control.connection.complete()
            control.connection = Connection([('UPDATE', None)])
            snapshot.collect(control, 'rebuilt', root/'builds')
            self.assertFalse((root/'builds'/'rebuilt').exists())
            control.connection.complete()

    def test_failure_unpins_and_preserves_failed_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            control = PipelineControl(root)
            control.ds['published'] = 'base'
            control.runs['base'] = {'id': 'base', 'artifact': {'sha256': 'a'*64}, 'status': 'published'}
            control.connection = Connection([('advisory', {'locked': True}), ('runs', None)])
            with patch.object(rebuild, '_facts', side_effect=Failure('source_invalid', 'corrupt')):
                with self.assertRaises(Failure):
                    rebuild.rebuild(control, DATASET, 'bad', root/'builds')
            self.assertFalse(control.pins)
            self.assertEqual(control.runs['bad']['error'], 'source_invalid')
            control.connection = Connection([('advisory', {'locked': True}), ('runs', None)])
            target = {name: 'a'*64 for name in ('metadata_uri','metadata_sha256','features_uri','features_sha256')}
            target['snapshot_id'] = 1
            with patch.object(incremental, 'load_bundle', side_effect=OSError('unavailable')):
                with self.assertRaises(OSError):
                    incremental.refresh(control, DATASET, 'failed', target, root/'builds')
            self.assertFalse(control.pins)
            self.assertEqual(control.runs['failed']['error'], 'build_failed')
            with self.assertRaises(Failure) as caught:
                rebuild._read({'path': str(root/'missing'), 'sha256': 'a'*64}, Budget())
            self.assertEqual(caught.exception.code, 'source_unavailable')
