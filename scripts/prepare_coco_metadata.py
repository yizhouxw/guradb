#!/usr/bin/env python3
"""Prepare one fixed COCO2017 metadata subset offline; never run the query engine."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
MEMBER = 'annotations/captions_val2017.json'
MEMBER_SHA256 = 'afe3b30e403dd7f228e2373023abbd60042a6e10ec6874d3652df034d289ebb9'
MAX_MEMBER_BYTES = 4 * 1024 * 1024


def prepare(source_zip, output_dir):
    if output_dir.is_absolute():
        raise ValueError('output directory must be a relative path inside repository artifacts')
    output = (ROOT / output_dir).resolve()
    if not output.is_relative_to(ROOT / 'artifacts') or output == ROOT / 'artifacts':
        raise ValueError('output directory must be inside repository artifacts')
    if output.exists() or (ROOT / output_dir).is_symlink():
        raise ValueError('output path already exists; choose a new directory; nothing overwritten')
    source = source_zip.resolve(strict=True)
    if not source.is_file():
        raise ValueError('source ZIP must be an existing file')
    # Only this bounded annotations member is read, never any photograph file.
    with zipfile.ZipFile(source, 'r') as archive:
        info = archive.getinfo(MEMBER)
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError('annotations member exceeds 4 MiB')
        with archive.open(info, 'r') as member:
            raw = member.read(MAX_MEMBER_BYTES + 1)
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > MAX_MEMBER_BYTES or digest != MEMBER_SHA256:
        raise ValueError('unsupported annotations member SHA256; fixed COCO2017 input required')
    document = json.loads(raw)
    rows = [dict(image_id=row['id'], file_name=row['file_name'], width=row['width'],
                 height=row['height'], image_license_id=row['license'], source_ordinal=i,
                 is_landscape=row['width'] > row['height'])
            for i, row in enumerate(document['images'][:32])]
    if len(rows) != 32:
        raise ValueError('fixed sample must contain 32 image descriptors')
    schema = pa.schema([('image_id', pa.int64()), ('file_name', pa.string()),
                        ('width', pa.int64()), ('height', pa.int64()),
                        ('image_license_id', pa.int64()), ('source_ordinal', pa.int64()),
                        ('is_landscape', pa.bool_())])
    output.mkdir(parents=True, exist_ok=False)
    parquet = output / 'records.parquet'
    config = output / 'config.json'
    provenance = output / 'source.json'
    try:
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), parquet, compression='snappy')
        if parquet.stat().st_size > 1024 * 1024:
            raise ValueError('prepared sample exceeds 1 MiB')
        sha = hashlib.sha256(parquet.read_bytes()).hexdigest()
        config.write_text(json.dumps({'source': parquet.name, 'sha256': sha, 'timeout_ms': 5000}, indent=2) + '\n')
        provenance.write_text(json.dumps({
            'source_zip': str(source), 'member': MEMBER, 'member_bytes': len(raw),
            'member_sha256': digest, 'whole_archive_sha256': 'not measured',
            'selection': 'original images array first 32 entries', 'rows': len(rows),
            'mapping': 'id/file_name/width/height/license -> image_id/file_name/width/height/image_license_id; source_ordinal = original array position; is_landscape = width > height',
            'parquet_sha256': sha, 'parquet_bytes': parquet.stat().st_size,
            'attribution': 'COCO Consortium, COCO 2017 Dataset v1.0 (2017/09/01)',
            'changes': 'metadata subset, scalar projection and derived Boolean; no image files opened; parsed caption fields not selected or copied',
            'license': 'annotations/website CC BY 4.0; image rights separate',
            'license_url': 'https://creativecommons.org/licenses/by/4.0/',
            'terms_url': 'https://github.com/cocodataset/cocodataset.github.io/blob/master/dataset/termsofuse.htm',
        }, indent=2) + '\n')
    except BaseException:
        # Only files in the exclusively created output directory belong to this call.
        for path in (parquet, config, provenance):
            path.unlink(missing_ok=True)
        output.rmdir()
        raise
    return {'output_dir': output.relative_to(ROOT).as_posix(), 'rows': len(rows), 'sha256': sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.source_zip, args.output_dir)
    except Exception as error:
        parser.exit(1, f'error: {error}\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
