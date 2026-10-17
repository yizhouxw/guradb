"""MCP lifecycle, framing and strict argument contracts."""
import io
import unittest

from clients.mcp.server import MAX_REQUEST, ProtocolError, Server, parse, serve

INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}}


class Transport:
    def __init__(self):
        self.calls = []
    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.endswith('/denied'):
            raise RuntimeError('secret-config-url')
        return {'status': 'queued', 'query_id': 'job'}


class MCPContract(unittest.TestCase):
    def ready(self):
        server = Server(Transport())
        self.assertIn('result', server.dispatch(INIT))
        self.assertIsNone(server.dispatch({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
        return server

    def test_lifecycle_and_tools(self):
        server = Server(Transport())
        self.assertIn('error', server.dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}))
        server = self.ready()
        result = server.dispatch({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        self.assertEqual({t['name'] for t in result['result']['tools']},
                         {'scan', 'search', 'graph', 'export', 'describe', 'status', 'results', 'cancel', 'release'})
        self.assertIn('error', server.dispatch(INIT))

    def test_invalid_envelopes_and_params(self):
        server = self.ready()
        for message in [[], {'id': True}, {'jsonrpc': '2.0', 'id': None, 'method': 'ping'},
                        {'jsonrpc': '2.0', 'id': 1.5, 'method': 'ping'},
                        {'jsonrpc': '2.0', 'id': 1, 'method': 'ping', 'unexpected': 1}]:
            self.assertIn('error', server.dispatch(message))
        for args in [{'dataset_id': 'x', 'query': {}, 'token': 'secret'},
                     {'dataset_id': '../secret', 'query': {}}, {'dataset_id': 'x', 'query': []}]:
            response = server.dispatch({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                       'params': {'name': 'scan', 'arguments': args}})
            self.assertIn('error', response)
        self.assertEqual(server.client.calls, [])

    def test_errors_and_no_wait(self):
        server = self.ready()
        response = server.dispatch({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                   'params': {'name': 'scan', 'arguments': {'dataset_id': 'x', 'query': {}}}})
        self.assertFalse(response['result']['isError'])
        self.assertEqual(len(server.client.calls), 1)
        response = server.dispatch({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                   'params': {'name': 'describe', 'arguments': {'dataset_id': 'denied'}}})
        self.assertTrue(response['result']['isError'])
        self.assertNotIn('secret-config', str(response))

    def test_duplicate_nonfinite_and_byte_limit(self):
        for raw in [b'{"id":1,"id":2}', b'{"x":NaN}', b'\xff']:
            with self.assertRaises(ProtocolError):
                parse(raw)
        sink = io.BytesIO()
        self.assertEqual(serve(Transport(), io.BytesIO(b'x' * (MAX_REQUEST+1)), sink), 1)
        self.assertEqual(len(sink.getvalue().splitlines()), 1)
