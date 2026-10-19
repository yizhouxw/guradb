"""Thin client and HTTP adapter units with explicit transport/service boundaries."""
from contextlib import ExitStack
from io import BytesIO, StringIO
import json
import os
import runpy
import sys
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
import uuid

from clients.common.http import Client
from clients.cli import m1 as cli
from clients.mcp import server as mcp
from modules.common.contracts import Failure, encoded
from modules.gateway.m1 import Handler, Server, handle
from support import Connection, control_for


class ClientTest(unittest.TestCase):
    def test_http_json_binary_errors_and_bound(self):
        client = Client('http://localhost/', 'secret')
        response = Mock()
        response.headers = {'Content-Type': 'application/json'}
        response.read.return_value = b'{"ok":true}'
        cm = Mock(__enter__=Mock(return_value=response), __exit__=Mock(return_value=False))
        with patch('clients.common.http.urlopen', return_value=cm) as send:
            self.assertEqual(client.request('POST', '/v1/search', {}), {'ok': True})
            self.assertEqual(send.call_args.args[0].get_method(), 'POST')
            response.headers['Content-Type'] = 'application/octet-stream'
            self.assertEqual(client.request('GET', '/file'), b'{"ok":true}')
            response.read.return_value = b'x'*((32 << 20)+1)
            with self.assertRaisesRegex(RuntimeError, 'budget'):
                client.request('GET', '/large')
        with patch('clients.common.http.urlopen', side_effect=HTTPError('http://localhost', 400, 'bad', {}, BytesIO(b'bad request'))):
            with self.assertRaisesRegex(RuntimeError, 'bad request'):
                client.request('GET', '/bad')

    def test_wait_terminal_cancel_failure_and_interrupt(self):
        client = Client('http://localhost', 'secret')
        with patch.object(client, 'request', side_effect=[{'query_id': 'j', 'status': 'succeeded'}, {'rows': []}]), patch('clients.common.http.time.sleep'):
            self.assertEqual(client.wait({'query_id': 'j', 'status': 'queued'}), {'rows': []})
        with patch.object(client, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'deadline'):
                client.wait({'query_id': 'j', 'status': 'running'}, seconds=-1)
            request.assert_called_once_with('DELETE', '/v1/jobs/j')
        with patch.object(client, 'request') as request, patch('clients.common.http.time.sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                client.wait({'query_id': 'j', 'status': 'running'})
            request.assert_called_once_with('DELETE', '/v1/jobs/j')
        with self.assertRaises(RuntimeError):
            client.wait({'query_id': 'j', 'status': 'failed'})

    def test_cli_routes_and_entrypoint(self):
        for arguments, method, path in [(['describe', 'd'], 'GET', '/v1/datasets/d'),
                (['status', 'j'], 'GET', '/v1/jobs/j'), (['cancel', 'j'], 'DELETE', '/v1/jobs/j'),
                (['release', 'j'], 'DELETE', '/v1/jobs/j/retention'),
                (['export', '--dataset', 'd', '--view', 'v', '--no-wait'], 'POST', '/v1/exports'),
                (['scan', '--dataset', 'd'], 'POST', '/v1/scan')]:
            with patch.object(sys, 'argv', ['m1', *arguments]), patch.dict(os.environ, GURADB_TOKEN='secret'), patch.object(cli, 'Client') as cls, patch('sys.stdout', new_callable=StringIO):
                cls.return_value.request.return_value = {'query_id': 'j', 'status': 'queued'}
                cls.return_value.wait.return_value = {'rows': []}
                self.assertEqual(cli.main(), 0)
                self.assertEqual(cls.return_value.request.call_args.args[:2], (method, path))
        with patch.object(sys, 'argv', ['m1', 'scan', '--dataset', 'd']), patch.dict(os.environ, {}, clear=True), patch('sys.stderr', new_callable=StringIO):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(cli.__file__, run_name='__main__')
            self.assertEqual(caught.exception.code, 1)

    def test_mcp_error_paths_main_and_routes(self):
        with self.assertRaises(mcp.ProtocolError):
            mcp.parse(b'{"x":NaN}')
        client = Mock()
        server = mcp.Server(client)
        server.call('describe', {'dataset_id': 'd'})
        client.request.assert_called_with('GET', '/v1/datasets/d')
        server.call('results', {'query_id': 'j'})
        client.request.assert_called_with('GET', '/v1/jobs/j/results')
        server.call('release', {'query_id': 'j'})
        client.request.assert_called_with('DELETE', '/v1/jobs/j/retention')
        server.call('scan', {'dataset_id': 'd', 'query': {}, 'read_view_id': 'view_a'})
        server.state = 'ready'
        client.request.side_effect = RuntimeError('secret URL')
        reply = server.dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'scan', 'arguments': {'dataset_id': 'd', 'query': {}}}})
        self.assertTrue(reply['result']['isError'])
        self.assertNotIn('secret URL', json.dumps(reply))
        reply = server.dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'missing'})
        self.assertEqual(reply['error']['code'], -32601)
        self.assertIsNone(server.dispatch({'jsonrpc': '2.0', 'method': 'unsupported'}))
        sink = BytesIO()
        self.assertEqual(mcp.serve(client, BytesIO(b'{invalid}\n'), sink), 0)
        self.assertEqual(json.loads(sink.getvalue())['error']['code'], -32700)
        with patch.dict(os.environ, {}, clear=True), patch('sys.stderr', new_callable=StringIO):
            self.assertEqual(mcp.main(), 2)
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(mcp.__file__, run_name='__main__')
            self.assertEqual(caught.exception.code, 2)
        with patch.dict(os.environ, GURADB_URL='http://localhost', GURADB_TOKEN='secret'), patch.object(mcp, 'serve', return_value=0) as serve:
            self.assertEqual(mcp.main(), 0)
            serve.assert_called_once()


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.control.principal.return_value = {'subject': 'reader'}
        self.job = str(uuid.uuid4())
        self.dataset = str(uuid.uuid4())
        self.row = {'id': self.job, 'kind': 'scan', 'status': 'queued', 'context': {'view': 'v'}, 'error': None}
        self.service.submit.return_value = self.row
        self.service.jobs.get.return_value = self.row
        self.service.jobs.cancel.return_value = self.row
        self.handler = Handler.__new__(Handler)
        self.handler.server = Mock(service=self.service)
        self.handler.headers = {'Authorization': 'Bearer secret', 'Content-Type': 'application/json'}

    def dispatch(self, method, path, body=None):
        self.handler.command, self.handler.path = method, path
        raw = encoded(body) if body is not None else b''
        self.handler.rfile = BytesIO(raw)
        self.handler.headers['Content-Length'] = str(len(raw))
        return self.handler.dispatch()

    def test_routes_and_body_validation(self):
        conn = Connection([('SELECT 1', None)])
        self.service.control.transaction.side_effect = lambda: __import__('support').transaction(conn)
        self.assertEqual(self.dispatch('GET', '/healthz'), (200, {'status': 'ok'}, False))
        for route in ('search', 'scan', 'exports', 'graph'):
            status, result, binary = self.dispatch('POST', '/v1/'+route, {'dataset_id': self.dataset, 'query': {}, 'read_view_id': 'v'})
            self.assertEqual(status, 202)
            self.assertEqual(result['query_id'], self.job)
            self.assertFalse(binary)
        self.dispatch('GET', '/v1/datasets/'+self.dataset)
        self.service.describe.assert_called_once()
        self.assertEqual(self.dispatch('GET', '/v1/jobs/'+self.job)[1]['status'], 'queued')
        for route, binary in (('results', False), ('parquet', True)):
            self.assertEqual(self.dispatch('GET', '/v1/jobs/'+self.job+'/'+route)[2], binary)
        self.dispatch('GET', '/v1/jobs/'+self.job+'/objects/'+'a'*64)
        self.service.media.assert_called_once()
        self.assertEqual(self.dispatch('DELETE', '/v1/jobs/'+self.job+'/retention')[1], {'released': True})
        self.dispatch('DELETE', '/v1/jobs/'+self.job)
        for method, route in [('PUT', '/v1/jobs/'+self.job), ('GET', '/unknown'), ('GET', '/v1/jobs/'+self.job+'/no'), ('GET', '/healthz?query=x')]:
            with self.assertRaises(Failure):
                self.dispatch(method, route)
        failed = dict(self.row, error='cancelled')
        self.assertEqual(handle(failed)['error']['code'], 'cancelled')

    def test_respond_status_envelopes_binary_and_failures(self):
        for result, expected in [((200, {'ok': True}, False), 200), ((200, b'data', True), 200),
                (Failure('unauthorized', 'denied'), 401), (ValueError('invalid'), 400), (OSError('PG down'), 503)]:
            self.handler.wfile = BytesIO()
            for name in ('send_response', 'send_header', 'end_headers'):
                setattr(self.handler, name, Mock())
            with patch.object(self.handler, 'dispatch', side_effect=result if isinstance(result, Exception) else None, return_value=result):
                self.handler.respond()
            self.handler.send_response.assert_called_once_with(expected)
            self.assertTrue(self.handler.wfile.getvalue())

    def test_server_capacity_failure_cleanup_and_setup(self):
        with patch('modules.gateway.m1.ThreadingHTTPServer.__init__', return_value=None):
            server = Server(('127.0.0.1', 0), self.service)
        server.connections = threading.BoundedSemaphore(1)
        server.shutdown_request = Mock()
        server.connections.acquire()
        server.process_request('socket', 'address')
        server.shutdown_request.assert_called_once_with('socket')
        server.connections.release()
        with patch('modules.gateway.m1.ThreadingHTTPServer.process_request', side_effect=OSError('failed')):
            with self.assertRaises(OSError):
                server.process_request('socket', 'address')
        self.assertTrue(server.connections.acquire(False))
        with patch('modules.gateway.m1.ThreadingHTTPServer.process_request_thread'):
            server.process_request_thread('socket', 'address')
        self.assertTrue(server.connections.acquire(False))
        with patch('modules.gateway.m1.BaseHTTPRequestHandler.setup'):
            self.handler.connection = Mock()
            self.handler.setup()
            self.handler.connection.settimeout.assert_called_once_with(3)
        self.handler.log_message('ignored')
