"""Closed, bounded private P06 layouts; no source or catalog client semantics."""
import hashlib
import json
import math
import struct
import sys
from modules.common.cf1a_primitives import canonical, digest, require, validate_shape
from modules.common.cf1a_read import validate_object
from modules.common.cf1a_wire import Contract

MAX_FILE_BYTES = 1 << 20
MAX_ROWS = 100
PROCESSING_VERSION = 'zh-CN-hand-segmented-v1'
SEPARATORS = frozenset(chr(n) for n in (
    *range(9, 14), 32, 133, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288))


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys), 'unknown or missing private field')


def bounded_list(value, limit):
    require(type(value) is list and len(value) <= limit, 'private array exceeds bound')


def count(value, maximum=MAX_ROWS):
    require(type(value) is int and 0 <= value <= maximum, 'invalid private counter')


def f64_hex(value):
    require(type(value) in (int, float) and -sys.float_info.max <= value <= sys.float_info.max
            and math.isfinite(value), 'invalid finite number')
    return struct.pack('>d', value).hex()


def from_hex(value, component=False):
    validate_shape(value, 'score')
    number = struct.unpack('>d', bytes.fromhex(value))[0]
    require(not component or abs(number) <= 1e150, 'vector component exceeds bound')
    return number


def tokens(text):
    require(type(text) is str and len(text) <= 4096, 'invalid query text')
    result, word = [], []
    for char in text:
        if char in SEPARATORS:
            if word:
                result.append(''.join(word))
                word = []
        else:
            word.append(char)
    if word:
        result.append(''.join(word))
    validate_tokens(result)
    return result


def validate_tokens(values):
    bounded_list(values, 1024)
    require(all(type(term) is str and 0 < len(term) <= 128 and
                not any(char in SEPARATORS for char in term) for term in values), 'invalid fixed token')


def object_ref(ref):
    validate_shape(ref, 'ObjectRef')
    validate_object(ref)
    require(ref['integrity']['mode'] == 'whole_sha256', 'private artifacts require whole hash')


def verified_bytes(raw, ref):
    object_ref(ref)
    require(type(raw) is bytes and len(raw) == ref['size_bytes'] and
            hashlib.sha256(raw).hexdigest() == ref['sha256'], 'object size/hash mismatch', 'corrupt_object')


def strict_json(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_FILE_BYTES, 'private file exceeds bound')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate private JSON field')
            result[key] = value
        return result
    def forbidden(_):
        raise ValueError('JSON float/constant is not supported')
    def integer(value):
        require(value != '-0' and len(value) <= 16, 'invalid private integer')
        number = int(value)
        count(number, (1 << 53) - 1)
        return number
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_float=forbidden,
                           parse_constant=forbidden, parse_int=integer)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            require(depth <= 32, 'private nesting limit')
            if type(item) is dict:
                pending.extend((child, depth + 1) for child in item.values())
            elif type(item) is list:
                pending.extend((child, depth + 1) for child in item)
        require(canonical(value) == raw, 'private file must be canonical UTF-8 JSON')
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        from modules.common.cf1a_primitives import ContractFailure
        if isinstance(error, ContractFailure):
            raise
        raise ContractFailure('invalid_contract', 'invalid private JSON encoding') from error


def envelope(kind, value):
    return Contract(canonical({'contract_version': 'cf1a/1.0',
                              'required_capabilities': ['fixed_read', 'typed_json_v1', 'strong_integrity'],
                              'payload': {kind: value}}))


def mapping(rows):
    return [{name: row[name] for name in ('record_id', 'record_version', 'locator')} for row in rows]


def validate_manifest(value, binding, ref):
    closed(value, ('manifest_version', 'dataset_id', 'data_revision_id', 'schema_sha256',
                   'source_version_id', 'source_objects', 'configurations', 'rows'))
    require(value['manifest_version'] == 'p06-processing/1', 'unknown processing manifest')
    require(binding.kind == 'read_binding', 'expected fixed read binding')
    bound = binding.value
    require(len(bound['revision']['sources']) == 1, 'P06 requires one source')
    source = bound['revision']['sources'][0]
    require(value['dataset_id'] == bound['resource']['dataset_id'] and
            value['data_revision_id'] == bound['revision']['data_revision_id'] and
            value['schema_sha256'] == bound['resource']['schema_sha256'] and
            value['source_version_id'] == source['source_version_id'], 'processing input scope mismatch')
    object_ref(ref)
    require(ref in bound['revision']['objects'], 'processing input outside protected revision')
    bounded_list(value['source_objects'], 100)
    require(bool(value['source_objects']), 'missing source objects')
    for item in value['source_objects']:
        object_ref(item)
        require(item != ref and item in bound['revision']['objects'], 'source object outside fixed revision')
    require(len({digest(item) for item in value['source_objects']}) == len(value['source_objects']),
            'duplicate source object')
    closed(value['configurations'], ('bm25', 'exact_vector'))
    bounded_list(value['rows'], MAX_ROWS)
    identities, locations = [], []
    for row in value['rows']:
        closed(row, ('record_id', 'record_version', 'locator', 'source_cells_sha256', 'text_state',
                     'tokens', 'vector_state', 'vector_reason', 'vector_f64_hex', 'feature_input'))
        for name in ('record_id', 'record_version'):
            validate_shape(row[name], 'id')
        validate_shape(row['source_cells_sha256'], 'hash')
        validate_shape(row['locator'], 'RowLocator')
        location = row['locator']
        require(location['source_version_id'] == source['source_version_id'] and
                location['object'] in value['source_objects'], 'locator outside declared source input')
        object_ref(location['object'])
        validate_tokens(row['tokens'])
        require(row['text_state'] in ('present', 'empty', 'null') and
                (row['text_state'] == 'present') == bool(row['tokens']), 'text eligibility mismatch')
        bounded_list(row['vector_f64_hex'], 3)
        require((row['vector_state'] == 'present' and len(row['vector_f64_hex']) == 3 and
                 row['vector_reason'] == '') or
                (row['vector_state'] == 'null' and not row['vector_f64_hex'] and
                 type(row['vector_reason']) is str and 0 < len(row['vector_reason']) <= 128),
                'missing explicit vector value or NULL reason')
        for component in row['vector_f64_hex']:
            from_hex(component, True)
        feature = row['feature_input']
        if row['vector_state'] == 'present':
            closed(feature, ('feature_id', 'feature_version', 'record_id', 'record_version', 'model_id',
                             'model_version', 'dimension', 'metric', 'normalization', 'processing_version'))
            validate_shape(feature['feature_id'], 'id')
            validate_shape(feature['feature_version'], 'id')
            require(feature['record_id'] == row['record_id'] and feature['record_version'] == row['record_version']
                    and feature['model_id'] == 'outline-synthetic-zh-image3' and feature['model_version'] == '1'
                    and type(feature['dimension']) is int and feature['dimension'] == 3
                    and feature['metric'] == 'squared_l2' and feature['normalization'] == 'none'
                    and feature['processing_version'] == PROCESSING_VERSION, 'feature input provenance mismatch')
        else:
            require(feature is None, 'NULL must not claim a feature input')
        identities.append(row['record_id'])
        locations.append(digest(location))
    require(identities == sorted(set(identities)) and len(locations) == len(set(locations)),
            'duplicate/unsorted identity or physical locator')
    return value
