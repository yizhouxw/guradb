"""M1 shared bounded input, identity and failure contracts."""
import hashlib
import json
import re
import struct
import time
import uuid

MAX_BYTES = 32 << 20
MAX_ROWS = 10000
MAX_FILES = 32


class Failure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

    def envelope(self):
        return {'error': {'code': self.code, 'message': self.message,
                          'retryable': False, 'request_id': str(uuid.uuid4())}}


def require(condition, code='unsupported_source', message='input outside M1 supported subset'):
    if not condition:
        raise Failure(code, message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z_][a-z_0-9]{0,62}', value) is not None


def key(value, kind):
    if kind == 'long':
        require(type(value) is int and -(1 << 63) <= value < (1 << 63), 'invalid_key')
        tag, raw = 2, struct.pack('>q', value)
    else:
        require(kind == 'string' and isinstance(value, str), 'invalid_key')
        tag, raw = 1, value.encode()
    require(len(raw) <= 4096, 'invalid_key')
    return (b'\x01' + struct.pack('>I', 1) + bytes([tag]) + struct.pack('>I', len(raw)) + raw).hex()


def public_values(values):
    return {name: str(value) if type(value) is int else value for name,value in values.items()}


def decode_json(raw):
    def pairs(items):
        result = {}
        for name,value in items:
            require(name not in result, 'invalid_request', 'duplicate JSON field')
            result[name] = value
        return result
    def constant(_):
        raise Failure('invalid_request', 'nonfinite JSON number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def public_media(media):
    return [{k:v for k,v in item.items() if k != 'copy'} for item in media]


class Budget:
    def __init__(self, cancelled=lambda: False, seconds=30):
        self.cancelled = cancelled
        self.deadline = time.monotonic() + seconds
        self.reads = self.bytes = 0
        self.artifact_reads = self.artifact_bytes = 0
        self.limits = {"reads": 128, "bytes": MAX_BYTES, "artifact_reads": 256, "artifact_bytes": 128 << 20}

    def check(self):
        require(not self.cancelled(), 'cancelled', 'operation cancelled')
        require(time.monotonic() < self.deadline, 'timeout', 'operation deadline exceeded')

    def artifact(self, size):
        self.check()
        self.artifact_reads += 1
        self.artifact_bytes += size
        require(self.artifact_reads <= self.limits['artifact_reads'] and self.artifact_bytes <= self.limits['artifact_bytes'], 'resource_limit', 'artifact budget exceeded')

    def account(self, size):
        self.check()
        self.reads += 1
        self.bytes += size
        require(self.reads <= self.limits['reads'] and self.bytes <= self.limits['bytes'], 'resource_limit', 'source byte budget exceeded')

    def counters(self):
        return {name: getattr(self, name) for name in self.limits}

    def allocation(self, count):
        self.check()
        return {name: max(0, limit-getattr(self, name)) // count for name, limit in self.limits.items()}

    def merge(self, counters):
        require(isinstance(counters, dict) and set(counters) == set(self.limits) and
                all(type(value) is int and value >= 0 for value in counters.values()), 'worker_mismatch')
        for name, value in counters.items():
            setattr(self, name, getattr(self, name)+value)
            require(getattr(self, name) <= self.limits[name], 'resource_limit', 'aggregate task budget exceeded')
        self.check()
