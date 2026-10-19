"""Negative boundary regressions and typed filtering omitted by happy-path scenarios."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from clients.mcp import server as mcp
from modules.catalog.control import Control
from modules.catalog.jobs import Jobs
from modules.catalog import recovery
from modules.catalog.recovery_sources import relocate
from modules.cluster import transport
from modules.common.contracts import Budget, Failure, decode_json, digest, encoded
from modules.common.process import run_process, stop_group
from modules.connectors import iceberg, incremental
from modules.connectors.writer import Writer
from modules.index.ann import candidates
from modules.index.graph import expand
from modules.index.retrieval import search
from modules.storage.objects import Objects
from support import Connection, control_for
from test_writer_units import IntentStore
from test_worker_units import fact_bundle


class BoundaryTest(unittest.TestCase):
    def test_json_parse_completion_and_ping(self):
        self.assertEqual(mcp.parse(b'{"x":1}'), {'x': 1})
        reply = mcp.Server(Mock()).dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})
        self.assertEqual(reply['result'], {})
        with self.assertRaises(Failure):
            decode_json('{"x":Infinity}')

    def test_explicit_view_jobs(self):
        view = '11111111-1111-1111-1111-111111111111'
        conn = Connection([('advisory', None), ('count', {'n': 0}), ('datasets', {'published': 'current'}),
            ('runs', {'id': view, 'status': 'published', 'artifact': {'context': {}}}), ('pins', None), ('jobs', {'id': 'j'})])
        with patch.object(Control, 'authorize', return_value={}):
            self.assertEqual(Jobs(control_for(conn), 'worker').submit({'tenant': 't', 'subject': 's', 'token_sha256': 'h'}, 'd', 'scan', {}, 'view_'+view), {'id': 'j'})
        conn.complete()

    def test_s3_reads_archives_and_sanitized_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            body = BytesIO(b'pixels')
            s3 = Mock()
            s3.get_object.return_value = {'Body': body, 'ContentLength': 6, 'ETag': 'etag', 'VersionId': 'v'}
            objects = Objects('s3://bucket/root', Budget(), s3, archive=root/'archive')
            self.assertEqual(objects.read('s3://bucket/root/data'), b'pixels')
            self.assertEqual(objects.dependencies[0]['identity']['version'], 'v')
            s3.get_object.side_effect = OSError('secret endpoint')
            with self.assertRaises(Failure) as caught:
                objects.read('s3://bucket/root/missing')
            self.assertNotIn('secret', str(caught.exception))
            with self.assertRaises(Failure) as caught:
                incremental.verify_identity(Objects(root.as_uri(), Budget()), {
                    'uri': (root/'missing').as_uri(), 'identity': {'kind': 'file-stat-v1'}})
            self.assertEqual(caught.exception.code, 'source_unavailable')

    def test_native_error_and_transient_group_permission(self):
        script = 'import pathlib,sys; pathlib.Path(sys.argv[-1]).write_text(\'{"error":"index_unavailable"}\')'
        with self.assertRaises(Failure) as caught:
            run_process([sys.executable, '-c', script], {}, Budget())
        self.assertEqual(caught.exception.code, 'index_unavailable')
        process = Mock(pid=123)
        with patch('modules.common.process.os.killpg', side_effect=[PermissionError(), None]):
            stop_group(process)
        self.assertEqual(process.wait.call_count, 2)

    def test_typed_int8_filters_empty_ann_and_nonmatching_edge_type(self):
        bundle = fact_bundle()
        for value, expected in [('1', 1), (2, 2)]:
            result = search(bundle, {'vector': [0., 0.], 'model': 'test', 'filter': {'field': 'id', 'equals': value}}, Budget())
            self.assertEqual(result['hits'][0]['values']['id'], str(expected))
        for value in ('01', '9223372036854775808', True):
            with self.assertRaises(Failure):
                search(bundle, {'vector': [0., 0.], 'model': 'test', 'filter': {'field': 'id', 'equals': value}}, Budget())
        bundle['ann'] = {'format': 'lance-ivf-flat-v1', 'revision': 'rev', 'model': bundle['model'], 'partitions': 1}
        self.assertEqual(candidates(bundle, [0., 0.], set(), 1, None, Budget())[0], [])
        bundle['manifest']['schema'] = [{'name': 'left', 'data_type': 'int8'}, {'name': 'right', 'data_type': 'int8'}, {'name': 'type', 'data_type': 'text'}]
        for row in bundle['rows']:
            row['values'].update(left=1, right=2, type='other')
        result = expand(bundle, {'source_field': 'left', 'target_field': 'right', 'type_field': 'type', 'seeds': ['1'], 'type': 'edge'}, Budget())
        self.assertEqual(result['paths'], [])

    def test_deleted_iceberg_entries_are_not_live_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = Writer(directory, 'documents')
            writer.initialize(IntentStore())
            source = writer.append(IntentStore(), 'append', [{'id': 1, 'title': 'a', 'active': True}])
            original = iceberg.avro
            def with_deleted(raw):
                header, rows = original(raw)
                if rows and 'data_file' in rows[0]:
                    rows = rows+[dict(deepcopy(rows[0]), status=2)]
                return header, rows
            with patch.object(iceberg, 'avro', side_effect=with_deleted):
                result = iceberg.snapshot(Objects(writer.root.as_uri(), Budget()), source['metadata_uri'], source['metadata_sha256'], source['snapshot_id'],
                    '11111111-1111-1111-1111-111111111111', 'documents', 'id', writer.root/'copy')
            self.assertEqual(len(result['rows']), 1)

    def test_recovery_source_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root/'source'
            originals = {'data.json': encoded({'uri': (root/'outside'/'file').as_uri()})}
            with self.assertRaises(Failure):
                relocate(originals, source, root/'dest', [root])
            managed = source/'managed'
            managed.mkdir(parents=True)
            conn = Connection([('lock_timeout', None), ('advisory', (True,)), ('to_regclass', (True,)), ('ORDER BY root', [(str(managed),)])])
            cm = Mock(__enter__=Mock(return_value=conn), __exit__=Mock(return_value=False))
            with patch.object(recovery.psycopg, 'connect', return_value=cm), patch.object(recovery.fcntl, 'flock', side_effect=BlockingIOError()):
                with self.assertRaises(Failure) as caught:
                    recovery.backup('dsn', source, root/'backup', frozen=True)
            self.assertEqual(caught.exception.code, 'recovery_busy')

    def test_transport_parser_watcher_and_failed_cancellation(self):
        with self.assertRaises(Failure):
            transport.endpoint('http://127.0.0.1:invalid')
        cancelled = threading.Event()
        connection = Mock()
        connection.sock.shutdown.side_effect = OSError('gone')
        def sent(*args):
            cancelled.set()
            time.sleep(.04)
        connection.request.side_effect = sent
        connection.getresponse.return_value.getheader.return_value = '1'
        with patch.object(transport.http.client, 'HTTPConnection', return_value=connection):
            with self.assertRaises(Failure) as caught:
                transport.request('http://127.0.0.1:1', '/v1/tasks', {}, 's'*32, 1, cancelled)
        self.assertEqual(caught.exception.code, 'cancelled')
        with tempfile.TemporaryDirectory() as directory, patch.object(transport, 'request', side_effect=Failure('worker_unavailable', 'offline')):
            with self.assertRaises(Failure):
                transport.fanout_remote([{'bundle': {'context': {}}}]*3, Budget(), directory,
                    ['http://127.0.0.1:1','http://127.0.0.1:2','http://127.0.0.1:3'], 's'*32)

    def test_incoming_edges_and_preserved_external_source_uri(self):
        bundle = fact_bundle()
        bundle['manifest']['schema'] = [{'name': 'left', 'data_type': 'int8'}, {'name': 'right', 'data_type': 'int8'}, {'name': 'type', 'data_type': 'text'}]
        for row in bundle['rows']:
            row['values'].update(left=1, right=2, type='edge')
        paths = expand(bundle, {'source_field': 'left', 'target_field': 'right', 'type_field': 'type', 'seeds': ['2'], 'type': 'edge', 'direction': 'in'}, Budget())['paths']
        self.assertEqual([p['neighbor'] for p in paths], ['1']*3)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve()
            raw = encoded({'uri': 'file:///external/opaque'})
            converted = relocate({'metadata.json': raw}, source, source/'destination', [source])
            self.assertEqual(json.loads(converted['metadata.json'])['uri'], 'file:///external/opaque')

    def test_concurrent_notification_ready_run_is_returned(self):
        from modules.query.incremental import _refresh
        conn = Connection([('runs', None)])
        control = control_for(conn)
        control.dataset.return_value = {'published': 'base', 'definition': {}}
        control.run.return_value = {'id': 'base'}
        control.begin.return_value = {'status': 'ready', 'id': 'existing'}
        target = {name: 'x' for name in ('metadata_uri','metadata_sha256','features_uri','features_sha256','snapshot_id')}
        self.assertEqual(_refresh(control, 'd', 'op', target, 'root', None, lambda: False)['id'], 'existing')
        conn.complete()

    def test_remote_fanout_observes_early_completed_future(self):
        with tempfile.TemporaryDirectory() as directory:
            payloads = [{'bundle': {'context': {'view': 'v'}}}]*3
            def remote(url, route, value, secret, *args):
                if route == '/v1/cancel':
                    return {}
                time.sleep(0.001 if value['shard'] == 0 else .08)
                return {**{n: value[n] for n in ('task_id', 'owner', 'shard', 'fingerprint')},
                        'pid': value['shard']+1, 'server_pid': value['shard']+4, 'read_context': {'view': 'v'},
                        'records': 1, 'rss_bytes': 1, 'output': {}, 'work': {'budget': Budget().counters()}}
            with patch.object(transport, 'request', side_effect=remote):
                results = transport.fanout_remote(payloads, Budget(), directory,
                    ['http://127.0.0.1:1','http://127.0.0.1:2','http://127.0.0.1:3'], 's'*32)
            self.assertEqual([r['shard'] for r in results], [0, 1, 2])
