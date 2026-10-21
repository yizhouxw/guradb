"""CF1-A low-level encoding and closed-shape validation, without orchestration."""
import hashlib
import json
import re
import math
import struct
from modules.common.cf1a_schema import I53, SHAPES


class ContractFailure(ValueError):
    """Stable error class shared by contract consumers."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, message, code='invalid_contract'):
    if not condition:
        raise ContractFailure(code, message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def unique(values):
    return len(values) == len(set(values))


def validate_shape(value, spec):
    if isinstance(spec, list):
        require(type(value) is list and spec[1] <= len(value) <= spec[2], 'invalid array')
        for item in value:
            validate_shape(item, spec[0])
    elif isinstance(spec, tuple):
        require(type(value) is str and value in spec, 'unsupported enum')
    elif spec in SHAPES:
        require(type(value) is dict and value.keys() == SHAPES[spec].keys(), 'unknown or missing field')
        for key, field in SHAPES[spec].items():
            validate_shape(value[key], field)
    elif spec == 'cell':
        require(type(value) is dict and set(value) == {'type', 'value'}, 'invalid typed cell')
        kind, item = value['type'], value['value']
        if kind == 'int8':
            require(type(item) is str and re.fullmatch(r'0|-[1-9][0-9]*|[1-9][0-9]*', item)
                    and len(item) <= 20 and -(1 << 63) <= int(item) < (1 << 63), 'invalid int8')
        elif kind == 'null':
            require(item is None, 'invalid NULL')
        else:
            require(kind in ('text', 'bool'), 'unsupported cell type')
            validate_shape(item, kind)
    elif spec in ('n', 'positive'):
        require(type(value) is int and (spec != 'positive' or value > 0) and 0 <= value <= I53,
                'invalid safe integer')
    elif spec == 'bool':
        require(type(value) is bool, 'invalid bool')
    else:
        require(type(value) is str and len(value) <= 4096, 'invalid string')
        if spec == 'id':
            require(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) and value != 'latest', 'invalid fixed ID')
        elif spec == 'opaque':
            require(0 < len(value) <= 1024 and not re.search(r'[\x00-\x20\x7f]', value), 'invalid opaque reference')
        elif spec == 'score':
            require(re.fullmatch(r'[0-9a-f]{16}', value) and
                    math.isfinite(struct.unpack('>d', bytes.fromhex(value))[0]), 'invalid finite binary64 score')
        elif spec == 'hash':
            require(re.fullmatch(r'[0-9a-f]{64}', value), 'invalid SHA-256')
        else:
            require(spec == 'text', 'unknown shape')
