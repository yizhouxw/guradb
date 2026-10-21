"""Immutable, fail-closed CF1-A wire values. No clients or execution state."""
from dataclasses import dataclass
import hashlib
import json
from modules.common.cf1a_schema import CAPABILITIES, KINDS, VERSION
from modules.common.cf1a_primitives import ContractFailure, canonical, digest, require, unique, validate_shape
from modules.common.cf1a_read import validate_read
from modules.common.cf1a_publication import validate_publication


def decode_document(raw):
    require(isinstance(raw, (str, bytes)) and len(raw) <= 1 << 20, 'envelope too large')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    def constant(_):
        raise ContractFailure('invalid_contract', 'nonfinite JSON')
    def integer(token):
        require(token != '-0', 'negative zero JSON integer')
        return int(token)
    try:
        require(len(raw.encode('utf-8') if isinstance(raw, str) else raw) <= 1 << 20, 'envelope byte limit exceeded')
        text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_int=integer)
        pending = [(value, 0)]
        while pending:
            node, depth = pending.pop()
            require(depth <= 64, 'JSON nesting limit exceeded')
            if type(node) is dict:
                pending.extend((item, depth + 1) for item in node.values())
            elif type(node) is list:
                pending.extend((item, depth + 1) for item in node)
        require(type(value) is dict and set(value) == {'contract_version', 'required_capabilities', 'payload'},
                'invalid envelope fields')
        require(value['contract_version'] == VERSION, 'unsupported contract version', 'unsupported_version')
        caps = value['required_capabilities']
        require(type(caps) is list and all(type(cap) is str for cap in caps) and unique(caps), 'invalid capability set')
        require(set(caps) <= set(CAPABILITIES), 'unknown required capability', 'unsupported_capability')
        payload = value['payload']
        require(type(payload) is dict and len(payload) == 1, 'expected exactly one payload')
        kind = next(iter(payload))
        require(kind in KINDS, 'unsupported payload')
        baseline = {'fixed_read', 'typed_json_v1', 'strong_integrity'}
        if kind in ('register_intent', 'publish_intent', 'mutation_receipt', 'mutation_auth'):
            baseline.add('catalog_cas')
        require(baseline <= set(caps), 'missing required capability', 'unsupported_capability')
        validate_shape(payload[kind], KINDS[kind])
        validate_read(kind, payload[kind])
        validate_publication(kind, payload[kind])
        require(len(canonical(value)) <= 1 << 20, 'canonical envelope too large')
        return value
    except ContractFailure:
        raise
    except (ValueError, UnicodeError, RecursionError, TypeError) as error:
        raise ContractFailure('invalid_contract', 'invalid JSON encoding') from error


@dataclass(frozen=True)
class Contract:
    """A validated canonical value; consumers receive copies, never mutable internals."""
    encoded: bytes

    def __post_init__(self):
        object.__setattr__(self, 'encoded', canonical(decode_document(self.encoded)))

    @property
    def document(self):
        return json.loads(self.encoded)

    @property
    def kind(self):
        return next(iter(self.document['payload']))

    @property
    def value(self):
        return self.document['payload'][self.kind]

    @property
    def sha256(self):
        return hashlib.sha256(self.encoded).hexdigest()


def decode(raw):
    return Contract(raw)
