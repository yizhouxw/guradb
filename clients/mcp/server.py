"""MCP 2025-03-26 stdio adapter over the public GuraDB HTTP client."""
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clients.common.http import Client

VERSION = '2025-03-26'
MAX_REQUEST = 65536
SUBMIT = ('scan', 'search', 'graph', 'export')
JOBS = ('status', 'results', 'cancel', 'release')


class ProtocolError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def need(condition, message='invalid params', code=-32602):
    if not condition:
        raise ProtocolError(code, message)


def parse(raw):
    def pairs(items):
        result = {}
        for name, value in items:
            need(name not in result, 'duplicate JSON field', -32700)
            result[name] = value
        return result
    def constant(_):
        raise ProtocolError(-32700, 'nonfinite number')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError):
        raise ProtocolError(-32700, 'invalid JSON') from None


def schema(name):
    if name in SUBMIT:
        return {'type': 'object', 'properties': {'dataset_id': {'type': 'string'},
                'query': {'type': 'object'}, 'read_view_id': {'type': 'string'}},
                'required': ['dataset_id', 'query'], 'additionalProperties': False}
    field = 'dataset_id' if name == 'describe' else 'query_id'
    return {'type': 'object', 'properties': {field: {'type': 'string'}},
            'required': [field], 'additionalProperties': False}


def tools():
    return [{'name': name, 'description': ('Submit bounded HTTP job; use status/results; no automatic retry.'
             if name in SUBMIT else 'Invoke public HTTP '+name+'; server authorization applies.'),
             'inputSchema': schema(name)} for name in (*SUBMIT, 'describe', *JOBS)]


def identity(value):
    need(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) is not None)
    return value


class Server:
    def __init__(self, client):
        self.client, self.state = client, 'new'

    def call(self, name, arguments):
        need(name in (*SUBMIT, 'describe', *JOBS), 'unknown tool')
        spec = schema(name)
        need(isinstance(arguments, dict) and set(spec['required']) <= set(arguments) <= set(spec['properties']))
        if name in SUBMIT:
            identity(arguments['dataset_id'])
            need(isinstance(arguments['query'], dict))
            if 'read_view_id' in arguments:
                identity(arguments['read_view_id'])
            return self.client.request('POST', '/v1/exports' if name == 'export' else '/v1/'+name, arguments)
        if name == 'describe':
            return self.client.request('GET', '/v1/datasets/'+identity(arguments['dataset_id']))
        path = '/v1/jobs/'+identity(arguments['query_id'])
        if name in ('results', 'release'):
            path += '/results' if name == 'results' else '/retention'
        return self.client.request('DELETE' if name in ('cancel', 'release') else 'GET', path)

    def dispatch(self, message):
        request_id = None
        notification = False
        try:
            need(isinstance(message, dict), 'batch/invalid message unsupported', -32600)
            request_id = message.get('id')
            need('id' not in message or type(request_id) is int and abs(request_id) <= 9007199254740991 or
                 isinstance(request_id, str) and 0 < len(request_id) <= 128, 'invalid id', -32600)
            notification = 'id' not in message
            need(set(message) <= {'jsonrpc', 'id', 'method', 'params'} and message.get('jsonrpc') == '2.0'
                 and isinstance(message.get('method'), str), 'invalid request', -32600)
            method, params = message['method'], message.get('params', {})
            need(isinstance(params, dict))
            if method == 'notifications/initialized':
                need(notification and self.state == 'negotiated' and not params)
                self.state = 'ready'
                return None
            need(not notification, 'unsupported notification', -32600)
            if method == 'initialize':
                need(self.state == 'new' and set(params) == {'protocolVersion', 'capabilities', 'clientInfo'})
                need(isinstance(params['protocolVersion'], str) and isinstance(params['capabilities'], dict))
                info = params['clientInfo']
                need(isinstance(info, dict) and set(info) == {'name', 'version'} and
                     all(isinstance(v, str) and 0 < len(v) <= 128 for v in info.values()))
                self.state = 'negotiated'
                result = {'protocolVersion': VERSION, 'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': 'guradb', 'version': '0.1.0'}}
            elif method == 'ping':
                need(not params)
                result = {}
            else:
                need(self.state == 'ready', 'initialization required', -32002)
                if method == 'tools/list':
                    need(not params)
                    result = {'tools': tools()}
                elif method == 'tools/call':
                    need(set(params) == {'name', 'arguments'} and isinstance(params['name'], str))
                    try:
                        value = self.call(params['name'], params['arguments'])
                        result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False,
                                   allow_nan=False)}], 'isError': False}
                    except (RuntimeError, OSError, ValueError) as error:
                        # Never echo exception text: network errors may contain configured URLs.
                        result = {'content': [{'type': 'text', 'text': json.dumps(
                                  {'error': {'code': 'http_error', 'message': 'HTTP operation failed; inspect server job/status'}})}],
                                  'isError': True}
                else:
                    raise ProtocolError(-32601, 'method not found')
            return {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        except ProtocolError as error:
            if notification:
                return None
            valid_id = type(request_id) is int and abs(request_id) <= 9007199254740991 or isinstance(request_id, str)
            return {'jsonrpc': '2.0', 'id': request_id if valid_id else None,
                    'error': {'code': error.code, 'message': error.message}}


def serve(client, source, sink):
    server = Server(client)
    while True:
        raw = source.readline(MAX_REQUEST+1)
        if not raw:
            return 0
        try:
            need(len(raw) <= MAX_REQUEST and raw.endswith(b'\n'), 'request byte budget exceeded', -32600)
            response = server.dispatch(parse(raw))
        except ProtocolError as error:
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': error.code, 'message': error.message}}
        if response is not None:
            sink.write((json.dumps(response, ensure_ascii=True, allow_nan=False)+'\n').encode())
            sink.flush()
        if len(raw) > MAX_REQUEST or not raw.endswith(b'\n'):
            return 1


def main():
    url, token = os.environ.get('GURADB_URL'), os.environ.get('GURADB_TOKEN')
    if not url or not token:
        print('GURADB_URL and GURADB_TOKEN are required', file=sys.stderr)
        return 2
    return serve(Client(url, token), sys.stdin.buffer, sys.stdout.buffer)


if __name__ == '__main__':
    raise SystemExit(main())
