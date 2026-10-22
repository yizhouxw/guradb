"""Local pass-through counts actual backend GETs without storing signed headers."""
import socket
from urllib.parse import urlsplit

from tests.storage_support.fault_server import FaultServer


class RecordingProxy(FaultServer):
    def __init__(self, endpoint):
        super().__init__()
        parsed = urlsplit(endpoint)
        if parsed.hostname != '127.0.0.1' or not parsed.port:
            raise ValueError('proxy backend must be numeric loopback')
        self.upstream = ('127.0.0.1', parsed.port)

    def _serve(self, conn):
        remote = None
        try:
            request = bytearray()
            while not request.endswith(b'\r\n\r\n'):
                part = conn.recv(1)
                if not part or len(request) >= 16384:
                    return
                request.extend(part)
            with self._lock:
                self.requests += 1
            remote = socket.create_connection(self.upstream, timeout=.100)
            # Keep Host and signed target untouched; do not parse or log credentials.
            remote.sendall(request)
            pending = bytearray()
            headers_complete = False
            while not self._stop.is_set():
                try:
                    part = remote.recv(65536)
                except TimeoutError:
                    if not self._pause(.002, conn):
                        return
                    continue
                if not part:
                    return
                if not headers_complete:
                    pending.extend(part)
                    split = pending.find(b'\r\n\r\n')
                    if split < 0:
                        if len(pending) > 32768:
                            return
                        continue
                    header, body = pending[:split + 4], pending[split + 4:]
                    if not self._send(conn, header, 65536, 0, True):
                        return
                    if not self._send(conn, body, 65536, 0, False):
                        return
                    pending.clear()
                    headers_complete = True
                elif not self._send(conn, part, 65536, 0, False):
                    return
        except OSError:
            pass
        finally:
            if remote is not None:
                remote.close()
            conn.close()
            with self._lock:
                self.active -= 1
                self._clients.discard(conn)
