"""Temporary engineering-only loopback HTTP range fixture; not a DB service."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import signal
import stat


def valid_key(key):
    return (type(key) is str and 0 < len(key) <= 4096 and len(key.split('/')) <= 16
            and all(re.fullmatch(r'[A-Za-z0-9._-]{1,255}', p) and p not in {'.', '..'} for p in key.split('/')))


def valid_etag(etag):
    if type(etag) is not str or not etag.isascii():
        return False
    tag = etag.encode('ascii')
    return (3 <= len(tag) <= 128 and tag[0] == 34 and tag[-1] == 34
            and all(0x21 <= b <= 0x7e and b not in (34, 92) for b in tag[1:-1]))


def capture(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= 32 * 1024 * 1024:
            raise ValueError('fixture needs one bounded ordinary object')
        data = stream.read(32 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    if len(data) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
        raise ValueError('fixture source changed during capture')
    return data


def emit(value):
    print(json.dumps(value, separators=(',', ':')), flush=True)


def serve(path, key, etag, port):
    if not valid_key(key) or not valid_etag(etag) or not 1024 <= port <= 65535:
        raise ValueError('unsupported fixture key, strong opaque tag or port')
    data = capture(path)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_GET(self):
            record = {'event': 'request', 'method': self.command, 'path': self.path,
                      'range': self.headers.get_all('Range'), 'if_match': self.headers.get_all('If-Match'),
                      'etag': etag, 'object_bytes': len(data), 'payload_attempted': 0, 'write_return_bytes': 0}
            status, body, content_range = 400, b'', None
            if self.path != '/objects/'+key:
                status = 404
            elif self.headers.get_all('If-Match') != [etag]:
                status = 412
            elif self.request_version == 'HTTP/1.1' and self.headers.get_all('Accept-Encoding') == ['identity'] and self.headers.get_all('Connection') == ['close']:
                ranges = self.headers.get_all('Range') or []
                match = re.fullmatch(r'bytes=(0|[1-9][0-9]*)-(0|[1-9][0-9]*)', ranges[0]) if len(ranges) == 1 else None
                if match:
                    start, end = map(int, match.groups())
                    if 0 <= start <= end < len(data) and end-start+1 <= 512 * 1024:
                        status, body = 206, data[start:end+1]
                        content_range = f'bytes {start}-{end}/{len(data)}'
                        record.update(offset=start, length=len(body))
                    else:
                        status = 416
            record.update(status=status, payload_attempted=len(body))
            self.close_connection = True
            try:
                self.send_response(status)
                self.send_header('ETag', etag)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Connection', 'close')
                if content_range:
                    self.send_header('Content-Range', content_range)
                self.end_headers()
                if body:
                    record['write_return_bytes'] = self.wfile.write(body)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError) as error:
                record['write_error'] = type(error).__name__
            finally:
                emit(record)

    server = HTTPServer(('127.0.0.1', port), Handler)
    emit({'event': 'ready', 'bind': '127.0.0.1', 'port': port, 'key': key,
          'etag': etag, 'captured_object_bytes': len(data), 'fixture_object_sha256': hashlib.sha256(data).hexdigest(),
          'scope': 'engineering capture truth, not client full-object verification or physical network metrics'})
    try:
        server.serve_forever(poll_interval=.1)
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--object', type=Path, required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--etag', required=True)
    parser.add_argument('--port', type=int, default=38081)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_args: (_ for _ in ()).throw(SystemExit(143)))
    try:
        serve(args.object, args.key, args.etag, args.port)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        parser.exit(1, f'error: {type(error).__name__}\n')


if __name__ == '__main__':
    main()
