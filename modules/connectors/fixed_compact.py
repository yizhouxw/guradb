"""Bounded Compact Thrift values for the private, narrow Parquet reader.

Wire rules follow Apache Thrift's Compact Protocol specification. This is not
a generic RPC client. Callers reserve the node budget before parsing any input.
"""
from modules.common.cf1a_primitives import require


class Compact:
    def __init__(self, raw, check, *, max_nodes=4096):
        require(isinstance(raw, (bytes, memoryview)), 'invalid compact input')
        require(type(max_nodes) is int and 0 < max_nodes <= 4096, 'invalid node budget')
        self.raw, self.check = memoryview(raw), check
        self.position, self.nodes, self.max_nodes = 0, 0, max_nodes

    def take(self, size):
        self.check()
        require(type(size) is int and 0 <= size <= len(self.raw) - self.position,
                'truncated compact value', 'corrupt_object')
        start = self.position
        self.position += size
        return self.raw[start:self.position]

    def byte(self):
        return self.take(1)[0]

    def varint(self, bits=64):
        value = 0
        for shift in range(0, bits, 7):
            octet = self.byte()
            value |= (octet & 127) << shift
            if octet < 128:
                require(value < 1 << bits and (shift == 0 or octet != 0),
                        'overflow or noncanonical compact integer', 'corrupt_object')
                return value
        require(False, 'unterminated compact integer', 'corrupt_object')

    def integer(self, bits):
        value = self.varint(bits)
        return (value >> 1) ^ -(value & 1)

    def node(self, depth):
        self.check()
        require(depth <= 12 and self.nodes < self.max_nodes,
                'compact structure exceeds certified bound', 'resource_limit')
        self.nodes += 1

    def struct(self, depth=0):
        self.node(depth)
        result, previous = {}, 0
        while True:
            header = self.byte()
            if header == 0:
                return result
            tag, delta = header & 15, header >> 4
            field = previous + delta if delta else self.integer(16)
            require(0 < field <= 32767 and field not in result and len(result) < 64,
                    'invalid or duplicate compact field', 'corrupt_object')
            result[field] = (tag, self.value(tag, depth + 1, field_bool=True))
            previous = field

    def value(self, tag, depth, *, field_bool=False):
        self.node(depth)
        if tag in (1, 2):
            flag = tag if field_bool else self.byte()
            require(flag in (1, 2), 'invalid compact boolean', 'corrupt_object')
            return flag == 1
        if tag == 3:
            octet = self.byte()
            return octet if octet < 128 else octet - 256
        if tag in (4, 5, 6):
            return self.integer({4: 16, 5: 32, 6: 64}[tag])
        if tag == 8:
            size = self.varint(32)
            require(size <= 65536, 'compact binary exceeds certified bound', 'resource_limit')
            return self.take(size)
        if tag == 9:
            header = self.byte()
            element, count = header & 15, header >> 4
            count = self.varint(32) if count == 15 else count
            require(count <= 1024 and count <= self.max_nodes - self.nodes,
                    'compact list exceeds certified bound', 'resource_limit')
            require(element in (1, 2, 3, 4, 5, 6, 8, 9, 12),
                    'unsupported compact list type', 'unsupported_capability')
            return element, [self.value(element, depth + 1) for _ in range(count)]
        if tag == 12:
            return self.struct(depth + 1)
        require(False, 'unsupported compact value type', 'unsupported_capability')


def shape(value, required, optional=None):
    """Reject unknown semantics and wrong wire types before using a structure."""
    optional = optional or {}
    require(type(value) is dict and set(required) <= value.keys(),
            'missing parquet metadata field', 'corrupt_object')
    allowed = {**required, **optional}
    require(value.keys() <= allowed.keys(), 'unsupported parquet metadata field', 'unsupported_capability')
    for key, (tag, _) in value.items():
        require(tag == allowed[key], 'wrong parquet metadata wire type', 'corrupt_object')


def item(value, key):
    return value[key][1]


def array(value, key, element):
    actual, children = item(value, key)
    require(actual == element, 'wrong parquet list element type', 'corrupt_object')
    return children


def text(value, *, maximum=4096):
    require(isinstance(value, memoryview) and len(value) <= 4 * maximum,
            'parquet string exceeds bound', 'resource_limit')
    try:
        result = value.tobytes().decode('utf-8')
    except UnicodeError:
        require(False, 'invalid parquet UTF8', 'corrupt_object')
    require(len(result) <= maximum, 'parquet string exceeds bound', 'resource_limit')
    return result
