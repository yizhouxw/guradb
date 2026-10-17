"""Real stdio subprocess -> HTTP adapter integration, reusable by M2/M3 driver."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from clients.common.http import Client

ROOT = Path(__file__).resolve().parents[2]


def run(url, token, dataset, query=None):
    """Exercise MCP on a live HTTP service; return scanned job/results evidence."""
    messages = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
         'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'integration', 'version': '1'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
         'name': 'describe', 'arguments': {'dataset_id': dataset}}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {
         'name': 'scan', 'arguments': {'dataset_id': dataset, 'query': query or {}}}},
    ]
    def exchange(batch, credential=token):
        env = {**os.environ, 'GURADB_URL': url, 'GURADB_TOKEN': credential}
        child = subprocess.run([sys.executable, '-m', 'clients.mcp.server'], cwd=ROOT, env=env,
                               input=''.join(json.dumps(m)+'\n' for m in batch), text=True,
                               capture_output=True, timeout=25, check=True)
        assert not child.stderr, 'unexpected MCP stderr'
        replies = [json.loads(line) for line in child.stdout.splitlines()]
        assert [r['id'] for r in replies] == [m['id'] for m in batch if 'id' in m], replies
        return replies

    def invoke(name, arguments, credential=token, error=False):
        message = {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
                   'params': {'name': name, 'arguments': arguments}}
        response = exchange(messages[:2]+[message], credential)[-1]['result']
        assert response['isError'] is error, response
        if error:
            serialized = json.dumps(response)
            assert credential not in serialized and token not in serialized and url not in serialized
        return json.loads(response['content'][0]['text'])

    client = Client(url, token)
    def terminal(handle):
        deadline = time.monotonic()+12
        while handle['status'] in ('queued', 'running', 'cancel_requested'):
            assert time.monotonic() < deadline, 'MCP integration job deadline exceeded'
            time.sleep(.02)
            handle = client.request('GET', '/v1/jobs/'+handle['query_id'])
        assert handle['status'] in ('succeeded', 'cancelled', 'failed'), handle
        return handle

    replies = exchange(messages)
    assert replies[0]['result']['protocolVersion'] == '2025-03-26'
    assert len(replies[1]['result']['tools']) == 9
    assert all(not r['result']['isError'] for r in replies[2:]), replies
    description = json.loads(replies[2]['result']['content'][0]['text'])
    handle = json.loads(replies[3]['result']['content'][0]['text'])
    assert 'query_id' in handle and 'status' in handle, handle
    assert terminal(handle)['status'] == 'succeeded'
    job = {'query_id': handle['query_id']}
    status = invoke('status', job)
    assert status['status'] == 'succeeded'
    results = invoke('results', job)
    assert isinstance(results.get('rows'), list) and results.get('read_context'), results
    invalid = 'invalid-mcp-integration-token'
    for name, args in [('describe', {'dataset_id': dataset}), ('status', job), ('results', job),
                       ('cancel', job), ('release', job)]:
        assert 'error' in invoke(name, args, invalid, error=True)
    released = invoke('release', job)
    assert released == {'released': True}, released
    second = invoke('scan', {'dataset_id': dataset, 'query': query or {}})
    cancellation = invoke('cancel', {'query_id': second['query_id']})
    assert cancellation['status'] in ('queued', 'running', 'cancel_requested', 'succeeded', 'failed', 'cancelled')
    final = terminal(cancellation)
    observed = invoke('status', {'query_id': second['query_id']})
    assert observed['status'] == final['status']
    assert invoke('release', {'query_id': second['query_id']}) == {'released': True}
    return {'description': description, 'handle': handle, 'protocol': '2025-03-26',
            'status': status['status'], 'rows': len(results['rows']), 'released': True,
            'cancel_terminal': observed['status'], 'invalid_token_rejected': True}


if __name__ == '__main__':
    # Real sockets and stdio subprocess; the full driver supplies a database service.
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def respond(self, value, status=200):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())
        def authorized(self):
            calls.append((self.command, self.path))
            if self.headers['Authorization'] != 'Bearer local-test-token':
                self.respond({'error': {'code': 'unauthorized', 'message': 'denied'}}, 401)
                return False
            return True
        def do_GET(self):
            if not self.authorized():
                return
            if '/datasets/' in self.path:
                self.respond({'dataset_id': 'local-dataset', 'schema': []})
            elif self.path.endswith('/results'):
                self.respond({'rows': [], 'read_context': {'read_view_id': 'fixed'}})
            else:
                self.respond({'query_id': 'local-job', 'status': 'succeeded'})
        def do_POST(self):
            if not self.authorized():
                return
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body == {'dataset_id': 'local-dataset', 'query': {}}
            self.respond({'query_id': 'local-job', 'status': 'queued'}, 202)
        def do_DELETE(self):
            if not self.authorized():
                return
            self.respond({'released': True} if self.path.endswith('/retention') else
                         {'query_id': 'local-job', 'status': 'succeeded'})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        evidence = run('http://127.0.0.1:'+str(server.server_port), 'local-test-token', 'local-dataset')
        assert ('GET', '/v1/jobs/local-job/results') in calls
        assert ('DELETE', '/v1/jobs/local-job') in calls
        assert ('DELETE', '/v1/jobs/local-job/retention') in calls
        print(json.dumps({'status': 'passed', 'transport': 'real-http-stdio', 'evidence': evidence}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
