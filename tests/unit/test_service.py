"""Fixed-view service orchestration, durable failure and retention boundaries."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

from modules.catalog.control import Control
from modules.common.contracts import Failure, encoded, digest
from modules.query.service import Service
from modules.storage.objects import get, put
from support import Connection, control_for


def bundle():
    return {'revision': 'rev', 'context': {'view': 'fixed'}, 'manifest': {'schema': [], 'dataset_id': 'd'},
            'model': {}, 'retention_mode': 'managed-copy', 'rows': [
                {'logical_key': '01', 'values': {'id': 2**63-1, 'active': True}, 'media': []}]}


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service.__new__(Service)
        self.service.root = Path(self.temp.name).resolve()
        self.service.control = Mock()
        self.service.jobs = Mock()
        self.service.jobs.cancelled.return_value = False
        self.service.control.run.return_value = {'artifact': {}}
        self.service.lease = Mock()
        self.service.failed = threading.Event()
        self.service.lease_lock = threading.Lock()
        self.service.capacity = threading.BoundedSemaphore(1)
        self.service.pool = Mock()
        self.service.workers = 0
        self.service.transport = None

    def test_constructor_lease_recovery_and_close(self):
        lease, jobs, pool = Mock(), Mock(), Mock()
        lease.execute.return_value.fetchone.return_value = (True,)
        with patch('modules.query.service.psycopg.connect', return_value=lease), patch('modules.query.service.Jobs', return_value=jobs), patch('modules.query.service.ThreadPoolExecutor', return_value=pool):
            service = Service(Mock(dsn='dsn'), self.temp.name, 3,
                              ['http://127.0.0.1:1', 'http://127.0.0.1:2', 'http://127.0.0.1:3'], 's'*32)
            jobs.recover.assert_called_once_with()
            service.check_lease()
            service.close()
            pool.shutdown.assert_called_once_with(wait=True, cancel_futures=False)
            lease.execute.return_value.fetchone.return_value = (False,)
            with self.assertRaises(Failure) as caught:
                Service(Mock(dsn='dsn'), self.temp.name)
            self.assertEqual(caught.exception.code, 'service_already_running')
        self.service.failed.set()
        with self.assertRaises(Failure):
            self.service.check_lease()

    def test_describe_pin_released_when_artifact_fails(self):
        ds = {'id': 'd', 'name': 'docs', 'published': 'r'}
        for error in (None, Failure('source_invalid', 'broken')):
            conn = Connection([('datasets', ds), ('runs', {'id': 'r', 'status': 'published', 'artifact': {}}), ('INSERT', None), ('DELETE', None)])
            self.service.control = control_for(conn)
            with patch.object(Control, 'authorize'), patch('modules.query.service.load_bundle', return_value=bundle(), side_effect=error):
                if error:
                    with self.assertRaises(Failure):
                        self.service.describe({}, 'd')
                else:
                    result = self.service.describe({}, 'd')
                    self.assertEqual(result['read_context'], {'view': 'fixed'})
            conn.complete()

    def test_submit_releases_capacity_on_failure_and_captures_deadline(self):
        self.service.jobs.submit.side_effect = Failure('not_ready', 'no view')
        with self.assertRaises(Failure):
            self.service.submit({}, 'd', 'scan', {})
        self.assertTrue(self.service.capacity.acquire(False))
        self.service.capacity.release()
        self.service.jobs.submit.side_effect = None
        self.service.jobs.submit.return_value = {'id': 'job'}
        row = self.service.submit({}, 'd', 'scan', {})
        self.assertGreater(row['deadline_at'], time.monotonic())
        self.assertEqual(self.service.pool.submit.call_args.args[1], row)
        with self.assertRaises(Failure):
            self.service.submit({}, 'd', 'scan', {})

    def execute(self, kind, request=None):
        row = {'id': str(uuid.uuid4()), 'run': 'r', 'kind': kind, 'request': request or {}, 'deadline_at': time.monotonic()+10}
        self.service.capacity.acquire()
        self.service.execute(row, {})
        self.assertTrue(self.service.capacity.acquire(False))
        self.service.capacity.release()
        return row

    def test_execute_all_routes_with_fixed_view(self):
        with patch('modules.query.service.load_bundle', return_value=bundle()), patch('modules.query.service.search', return_value={'hits': []}), patch('modules.query.service.expand', return_value={'paths': []}), patch('modules.query.service.export', return_value={'rows': 1}), patch('modules.query.service.distributed', return_value={'rows': []}):
            for kind in ('search', 'graph', 'scan', 'export'):
                self.service.jobs.cancelled.return_value = False
                self.execute(kind)
                kwargs = self.service.jobs.finish.call_args.kwargs
                result = json.loads(get(kwargs['result']))
                if kind == 'scan':
                    self.assertEqual(result['rows'][0]['values']['id'], str(2**63-1))
                    self.assertTrue(result['rows'][0]['values']['active'])
                else:
                    self.assertIn({'search': 'hits', 'graph': 'paths', 'export': 'rows'}[kind], result)
            self.service.workers = 3
            self.execute('scan')

    def test_execute_failure_and_persistence_outage(self):
        with patch('modules.query.service.load_bundle', return_value=bundle()):
            self.execute('scan', {'limit': 0})
            self.assertEqual(self.service.jobs.finish.call_args.kwargs['error'], 'resource_limit')
            self.service.jobs.finish.side_effect = RuntimeError('PG down')
            self.execute('scan', {'unexpected': 1})
            self.assertTrue(self.service.failed.is_set())
        self.service.failed.clear()
        self.service.jobs.finish.side_effect = None
        with patch('modules.query.service.load_bundle', side_effect=OSError('missing')):
            self.execute('scan')
        self.assertEqual(self.service.jobs.finish.call_args.kwargs['error'], 'execution_failed')

    def test_media_results_and_retention(self):
        media = put(self.service.root/'media', b'pixels')
        fixed = bundle()
        fixed['rows'][0]['media'] = [{'sha256': digest(b'pixels'), 'copy': media}]
        self.service.jobs.get.return_value = {'kind': 'export', 'status': 'succeeded', 'run': 'r'}
        with patch('modules.query.service.load_bundle', return_value=fixed):
            self.assertEqual(self.service.media('job', {}, media['sha256']), b'pixels')
            with self.assertRaises(Failure):
                self.service.media('job', {}, 'unknown')
        manifest = put(self.service.root/'manifest', encoded({'rows': 1}))
        parquet = put(self.service.root/'parquet', b'parquet')
        result = put(self.service.root/'result', encoded({'manifest': manifest, 'parquet': parquet, 'execution': {'workers': 3}}))
        self.service.jobs.get.return_value['result'] = result
        self.assertEqual(self.service.result('job', {}, True), b'parquet')
        exported = self.service.result('job', {})
        self.assertEqual(exported['query_id'], 'job')
        self.assertEqual(exported['execution'], {'workers': 3})
        self.service.jobs.get.return_value.update(kind='scan', result=put(self.service.root/'scan', b'{"rows":[]}'))
        self.assertEqual(self.service.result('job', {})['rows'], [])
        with self.assertRaises(Failure):
            self.service.result('job', {}, True)
        job = str(uuid.uuid4())
        directory = self.service.root/job
        directory.mkdir()
        (directory/'file').write_text('x')
        self.service.jobs.release.side_effect = lambda job, principal, cleanup: cleanup()
        self.service.release(job, {})
        self.assertFalse(directory.exists())
        self.service.release(job, {})
