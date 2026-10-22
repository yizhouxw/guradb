"""Raw local fault injection; does not authenticate or impersonate a real S3 service."""
from dataclasses import dataclass
import select
import socket
import threading
import time


@dataclass(frozen=True)
class Response:
    body: bytes = b'0123456789abcdef'
    version: str = 'v1'
    status: int = 200
    extra_headers: tuple = ()
    declared_length: int | None = None
    raw_headers: bytes | None = None
    header_delay: float = 0
    header_chunk: int = 65536
    header_interval: float = 0
    body_delay: float = 0
    body_chunk: int = 65536
    body_interval: float = 0
    eof_delay: float = 0

    def header(self):
        if self.raw_headers is not None:
            return self.raw_headers
        length = len(self.body) if self.declared_length is None else self.declared_length
        pairs = [('Content-Length', str(length)), ('x-amz-version-id', self.version),
                 ('Connection', 'close'), *self.extra_headers]
        return (f'HTTP/1.1 {self.status} Test\r\n' + ''.join(
            name + ': ' + value + '\r\n' for name, value in pairs) + '\r\n').encode('ascii')


class FaultServer:
    def __init__(self, responses=None):
        self.responses = list(responses or [Response()])
        self.requests = self.active = self.sent_body = self.sent_header = 0
        self._targets = []
        self._clients = set()
        self._threads = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.errors = []

    def __enter__(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(8)
        self.listener.settimeout(.050)
        self.endpoint = f'http://127.0.0.1:{self.listener.getsockname()[1]}'
        self.acceptor = threading.Thread(target=self._accept, name='p03-fault-listener')
        self.acceptor.start()
        return self

    @property
    def received_targets(self):
        # Only for in-memory golden checks. snapshot never exports object paths.
        with self._lock:
            return tuple(self._targets)

    def _accept(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(.100)
            with self._lock:
                self._clients.add(conn)
                self.active += 1
            worker = threading.Thread(target=self._serve, args=(conn,), name='p03-fault-connection')
            self._threads.append(worker)
            worker.start()

    def _pause(self, seconds, conn):
        until = time.monotonic() + seconds
        while not self._stop.is_set() and time.monotonic() < until:
            try:
                ready, _, _ = select.select([conn], [], [], 0)
                if ready and not conn.recv(1, socket.MSG_PEEK):
                    return False
            except OSError:
                return False
            self._stop.wait(min(.005, max(0, until - time.monotonic())))
        return not self._stop.is_set()

    def _send(self, conn, data, width, interval, header):
        for start in range(0, len(data), width):
            if self._stop.is_set():
                return False
            part = memoryview(data)[start:start + width]
            while part:
                count = conn.send(part)
                with self._lock:
                    if header:
                        self.sent_header += count
                    else:
                        self.sent_body += count
                part = part[count:]
            if not self._pause(interval, conn):
                return False
        return True

    def _serve(self, conn):
        try:
            request = bytearray()
            while not request.endswith(b'\r\n\r\n') and len(request) <= 16384:
                part = conn.recv(1)
                if not part:
                    return
                request.extend(part)
            first = request.split(b'\r\n', 1)[0].split(b' ')
            with self._lock:
                self.requests += 1
                response = self.responses[min(self.requests - 1, len(self.responses) - 1)]
                self._targets.append(first[1].decode('ascii') if len(first) == 3 else '<invalid>')
            if not self._pause(response.header_delay, conn):
                return
            if not self._send(conn, response.header(), response.header_chunk, response.header_interval, True):
                return
            if not self._pause(response.body_delay, conn):
                return
            if not self._send(conn, response.body, response.body_chunk, response.body_interval, False):
                return
            self._pause(response.eof_delay, conn)
        except (OSError, ValueError):
            # Expected peer close/injected malformed response; never log request data.
            pass
        finally:
            conn.close()
            with self._lock:
                self.active -= 1
                self._clients.discard(conn)

    def wait_idle(self, seconds=1):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            with self._lock:
                if self.active == 0:
                    return True
            time.sleep(.002)
        return False

    def snapshot(self):
        with self._lock:
            return {'requests': self.requests, 'active_connections': self.active,
                    'sent_header_bytes': self.sent_header, 'sent_body_bytes': self.sent_body}

    def __exit__(self, kind, value, traceback):
        self._stop.set()
        self.listener.close()
        with self._lock:
            clients = list(self._clients)
        for conn in clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
        self.acceptor.join(1)
        for thread in self._threads:
            thread.join(1)
        if self.acceptor.is_alive() or any(thread.is_alive() for thread in self._threads):
            raise RuntimeError('fault server did not terminate owned threads')
