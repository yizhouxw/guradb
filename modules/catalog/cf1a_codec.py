"""Canonical metadata, explicit quota constants, and strict persisted values."""
import hashlib
import json
from dataclasses import dataclass

from modules.common.cf1a_primitives import ContractFailure, canonical, digest, require, validate_shape
from modules.common.cf1a_schema import CAPABILITIES, VERSION
from modules.common.cf1a_wire import Contract

LIMITS = {'datasets': 16, 'grants': 64, 'identities': 256, 'targets': 128,
          'operations': 512, 'queries': 1024}
MAX_METADATA_BYTES = 8 << 20
MAX_COUNTER = (1 << 53) - 1


def contract(kind, value):
    return Contract(canonical({'contract_version': VERSION,
                               'required_capabilities': list(CAPABILITIES),
                               'payload': {kind: value}}))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def stored_contract(raw, expected_sha, expected_kind):
    require(isinstance(raw, (bytes, memoryview)), 'invalid stored catalog bytes')
    value = bytes(raw)
    require(sha(value) == expected_sha, 'stored catalog digest mismatch')
    result = Contract(value)
    require(result.kind == expected_kind and result.encoded == value, 'noncanonical stored catalog value')
    return result


def counter(value, increment=0):
    validate_shape(value, 'n')
    require(type(increment) is int and 0 <= increment <= MAX_COUNTER - value,
            'catalog counter exhausted', 'resource_limit')
    return value + increment


def identity_values(target):
    value = target.value
    resource, revision, view = value['resource'], value['revision'], value['view']
    return [('resource', resource['dataset_id'], resource),
            ('revision', revision['data_revision_id'], revision),
            ('view', view['read_view_id'], view)] + [
                ('source', item['source_version_id'], item) for item in revision['sources']] + [
                ('artifact', item['artifact_id'], item) for item in value['indexes']]


def receipt(intent, state, generation, code='none'):
    value = intent.value
    return contract('mutation_receipt', {
        'operation_id': value['operation_id'], 'request_sha256': digest(value),
        'state': state, 'generation': generation,
        'result_id': value.get('target_view_id', value['target_revision_id']) if state == 'applied' else '',
        'reconcile_ref': value['operation_id'], 'error_code': code})


def private_value(raw, expected_sha):
    """Private records use canonical bytes and closed typed validation at the consumer."""
    require(isinstance(raw, (bytes, memoryview)) and len(raw) <= 1 << 20, 'invalid private stored bytes')
    raw = bytes(raw)
    require(sha(raw) == expected_sha, 'private stored digest mismatch')
    try:
        value = json.loads(raw)
        require(canonical(value) == raw, 'noncanonical private metadata')
        return value
    except ContractFailure:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise ContractFailure('invalid_contract', 'invalid private persisted JSON') from None


@dataclass(frozen=True)
class AdminResult:
    """Immutable private terminal/unknown result; deliberately not an A Receipt."""
    encoded: bytes

    def __post_init__(self):
        require(isinstance(self.encoded, (bytes, memoryview)), 'invalid admin result bytes')
        object.__setattr__(self, 'encoded', bytes(self.encoded))
        value = private_value(self.encoded, sha(self.encoded))
        require(type(value) is dict and set(value) == {'version', 'operation_id', 'dataset_id',
            'request_sha256', 'state', 'generation', 'policy_epoch', 'owner_epoch', 'reconcile_ref'},
            'invalid admin result fields')
        require(value['version'] == 'cf1a-admin/1' and value['state'] in ('applied', 'outcome_unknown'),
                'invalid admin result state')
        for name in ('operation_id', 'dataset_id', 'reconcile_ref'):
            validate_shape(value[name], 'id')
        validate_shape(value['request_sha256'], 'hash')
        for name in ('generation', 'policy_epoch', 'owner_epoch'):
            counter(value[name])
        require(value['state'] != 'applied' or value['policy_epoch'] > 0 and value['owner_epoch'] > 0,
                'invalid applied admin epochs')

    @property
    def value(self):
        return json.loads(self.encoded)
