"""Bounded M1 HTTP adapter: DB authorization and query lifecycle share one service."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import urlsplit
import uuid

from modules.common.contracts import Failure, decode_json, encoded, require


def handle(row):
    return {'query_id': str(row['id']), 'status': row['status'], 'result_kind': 'data',
            'kind': row['kind'], 'read_context': row['context'], 'error': Failure(row['error'],'query execution failed').envelope()['error'] if row['error'] else None}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service):
        self.service = service
        self.connections = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'GuraDB-M1'

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *_):
        pass  # Tokens, parameters and source paths never enter default request logs.

    def dispatch(self):
        service = self.server.service
        service.check_lease()
        path = urlsplit(self.path)
        require(not path.query and not path.fragment, 'invalid_request')
        if self.command == 'GET' and path.path == '/healthz':
            with service.control.transaction() as conn:
                conn.execute('SELECT 1')
            return 200, {'status': 'ok'}, False
        token = self.headers.get('Authorization', '')
        require(token.startswith('Bearer '), 'unauthorized')
        principal = service.control.principal(token[7:])
        if self.command == 'POST' and path.path in ('/v1/search','/v1/scan','/v1/exports'):
            require(not self.headers.get('Transfer-Encoding') and self.headers.get('Content-Type') == 'application/json', 'invalid_request')
            length = int(self.headers.get('Content-Length', '-1'))
            require(0 < length <= 65536, 'resource_limit')
            raw = self.rfile.read(length)
            require(len(raw) == length, 'invalid_request')
            body = decode_json(raw)
            require(isinstance(body,dict) and set(body) <= {'dataset_id','query','read_view_id'} and
                    'dataset_id' in body and 'query' in body and
                    ('read_view_id' not in body or isinstance(body['read_view_id'], str)), 'invalid_request')
            dataset = str(uuid.UUID(body['dataset_id']))
            kind = {'/v1/search':'search','/v1/scan':'scan','/v1/exports':'export'}[path.path]
            return 202, handle(service.submit(principal,dataset,kind,body['query'],body.get('read_view_id'))), False
        parts = path.path.strip('/').split('/')
        if self.command == 'GET' and len(parts) == 3 and parts[:2] == ['v1','datasets']:
            return 200, service.describe(principal,str(uuid.UUID(parts[2]))), False
        require(len(parts) in (3,4,5) and parts[:2] == ['v1','jobs'], 'not_found')
        job = str(uuid.UUID(parts[2]))
        if self.command == 'GET':
            if len(parts) == 5:
                require(parts[3] == 'objects' and len(parts[4]) == 64, 'not_found')
                return 200, service.media(job,principal,parts[4]), True
            if len(parts) == 3:
                return 200, handle(service.jobs.get(job,principal)), False
            require(parts[3] in ('results','parquet'), 'not_found')
            parquet = parts[3] == 'parquet'
            return 200, service.result(job,principal,parquet), parquet
        if self.command == 'DELETE':
            require(len(parts) <= 4, 'not_found')
            if len(parts) == 4:
                require(parts[3] == 'retention', 'not_found')
                service.release(job,principal)
                return 200, {'released': True}, False
            return 200, handle(service.jobs.cancel(job,principal)), False
        raise Failure('not_found', 'endpoint unavailable')

    def respond(self):
        try:
            status, value, binary = self.dispatch()
            raw = value if binary else encoded(value)
            require(len(raw) <= 32 << 20, 'resource_limit')
        except Failure as error:
            status = {'unauthorized':401,'not_found':404,'not_ready':409,'view_unavailable':409,'resource_limit':429,'service_unavailable':503}.get(error.code,400)
            raw, binary = encoded(error.envelope()), False
        except (ValueError, TypeError, KeyError):
            status, raw, binary = 400, encoded(Failure('invalid_request','invalid request').envelope()), False
        except Exception:
            status, raw, binary = 503, encoded(Failure('service_unavailable','service dependency unavailable').envelope()), False
        self.send_response(status)
        self.send_header('Content-Type', 'application/octet-stream' if binary else 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    do_GET = respond
    do_POST = respond
    do_DELETE = respond
