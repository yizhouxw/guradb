"""Real TCP PostgreSQL framing probes; used only by isolated acceptance clients."""
import socket
import struct
import select


def pack_int(value):
    return struct.pack('!i', value)


def frame(kind, payload=b''):
    return kind + pack_int(len(payload) + 4) + payload


class RawClient:
    def __init__(self, password, encoding='UTF8', user='reader', database='guradb', version=196608):
        self.password = password
        self.socket = socket.create_connection(('127.0.0.1', 5433), timeout=3)
        self.socket.settimeout(3)
        startup = pack_int(version) + b'user\x00' + user.encode() + b'\x00database\x00' + database.encode()
        startup += b'\x00client_encoding\x00' + encoding.encode() + b'\x00\x00'
        self.socket.sendall(pack_int(len(startup) + 4) + startup)
        self.backend = None
        self.ready = []
        while True:
            kind, data = self.read()
            self.ready.append(self.summary(kind, data))
            if kind == b'R' and data == pack_int(3):
                self.socket.sendall(frame(b'p', password.encode() + b'\x00'))
            elif kind == b'K':
                self.backend = struct.unpack('!ii', data)
            elif kind in (b'Z', b'E'):
                break

    def exact(self, size):
        chunks = b''
        while len(chunks) < size:
            part = self.socket.recv(size - len(chunks))
            if not part:
                raise EOFError('server closed socket')
            chunks += part
        return chunks

    def read(self):
        kind = self.exact(1)
        size = struct.unpack('!i', self.exact(4))[0]
        assert 4 <= size <= 2 * 1024 * 1024, size
        return kind, self.exact(size - 4)

    @staticmethod
    def summary(kind, data):
        result = {'type': kind.decode('ascii')}
        if kind == b'E':
            fields = data.split(b'\x00')
            result['sqlstate'] = next((f[1:].decode() for f in fields if f.startswith(b'C')), None)
        if kind == b'v':
            result['version'] = struct.unpack('!i', data[:4])[0]
        if kind == b'D':
            size = struct.unpack('!h', data[:2])[0]
            offset, values = 2, []
            for _ in range(size):
                length = struct.unpack('!i', data[offset:offset + 4])[0]
                offset += 4
                values.append(None if length < 0 else data[offset:offset + length].hex())
                offset += max(0, length)
            result['values_hex'] = values
        return result

    def collect(self, terminal=(b'Z', b's', b'E')):
        result = []
        while True:
            kind, data = self.read()
            result.append(self.summary(kind, data))
            if kind in terminal:
                return result

    def action(self, request):
        mode = request['mode']
        if mode == 'portal':
            name = b'' if request.get('unnamed') else b'statement'
            sql = b'SELECT id, title FROM documents ORDER BY id\x00'
            parse = frame(b'P', name + b'\x00' + sql + b'\x00\x00')
            bind = frame(b'B', b'portal\x00' + name + b'\x00' + b'\x00\x00' * 3)
            describe = frame(b'D', b'Pportal\x00')
            execute = frame(b'E', b'portal\x00' + pack_int(2))
            self.socket.sendall(parse + bind + describe + execute + frame(b'H'))
            return self.collect()
        if mode == 'resume':
            self.socket.sendall(frame(b'E', b'portal\x00' + pack_int(2)) + frame(b'H'))
            return self.collect()
        if mode == 'sync':
            self.socket.sendall(frame(b'S'))
            return self.collect((b'Z',))
        if mode == 'close_statement':
            self.socket.sendall(frame(b'C', b'Sstatement\x00') + frame(b'E', b'portal\x00' + pack_int(2)) + frame(b'H'))
            return self.collect()
        if mode == 'replace_unnamed':
            self.socket.sendall(frame(b'P', b'\x00SELECT id FROM documents\x00\x00\x00')
                                + frame(b'E', b'portal\x00' + pack_int(2)) + frame(b'H'))
            return self.collect()
        if mode == 'portal_capacity':
            self.socket.sendall(frame(b'P', b's\x00SELECT id FROM documents\x00\x00\x00') + frame(b'H'))
            assert self.collect((b'1',)) == [{'type': '1'}]
            for index in range(16):
                self.socket.sendall(frame(b'B', f'p{index}'.encode() + b'\x00s\x00' + b'\x00\x00' * 3) + frame(b'H'))
                assert self.collect((b'2',)) == [{'type': '2'}]
            self.socket.sendall(frame(b'B', b'overflow\x00s\x00' + b'\x00\x00' * 3) + frame(b'H'))
            overflow = self.collect()
            self.socket.sendall(frame(b'S'))
            assert self.collect() == [{'type': 'Z'}]
            self.socket.sendall(frame(b'B', b'after_sync\x00s\x00' + b'\x00\x00' * 3) + frame(b'H'))
            assert self.collect((b'2',)) == [{'type': '2'}]
            return overflow
        if mode == 'start_query':
            self.socket.sendall(frame(b'Q', b'SELECT * FROM documents ORDER BY id\x00'))
            return []
        if mode == 'collect_query':
            return self.collect((b'Z',))
        if mode == 'wrong_cancel':
            peer = RawClient(self.password)
            try:
                with socket.create_connection(('127.0.0.1', 5433), timeout=3) as cancel:
                    cancel.sendall(pack_int(16) + pack_int(80877102) + pack_int(self.backend[0]) + pack_int(peer.backend[1]))
                    assert cancel.recv(1) == b''
                if select.select([self.socket], [], [], .15)[0]:
                    return self.collect()
                return [{'type': 'pending'}]
            finally:
                peer.close()
        if mode == 'oversized':
            self.socket.sendall(b'Q' + pack_int(65537))
        elif mode == 'truncated':
            self.socket.sendall(frame(b'Q', b'SELECT')[0:7])
            self.socket.shutdown(socket.SHUT_WR)
        elif mode == 'invalid_utf8':
            self.socket.sendall(frame(b'Q', b'\xff\x00'))
        else:
            raise ValueError('unknown raw probe')
        try:
            return self.collect()
        except (EOFError, ConnectionResetError):
            return [{'type': 'closed'}]

    def close(self):
        self.socket.close()


def malformed_startup(mode):
    with socket.create_connection(('127.0.0.1', 5433), timeout=3) as connection:
        connection.settimeout(3)
        if mode == 'truncated':
            connection.sendall(pack_int(99) + pack_int(196608))
            connection.shutdown(socket.SHUT_WR)
        elif mode == 'oversized':
            connection.sendall(pack_int(65537))
        elif mode == 'invalid_utf8':
            data = pack_int(196608) + b'user\x00\xff\x00database\x00guradb\x00\x00'
            connection.sendall(pack_int(len(data) + 4) + data)
        else:
            raise ValueError('unknown startup probe')
        try:
            data = connection.recv(4096)
            assert not data or data[:1] == b'E', data
            if not data:
                return {'rejected': True, 'closed': True}
            while len(data) < 5:
                data += connection.recv(5 - len(data))
            size = struct.unpack('!i', data[1:5])[0]
            while len(data) < size + 1:
                data += connection.recv(size + 1 - len(data))
            return {'rejected': True, 'closed': False, **RawClient.summary(b'E', data[5:])}
        except ConnectionResetError:
            return {'rejected': True, 'closed': True}
