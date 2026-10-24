"""Validate complete flat Parquet metadata before any row can be delivered.

Only contiguous, uncompressed, non-dictionary column chunks are admitted. Known
auxiliary writer metadata is never used to infer schema, rows, or identity.
"""
import struct

from modules.common.cf1a_primitives import require
from modules.connectors.fixed_compact import Compact, array, item, shape, text

KINDS = {'text': 6, 'int8': 2, 'bool': 0}


def scalar_field(node):
    shape(node, {1: 5, 3: 5, 4: 8, 9: 5}, {6: 5, 10: 12})
    physical, repetition = item(node, 1), item(node, 3)
    require(physical in (0, 2, 6) and repetition in (0, 1),
            'unsupported parquet scalar', 'unsupported_capability')
    converted = item(node, 6) if 6 in node else None
    logical = item(node, 10) if 10 in node else None
    if physical == 6:
        require(converted in (None, 0) and (logical is None or logical == {1: (12, {})})
                and (converted == 0 or logical is not None),
                'BYTE_ARRAY requires the supported UTF8 annotation', 'unsupported_capability')
    else:
        require(converted is None and logical is None,
                'annotated integer or boolean is unsupported', 'unsupported_capability')
    identifier = item(node, 9)
    require(identifier > 0, 'missing parquet physical field identity', 'corrupt_object')
    return {'source_field_id': identifier, 'name': text(item(node, 4), maximum=128),
            'type': {0: 'bool', 2: 'int8', 6: 'text'}[physical], 'nullable': repetition == 1}


def schema(nodes, expected):
    require(2 <= len(nodes) <= 33, 'invalid flat parquet schema', 'unsupported_capability')
    root = nodes[0]
    shape(root, {4: 8, 5: 5}, {3: 5})
    require(item(root, 5) == len(nodes) - 1 and (3 not in root or item(root, 3) == 0),
            'nested parquet schema is unsupported', 'unsupported_capability')
    text(item(root, 4), maximum=128)
    fields = [scalar_field(node) for node in nodes[1:]]
    require(len({field['name'] for field in fields}) == len(fields)
            and len({field['source_field_id'] for field in fields}) == len(fields),
            'duplicate parquet field identity', 'corrupt_object')
    require(sorted(fields, key=lambda field: field['source_field_id']) == expected,
            'complete physical parquet schema mismatch', 'corrupt_object')
    return fields


def auxiliary(metadata, width):
    if 5 in metadata:
        seen = set()
        for pair in array(metadata, 5, 12):
            shape(pair, {1: 8}, {2: 8})
            name = text(item(pair, 1), maximum=128)
            require(name == 'ARROW:schema' and name not in seen and 2 in pair,
                    'unsupported parquet writer metadata', 'unsupported_capability')
            seen.add(name)
            # Bounded opaque auxiliary data. The actual Parquet schema above,
            # never this serialized Arrow schema, is the source of truth.
    if 6 in metadata:
        text(item(metadata, 6))
    if 7 in metadata:
        orders = array(metadata, 7, 12)
        require(len(orders) == width and all(order == {1: (12, {})} for order in orders),
                'unsupported parquet column order', 'unsupported_capability')


def size_statistics(value, field, rows):
    """Validate optional flat-column estimates without trusting them as data."""
    shape(value, {}, {1: 6, 2: 9, 3: 9})
    result = {}
    if 1 in value:
        size = item(value, 1)
        require(field['type'] == 'text' and type(size) is int and 0 <= size <= 1 << 20,
                'invalid parquet unencoded byte count', 'corrupt_object')
        result['text_bytes'] = size
    for key, width in ((2, 1), (3, 2 if field['nullable'] else 1)):
        if key not in value:
            continue
        counts = array(value, key, 6)
        # PyArrow22 writes empty lists for omitted flat-level histograms.
        require(len(counts) in (0, width)
                and all(type(count) is int and 0 <= count <= rows for count in counts)
                and (not counts or sum(counts) == rows),
                'invalid flat parquet size histogram', 'corrupt_object')
        if key == 3 and counts:
            result['null_count'] = counts[0] if field['nullable'] else 0
    return result


