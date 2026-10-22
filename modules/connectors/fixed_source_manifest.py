"""Closed p04-fixed/1 metadata. No listing, inferred schema, or latest lookup."""
import json

from modules.common.cf1a_primitives import ContractFailure, canonical, digest, require, validate_shape
from modules.common.cf1a_read import validate_object

MAX_METADATA = 65536


def closed(value, names):
    require(type(value) is dict and value.keys() == set(names), 'unknown or missing fixed source field')


def bounded_json(raw, check):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_METADATA,
            'fixed metadata exceeds bound', 'resource_limit')
    # Bound nesting and structural allocation before json.loads. Quoted commas
    # and escaped quotes are data, not structural nodes. JSON's actual grammar,
    # Unicode and closing-bracket matching are still checked by the decoder.
    quoted, escaped, depth, nodes = False, False, 0, 0
    for index, octet in enumerate(raw):
        if index % 256 == 0:
            check()
        if quoted:
            if escaped:
                escaped = False
            elif octet == 92:
                escaped = True
            elif octet == 34:
                quoted = False
        elif octet == 34:
            quoted = True
            nodes += 1
        elif octet in (91, 123):
            depth += 1
            nodes += 1
        elif octet in (93, 125):
            depth -= 1
        elif octet in (44, 58):
            nodes += 1
        require(0 <= depth <= 12 and nodes <= 4096,
                'fixed metadata structure exceeds bound', 'resource_limit')
    require(not quoted and depth == 0, 'truncated fixed metadata', 'corrupt_object')

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate fixed metadata field')
            result[key] = value
        return result

    def forbidden(_):
        raise ContractFailure('invalid_contract', 'unsupported fixed metadata number')

    def integer(token):
        require(token != '-0' and len(token) <= 16, 'invalid fixed metadata integer')
        result = int(token)
        validate_shape(result, 'n')
        return result

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_float=forbidden,
                           parse_constant=forbidden, parse_int=integer)
        require(canonical(value) == raw, 'fixed metadata must be canonical UTF8 JSON')
        check()
        return value
    except ContractFailure:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise ContractFailure('corrupt_object', 'invalid fixed metadata encoding') from None


def source_fields(value):
    require(type(value) is list and 0 < len(value) <= 32, 'invalid complete source schema')
    ids, names = [], set()
    for field in value:
        closed(field, ('source_field_id', 'name', 'type', 'nullable'))
        identifier = field['source_field_id']
        require(type(identifier) is int and 0 < identifier < 1 << 31, 'invalid physical field identity')
        name = field['name']
        require(type(name) is str and 0 < len(name) <= 128 and '\0' not in name and name not in names,
                'invalid or duplicate physical field name')
        require(field['type'] in ('text', 'int8', 'bool') and type(field['nullable']) is bool,
                'unsupported fixed source field', 'unsupported_capability')
        ids.append(identifier)
        names.add(name)
    require(ids == sorted(set(ids)), 'physical schema must have unique ascending field IDs')


def object_reference(value):
    validate_shape(value, 'ObjectRef')
    validate_object(value)
    return canonical(value)


def manifest(raw, source, scope):
    value = bounded_json(raw, scope.check)
    closed(value, ('manifest_version', 'source_id', 'source_version_id', 'snapshot_id',
                   'source_schema', 'files', 'delete_files', 'schema_evolution'))
    require(value['manifest_version'] == 'p04-fixed/1', 'unsupported fixed metadata version',
            'unsupported_version')
    require(value['delete_files'] == [] and value['schema_evolution'] == 'none',
            'source delete or schema evolution is unsupported', 'unsupported_capability')
    for key in ('source_id', 'source_version_id', 'snapshot_id'):
        require(value[key] == source[key], 'fixed source identity mismatch', 'corrupt_object')
    source_fields(value['source_schema'])
    require(digest(value['source_schema']) == source['source_schema_sha256'],
            'complete source schema digest mismatch', 'corrupt_object')
    physical = {field['source_field_id']: field for field in value['source_schema']}
    for mapping in source['field_mapping']:
        if mapping['source_field_id']:
            field = physical.get(mapping['source_field_id'])
            require(field is not None and field['type'] == mapping['source_type'],
                    'source mapping references missing or wrong field', 'corrupt_object')
    files = value['files']
    require(type(files) is list and len(files) <= 4, 'fixed source file count exceeds bound', 'resource_limit')
    metadata = object_reference(source['metadata'])
    objects, total_groups, total_rows, total_bytes = {metadata}, 0, 0, 0
    for entry in files:
        scope.check()
        closed(entry, ('object', 'row_group_rows'))
        encoded = object_reference(entry['object'])
        require(encoded not in objects, 'duplicate fixed file or metadata used as data')
        require(entry['object']['size_bytes'] <= 1 << 20, 'fixed data file exceeds bound', 'resource_limit')
        groups = entry['row_group_rows']
        require(type(groups) is list and 0 < len(groups) <= 16
                and all(type(n) is int and 0 < n <= 1000 for n in groups), 'invalid fixed group counts')
        total_groups += len(groups)
        total_rows += sum(groups)
        total_bytes += entry['object']['size_bytes']
        objects.add(encoded)
    require(total_groups <= 16 and total_rows <= 1000 and total_bytes <= 4 << 20,
            'fixed source aggregate bounds exceeded', 'resource_limit')
    return value
