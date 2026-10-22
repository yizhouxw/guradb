"""Checked PLAIN DataPageV1 decoding, without Arrow/native decompression.

All offsets refer to the already verified input pool. Callers pre-reserve
decoded values/containers and keep the original query scope throughout.
"""
import struct
import zlib

from modules.common.cf1a_primitives import require
from modules.connectors.fixed_compact import Compact, item, shape


class Values:
    def __init__(self, raw, check):
        self.raw, self.check, self.position = memoryview(raw), check, 0

    def take(self, size):
        self.check()
        require(type(size) is int and 0 <= size <= len(self.raw) - self.position,
                'truncated parquet page value', 'corrupt_object')
        position = self.position
        self.position += size
        return self.raw[position:self.position]

    def uint32(self):
        return struct.unpack('<I', self.take(4))[0]


def definitions(values, count):
    size = values.uint32()
    require(size > 0, 'empty parquet definition stream', 'corrupt_object')
    stream = Compact(values.take(size), values.check)
    result = []
    while stream.position < size:
        header = stream.varint(32)
        require(header > 0 and len(result) < count, 'extra parquet definition run', 'corrupt_object')
        remaining = count - len(result)
        if header & 1:
            groups = header >> 1
            # A final bit-packed group may pad at most seven unused bits.
            require(groups > 0 and groups * 8 <= remaining + 7,
                    'parquet definition run exceeds rows', 'corrupt_object')
            raw = stream.take(groups)
            for index in range(min(remaining, groups * 8)):
                values.check()
                result.append((raw[index // 8] >> (index % 8)) & 1)
            require(groups * 8 <= remaining or stream.position == size,
                    'padding before the final definition run', 'corrupt_object')
        else:
            run = header >> 1
            require(0 < run <= remaining, 'parquet RLE exceeds remaining rows', 'corrupt_object')
            flag = stream.byte()
            require(flag in (0, 1), 'invalid flat parquet definition value', 'corrupt_object')
            # Check run bounds before expanding and check cancellation per value.
            for _ in range(run):
                values.check()
                result.append(flag)
    require(len(result) == count, 'incomplete parquet definitions', 'corrupt_object')
    return result


def plain(body, field, count, check):
    values = Values(body, check)
    present = definitions(values, count) if field['nullable'] else [1] * count
    nonnull = sum(present)
    boolean = values.take((nonnull + 7) // 8) if field['type'] == 'bool' else None
    result, ordinal = [], 0
    for exists in present:
        check()
        if not exists:
            result.append(None)
            continue
        if field['type'] == 'int8':
            value = struct.unpack('<q', values.take(8))[0]
        elif field['type'] == 'bool':
            value = bool((boolean[ordinal // 8] >> (ordinal % 8)) & 1)
        else:
            size = values.uint32()
            require(size <= 4 * 4096, 'parquet text exceeds certified bound', 'resource_limit')
            raw = values.take(size)
            try:
                value = raw.tobytes().decode('utf-8')
            except UnicodeError:
                require(False, 'invalid parquet text UTF8', 'corrupt_object')
            require(len(value) <= 4096, 'parquet text exceeds certified bound', 'resource_limit')
        result.append(value)
        ordinal += 1
    require(values.position == len(values.raw), 'unconsumed parquet page body', 'corrupt_object')
    return result


def decode_column(raw, plan, rows, scope):
    cursor, end = plan['offset'], plan['offset'] + plan['size']
    result, pages = [], 0
    while cursor < end:
        scope.check()
        require(len(result) < rows, 'extra parquet data page', 'corrupt_object')
        maximum = min(65536, end - cursor)
        with scope.reserve(min(4096, maximum) * 512 + 4096):
            header = Compact(memoryview(raw)[cursor:cursor + maximum], scope.check,
                             max_nodes=min(4096, maximum))
            value = header.struct()
            shape(value, {1: 5, 2: 5, 3: 5}, {4: 5, 5: 12, 6: 12, 7: 12, 8: 12})
            require(item(value, 1) == 0, 'only DataPageV1 is supported', 'unsupported_capability')
            shape(value, {1: 5, 2: 5, 3: 5, 5: 12}, {4: 5})
            size = item(value, 3)
            cursor += header.position
            require(0 < size == item(value, 2) <= end - cursor,
                    'invalid uncompressed parquet page size', 'corrupt_object')
            data_header = item(value, 5)
            shape(data_header, {1: 5, 2: 5, 3: 5, 4: 5}, {5: 12})
            require(5 not in data_header or item(data_header, 5) == {},
                    'nonempty page statistics are unsupported', 'unsupported_capability')
            count = item(data_header, 1)
            require(0 < count <= rows - len(result), 'page values exceed group rows', 'corrupt_object')
            require(item(data_header, 2) == 0 and item(data_header, 3) == item(data_header, 4) == 3,
                    'unsupported parquet page encoding', 'unsupported_capability')
            body = memoryview(raw)[cursor:cursor + size]
            if 4 in value:
                require(zlib.crc32(body) == item(value, 4) & 0xffffffff,
                        'parquet page checksum mismatch', 'corrupt_object')
            decoded = plain(body, plan['field'], count, scope.check)
            result.extend(decoded)
            cursor += size
            pages += 1
    require(cursor == end and len(result) == rows
            and (plan['pages'] is None or pages == plan['pages']),
            'incomplete parquet column coverage', 'corrupt_object')
    statistics = plan.get('size_statistics')
    if statistics is not None:
        nulls, text_bytes = 0, 0
        # PLAIN text validation bounds one temporary UTF8 encoding to16KiB.
        with scope.reserve(16384):
            for value in result:
                scope.check()
                if value is None:
                    nulls += 1
                elif 'text_bytes' in statistics:
                    text_bytes += len(value.encode('utf-8'))
        require(('null_count' not in statistics or statistics['null_count'] == nulls)
                and ('text_bytes' not in statistics or statistics['text_bytes'] == text_bytes),
                'parquet size statistics contradict decoded values', 'corrupt_object')
    return result


def decode_group(raw, plans, rows, scope):
    require(type(rows) is int and 0 < rows <= 1000 and 0 < len(plans) <= 32,
            'invalid certified parquet group')
    columns = [decode_column(raw, plan, rows, scope) for plan in plans]
    result = []
    for offset in range(rows):
        scope.check()
        result.append({plan['field']['source_field_id']: column[offset]
                       for plan, column in zip(plans, columns)})
    return result