def column(chunk, field, rows, end):
    # file_offset is deprecated; this private reader accepts only the usual 0.
    shape(chunk, {2: 6, 3: 12})
    require(item(chunk, 2) == 0, 'external column metadata is unsupported', 'unsupported_capability')
    value = item(chunk, 3)
    shape(value, {1: 5, 2: 9, 3: 9, 4: 5, 5: 6, 6: 6, 7: 6, 9: 6}, {13: 9, 16: 12})
    require(item(value, 1) == KINDS[field['type']] and item(value, 4) == 0,
            'compressed or mismatched parquet column', 'unsupported_capability')
    encodings = array(value, 2, 5)
    require(len(set(encodings)) == len(encodings) and 0 in encodings and set(encodings) <= {0, 3},
            'dictionary or unsupported parquet encoding', 'unsupported_capability')
    paths = array(value, 3, 8)
    require(len(paths) == 1 and text(paths[0], maximum=128) == field['name'],
            'column path does not match complete physical schema', 'corrupt_object')
    size, offset = item(value, 7), item(value, 9)
    require(item(value, 5) == rows and item(value, 6) == size and 0 < size <= end - 4
            and 4 <= offset <= end - size, 'invalid parquet chunk bounds', 'corrupt_object')
    if 13 in value:
        statistics = array(value, 13, 12)
        require(len(statistics) == 1, 'unsupported page encoding summary', 'unsupported_capability')
        stat = statistics[0]
        shape(stat, {1: 5, 2: 5, 3: 5})
        require(item(stat, 1) == item(stat, 2) == 0,
                'only DataPageV1 PLAIN summaries are supported', 'unsupported_capability')
        require(0 < item(stat, 3) <= rows,
                'invalid page encoding summary', 'corrupt_object')
    return {'field': field, 'offset': offset, 'size': size,
            'pages': item(statistics[0], 3) if 13 in value else None,
            'size_statistics': size_statistics(item(value, 16), field, rows) if 16 in value else None}


def footer(raw, expected, group_rows, scope):
    require(type(raw) is bytes and 12 <= len(raw) <= 1 << 20,
            'parquet input exceeds certified bounds', 'resource_limit')
    require(raw[:4] == raw[-4:] == b'PAR1', 'invalid parquet magic', 'corrupt_object')
    size = struct.unpack_from('<I', raw, len(raw) - 8)[0]
    require(0 < size <= 65536 and size <= len(raw) - 12,
            'invalid parquet footer length', 'corrupt_object')
    end = len(raw) - 8 - size
    # Each Compact node has at most one dictionary/list entry and a scalar or
    # pair wrapper. Binary values are views of the already charged input pool.
    # This transient reservation is acquired before constructing the tree.
    nodes = min(4096, size)
    with scope.reserve(nodes * 512 + 4096):
        parser = Compact(memoryview(raw)[end:end + size], scope.check, max_nodes=nodes)
        metadata = parser.struct()
        require(parser.position == size, 'trailing parquet footer bytes', 'corrupt_object')
        shape(metadata, {1: 5, 2: 9, 3: 6, 4: 9}, {5: 9, 6: 8, 7: 9})
        require(item(metadata, 1) in (1, 2), 'unsupported parquet file version', 'unsupported_version')
        fields = schema(array(metadata, 2, 12), expected)
        auxiliary(metadata, len(fields))
        groups = array(metadata, 4, 12)
        require(len(groups) == len(group_rows) <= 16 and item(metadata, 3) == sum(group_rows)
                and 0 < sum(group_rows) <= 1000, 'parquet row group coverage mismatch', 'corrupt_object')
        result, ranges = [], []
        for ordinal, (group, rows) in enumerate(zip(groups, group_rows)):
            scope.check()
            shape(group, {1: 9, 2: 6, 3: 6}, {5: 6, 6: 6, 7: 4})
            chunks = array(group, 1, 12)
            require(item(group, 3) == rows and len(chunks) == len(fields),
                    'incomplete parquet group', 'corrupt_object')
            plan = [column(chunk, field, rows, end) for chunk, field in zip(chunks, fields)]
            total = sum(value['size'] for value in plan)
            require(item(group, 2) == total and (6 not in group or item(group, 6) == total)
                    and (7 not in group or item(group, 7) == ordinal)
                    and (5 not in group or item(group, 5) == plan[0]['offset']),
                    'parquet group accounting mismatch', 'corrupt_object')
            ranges.extend((value['offset'], value['offset'] + value['size']) for value in plan)
            result.append(plan)
        cursor = 4
        for start, stop in sorted(ranges):
            require(start == cursor, 'overlapping or uncovered parquet data', 'corrupt_object')
            cursor = stop
        require(cursor == end, 'unconsumed parquet file data', 'corrupt_object')
        scope.check()
        return result
