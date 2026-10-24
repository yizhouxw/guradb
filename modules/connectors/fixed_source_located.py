"""Private, same-process A + actual decoder provenance, never an auth capability.

The producer owns the shared reservation and single delivery. Consumers must
independently read the fixed locator; structural validation is not row proof.
"""
from dataclasses import dataclass
import hashlib
import json

from modules.common.cf1a_primitives import ContractFailure, canonical, digest, require, validate_shape
from modules.common.cf1a_read import validate_batch_for, without
from modules.common.cf1a_schema import I53, VERSION
from modules.common.cf1a_wire import Contract

MAX_JOINT = 768 << 10


@dataclass(frozen=True)
class LocatedBatch:
    batch: Contract
    provenance_encoded: bytes

    def __post_init__(self):
        require(type(self.batch) is Contract and type(self.provenance_encoded) is bytes,
                'located values must own immutable bytes')

    @property
    def wire_bytes(self):
        return len(self.batch.encoded) + len(self.provenance_encoded)


def _string_size(text):
    # JSON UTF8 size without allocating a temporary escaped string/bytes.
    return 2 + sum(2 if c in ('"', '\\') else 6 if ord(c) < 32 else
                   1 if ord(c) < 128 else 2 if ord(c) < 2048 else
                   3 if ord(c) < 65536 else 4 for c in text)


def joint_bound(rows, locations, ordinary_bound, check):
    sidecar = 1024
    for row in rows:
        check()
        locator = locations[row['record_id']]
        ref, integrity = locator['object'], locator['object']['integrity']
        strings = [locator['source_version_id'], ref['backend_id'], ref['bucket'], ref['key'],
                   ref['version'], ref['sha256'], integrity['mode'], integrity['proof_ref']]
        # Closed keys, integer widths, punctuation and each 64hex digest/list entry.
        sidecar += (768 + _string_size(row['record_id']) + _string_size(row['record_version'])
                    + sum(_string_size(text) for text in strings)
                    + 72 * len(integrity['block_sha256']))
    return ordinary_bound + sidecar


def _closed(value, names):
    require(type(value) is dict and set(value) == set(names), 'unknown or missing located field')


def _provenance(raw):
    require(type(raw) is bytes and len(raw) <= MAX_JOINT, 'located wire exceeds bound', 'resource_limit')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate located field')
            result[key] = value
        return result
    def forbidden(_):
        raise ContractFailure('invalid_contract', 'nonfinite located number')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=forbidden)
        require(canonical(value) == raw, 'located provenance must be canonical UTF8 JSON')
        return value
    except ContractFailure:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ContractFailure('invalid_contract', 'invalid located provenance') from None


def validate_located_for(binding, located, *, expected_locations=None, bounds=None):
    """Validate data coupling; only the producer supplies trusted decoder bounds.

    Without those private facts a consumer still must perform actual row lookup.
    No successful call authenticates the caller or authorizes another read.
    """
    require(type(located) is LocatedBatch and type(located.batch) is Contract,
            'expected immutable located batch')
    require(located.wire_bytes <= MAX_JOINT, 'combined located wire exceeds bound', 'resource_limit')
    validate_batch_for(binding, located.batch)
    batch, fixed = located.batch.value, binding.value
    value = _provenance(located.provenance_encoded)
    _closed(value, ('version', 'context_sha256', 'batch_sha256', 'batch_ordinal', 'last', 'rows'))
    require(value['version'] == 'p04-located/1', 'unsupported located version', 'unsupported_version')
    require(value['context_sha256'] == binding.sha256 and value['batch_sha256'] == located.batch.sha256
            and value['batch_ordinal'] == batch['batch_ordinal'] and value['last'] == batch['last'],
            'located batch/context/page mismatch')
    validate_shape(value['batch_ordinal'], 'n')
    validate_shape(value['last'], 'bool')
    require(type(value['rows']) is list and len(value['rows']) == len(batch['rows']) <= 64,
            'located rows differ from complete page')
    sources = {source['source_version_id'] for source in fixed['revision']['sources']}
    metadata = [source['metadata'] for source in fixed['revision']['sources']]
    for row, original in zip(value['rows'], batch['rows']):
        _closed(row, ('record_id', 'record_version', 'cells_sha256', 'locator'))
        require(row['record_id'] == original['record_id'] and row['record_version'] == original['record_version']
                and row['cells_sha256'] == digest(original['cells']), 'located record/cells mismatch')
        locator = row['locator']
        validate_shape(locator, 'RowLocator')
        require(locator['source_version_id'] in sources and locator['object'] in fixed['revision']['objects']
                and locator['object'] not in metadata, 'located object outside fixed data')
        if bounds is not None:
            groups = bounds.get((locator['source_version_id'], canonical(locator['object'])))
            require(groups is not None and locator['row_group'] < len(groups)
                    and locator['row_offset'] < groups[locator['row_group']], 'located row outside decoded file')
        if expected_locations is not None:
            require(locator == expected_locations[original['record_id']], 'located row differs from decoder')
    return value


def _sidecar(binding, value, locations):
    return {'version': 'p04-located/1', 'context_sha256': binding.sha256,
            'batch_sha256': '0' * 64, 'batch_ordinal': value['batch_ordinal'], 'last': value['last'],
            'rows': [{'record_id': row['record_id'], 'record_version': row['record_version'],
                      'cells_sha256': digest(row['cells']), 'locator': locations[row['record_id']]}
                     for row in value['rows']]}


def encode_located(binding, value, locations, bounds, scope, bound):
    """Called inside the reader's reserved/owned batch, before any final delivery."""
    prefix = value['usage']['output_bytes']
    sidecar = _sidecar(binding, value, locations)
    usage = prefix
    for _ in range(32):
        scope.check()
        require(0 <= usage <= I53, 'located output counter exceeds safe integer', 'resource_limit')
        value['usage']['output_bytes'] = usage
        value['content_sha256'] = digest(without(value, 'content_sha256'))
        raw = canonical({'contract_version': VERSION,
            'required_capabilities': ['fixed_read', 'typed_json_v1', 'strong_integrity'],
            'payload': {'read_batch': value}})
        sidecar['batch_sha256'] = hashlib.sha256(raw).hexdigest()
        provenance = canonical(sidecar)
        length = len(raw) + len(provenance)
        require(length <= MAX_JOINT and length <= bound, 'combined located wire exceeds bound', 'resource_limit')
        scope.output(length)  # Only L is new. Prefix D is already in the parent ledger.
        wanted = prefix + length
        require(wanted <= I53, 'located output counter exceeds safe integer', 'resource_limit')
        if usage == wanted:
            break
        usage = wanted
    else:
        require(False, 'located output fixedpoint did not converge', 'resource_limit')
    result = LocatedBatch(Contract(raw), provenance)
    require(result.batch.encoded == raw and usage == prefix + result.wire_bytes,
            'located canonical bytes/accounting changed')
    validate_located_for(binding, result, expected_locations=locations, bounds=bounds)
    return result
