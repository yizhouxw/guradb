#!/usr/bin/env python3
"""Bounded offline normalization and range description; no online query answers."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import stat
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq

LIMIT = 32 << 20
DECODE = 64 << 20


def digest(data):
    return hashlib.sha256(data).hexdigest()


def indices(value, maximum, count):
    values = [int(x) for x in value.split(',')]
    if not 1 <= len(values) <= count or values != sorted(set(values)) or not all(0 <= n < maximum for n in values):
        raise ValueError('selection must contain unique ascending bounded indices')
    return values


def prepare(args):
    started = time.monotonic()
    sql_source = getattr(args, 'sql_source', False)
    if sql_source and (args.columns is not None or args.row_groups is not None):
        raise ValueError('SQL source describes all rows; physical selection flags are incompatible')
    source = Path(args.input)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= LIMIT:
            raise ValueError('input must be a regular non-linked file <=32MiB')
        raw = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if len(raw) > LIMIT or any(getattr(before, k) != getattr(after, k) for k in fields):
        raise ValueError('input changed during preparation')
    file = pq.ParquetFile(pa.BufferReader(raw))
    metadata = file.metadata
    schema = file.schema_arrow
    if not 1 <= metadata.num_rows <= 200 or not 1 <= len(schema) <= 8:
        raise ValueError('whole input must have 1..200 rows and 1..8 columns')
    if len(set(schema.names)) != len(schema.names) or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', n) for n in schema.names):
        raise ValueError('column names must be unique bounded ASCII identifiers')
    if any(f.type not in (pa.int64(), pa.string(), pa.bool_()) for f in schema):
        raise ValueError('offline input supports only int64/string/bool columns')
    declared = sum(metadata.row_group(g).column(c).total_uncompressed_size for g in range(metadata.num_row_groups) for c in range(metadata.num_columns))
    if not 0 <= declared <= DECODE:
        raise ValueError('declared full offline decode exceeds64MiB')
    table = file.read()
    if table.nbytes > DECODE or table.num_rows != metadata.num_rows:
        raise ValueError('offline table exceeds64MiB or differs from metadata')
    clean = pa.schema([pa.field(f.name, f.type, f.nullable) for f in schema])
    table = table.cast(clean).replace_schema_metadata(None)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression='NONE', use_dictionary=False,
                   data_page_version='1.0', version='1.0', store_schema=False,
                   write_page_index=False, row_group_size=max(1, math.ceil(table.num_rows / 3)))
    data = sink.getvalue().to_pybytes()
    if len(data) > 4 << 20 or not data.startswith(b'PAR1') or not data.endswith(b'PAR1'):
        raise ValueError('normalized bundle object exceeds4MiB or has bad magic')
    normalized = pq.ParquetFile(pa.BufferReader(data)).metadata
    footer_length = int.from_bytes(data[-8:-4], 'little') + 8
    footer_offset = len(data) - footer_length
    def region(offset, length):
        if offset < 0 or length < 1 or offset + length > len(data):
            raise ValueError('invalid descriptor range')
        return dict(offset=offset, length=length, sha256=digest(data[offset:offset+length]))
    chunks = []
    for g in range(normalized.num_row_groups):
        for c in range(normalized.num_columns):
            column = normalized.row_group(g).column(c)
            if column.dictionary_page_offset is not None or column.compression != 'UNCOMPRESSED':
                raise ValueError('unexpected normalized encoding')
            chunk = region(column.data_page_offset, column.total_compressed_size)
            if chunk['offset'] + chunk['length'] > footer_offset:
                raise ValueError('column chunk crosses footer')
            chunks.append(dict(row_group=g, column=c, **chunk))
    columns = [] if sql_source else indices(args.columns or '0,2', normalized.num_columns, 3)
    groups = [] if sql_source else indices(args.row_groups or '0,2', normalized.num_row_groups, 2)
    selected = [c for c in chunks if c['row_group'] in groups and c['column'] in columns]
    payload = 4 + footer_length + sum(c['length'] for c in selected)
    if 2 + len(selected) > 8 or payload > 512 << 10:
        raise ValueError('selected composite ranges exceed operation budget')
    # Reuse the engineering identity whitelist, not a separate HTTP authority.
    import importlib.util
    spec = importlib.util.spec_from_file_location('range_fixture', Path(__file__).with_name('local_http_fixture.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not module.valid_key(args.key) or not module.valid_etag(args.etag) or not re.fullmatch(r'http://127\.0\.0\.1:([1-9][0-9]{3,4})', args.origin):
        raise ValueError('invalid local HTTP identity')
    port = int(args.origin.rsplit(':', 1)[1])
    if not 1024 <= port <= 65535:
        raise ValueError('invalid local HTTP port')
    request = dict(version=1, origin=args.origin, object_key=args.key, etag=args.etag,
                   object_bytes=len(data), source_sha256_provenance=digest(data),
                   header=region(0, 4), footer=region(footer_offset, footer_length),
                   chunks=chunks, columns=columns, row_groups=groups)
    if sql_source:
        del request['columns'], request['row_groups']
    encoded = (json.dumps(request, indent=2) + '\n').encode()
    if len(encoded) > 16384:
        raise ValueError('request descriptor exceeds16KiB')
    out = Path(args.out)
    if out.exists() or out.is_symlink():
        raise ValueError('output must be a new directory; refusing overwrite')
    if '..' in out.parts:
        raise ValueError('output parent traversal is unsupported')
    absolute = out if out.is_absolute() else Path.cwd() / out
    parent = Path(absolute.anchor)
    for part in absolute.parent.parts[1:]:
        parent = parent / part
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError('output parent must be an existing non-linked directory chain')
    out = parent / absolute.name
    if out.name in ('', '.', '..'):
        raise ValueError('invalid output directory')
    cost = dict(input_name=source.name, input_full_bytes=len(raw), input_full_sha256=digest(raw),
                input_full_rows=table.num_rows, offline_declared_decode_bytes=declared,
                offline_table_bytes=table.nbytes, normalized_bytes=len(data),
                normalized_full_sha256_provenance=digest(data), normalized_row_groups=normalized.num_row_groups,
                planned_consumer_GETs=None if sql_source else 2+len(selected),
                planned_consumer_payload_bytes=None if sql_source else payload,
                current_full_object_revalidation=False,
                license='Input rights/attribution remain caller responsibility; COCO reference captions retain source attribution separately from images.',
                authority='Trusted offline whole read and normalization; descriptor is not a signature or database result cache.',
                seconds=time.monotonic()-started,
                rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024))
    if cost['seconds'] > 10:
        raise ValueError('offline preparation exceeds10s work budget')
    out.mkdir()
    try:
        (out/'data.parquet').write_bytes(data)
        (out/('sql-source.json' if sql_source else 'request.json')).write_bytes(encoded)
        (out/'SOURCE.json').write_text(json.dumps(cost, indent=2)+'\n')
        shutil.copyfile(Path(__file__).with_name('local_http_fixture.py'), out/'local_http_fixture.py')
    except BaseException:
        for p in out.iterdir():
            p.unlink()
        out.rmdir()
        raise
    return cost


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--origin', default='http://127.0.0.1:38081')
    parser.add_argument('--key', default='caption/v1/records.parquet')
    parser.add_argument('--etag', default='"caption15-fixed-v1"')
    parser.add_argument('--columns')
    parser.add_argument('--row-groups')
    parser.add_argument('--sql-source', action='store_true',
                        help='complete SQL source descriptor, incompatible with physical selections')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args), indent=2))
    except (ValueError, OSError, pa.ArrowException) as error:
        print(json.dumps(dict(error=str(error))), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
