#!/usr/bin/env python3
"""Offline one-image COCO caption preparation and actual macOS ImageIO decode."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
from prepare_coco_metadata import ROOT, MEMBER, MEMBER_SHA256, MAX_MEMBER_BYTES

IMAGE_ID = 397133
FILE_NAME = '000000397133.jpg'
IMAGE_SHA256 = '09e1d25c75f7879bdaa69c327fece5cabacd53939c8c2ef9e87f1c97a2e478c4'


def read_member(path, name, limit):
    with zipfile.ZipFile(path, 'r') as archive:
        info = archive.getinfo(name)
        if info.file_size > limit:
            raise ValueError('source member exceeds byte budget')
        with archive.open(info, 'r') as stream:
            data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('source member exceeds byte budget')
    return data


def prepare(annotations_zip, images_zip, output_dir):
    if output_dir.is_absolute():
        raise ValueError('output directory must be a new relative artifacts path')
    output = (ROOT / output_dir).resolve()
    if not output.is_relative_to(ROOT / 'artifacts') or output == ROOT / 'artifacts':
        raise ValueError('output directory must be inside repository artifacts')
    if output.exists() or (ROOT / output_dir).is_symlink():
        raise ValueError('output path already exists; nothing overwritten')
    if not Path('/usr/bin/sips').is_file():
        raise ValueError('macOS /usr/bin/sips is required for actual image decoding')
    annotations = annotations_zip.resolve(strict=True)
    images = images_zip.resolve(strict=True)
    raw = read_member(annotations, MEMBER, MAX_MEMBER_BYTES)
    if hashlib.sha256(raw).hexdigest() != MEMBER_SHA256:
        raise ValueError('unsupported annotations member SHA256')
    document = json.loads(raw)
    image = next(row for row in document['images'] if row['id'] == IMAGE_ID)
    if image['file_name'] != FILE_NAME:
        raise ValueError('image ID/file name association differs')
    captions = sorted((row for row in document['annotations'] if row['image_id'] == IMAGE_ID), key=lambda r: r['id'])
    if len(captions) != 5 or len({r['id'] for r in captions}) != 5:
        raise ValueError('expected five distinct source captions for the image')
    image_member = 'val2017/' + FILE_NAME
    jpeg = read_member(images, image_member, 16 * 1024 * 1024)
    if hashlib.sha256(jpeg).hexdigest() != IMAGE_SHA256:
        raise ValueError('image member SHA256/association differs; damaged or unsupported image')
    rows = [dict(image_id=row['image_id'], caption_id=row['id'], caption=row['caption'],
                 file_name=FILE_NAME, image_path='images/' + FILE_NAME,
                 width=image['width'], height=image['height']) for row in captions]
    schema = pa.schema([('image_id', pa.int64()), ('caption_id', pa.int64()), ('caption', pa.string()),
                        ('file_name', pa.string()), ('image_path', pa.string()),
                        ('width', pa.int64()), ('height', pa.int64())])
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output / 'images').mkdir()
        local_image = output / 'images' / FILE_NAME
        local_image.write_bytes(jpeg)
        decoded = output / 'decoded.png'
        result = subprocess.run(['/usr/bin/sips', '-s', 'format', 'png', str(local_image), '--out', str(decoded)],
                                capture_output=True, timeout=20)
        if result.returncode != 0 or not decoded.is_file():
            raise ValueError('image decode failed')
        png = decoded.read_bytes()
        if png[:8] != b'\x89PNG\r\n\x1a\n' or len(png) < 24:
            raise ValueError('image decoder did not produce PNG pixels')
        width, height = struct.unpack('>II', png[16:24])
        if (width, height) != (image['width'], image['height']):
            raise ValueError('decoded image dimensions differ from annotations')
        decoded.unlink()
        parquet = output / 'records.parquet'
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), parquet, compression='snappy')
        if parquet.stat().st_size > 1024 * 1024:
            raise ValueError('prepared Parquet exceeds 1 MiB')
        digest = hashlib.sha256(parquet.read_bytes()).hexdigest()
        (output / 'config.json').write_text(json.dumps({'source': parquet.name, 'sha256': digest, 'timeout_ms': 5000}, indent=2) + '\n')
        license_row = next(row for row in document['licenses'] if row['id'] == image['license'])
        (output / 'source.json').write_text(json.dumps({
            'annotations_zip': str(annotations), 'annotations_member': MEMBER, 'annotations_sha256': MEMBER_SHA256,
            'images_zip': str(images), 'image_member': image_member, 'image_sha256': IMAGE_SHA256,
            'image_id': IMAGE_ID, 'rows': len(rows), 'caption_ids': [r['id'] for r in captions],
            'image_bytes': len(jpeg), 'image_path_relative_to_config': 'images/' + FILE_NAME,
            'decoded': {'tool': '/usr/bin/sips (macOS ImageIO)', 'format': 'PNG', 'width': width, 'height': height, 'temporary_png_removed': True},
            'parquet_sha256': digest, 'parquet_bytes': parquet.stat().st_size,
            'caption_attribution': 'COCO Consortium; annotations CC BY 4.0; subset and scalar projection',
            'caption_license_url': 'https://creativecommons.org/licenses/by/4.0/',
            'image_license_from_source_metadata': license_row, 'image_flickr_source': image['flickr_url'],
            'photographer_name': 'UNKNOWN; not provided by COCO metadata',
            'image_changes': 'JPEG bytes unchanged; temporary offline PNG decode only',
            'scope': 'one exact image and five source captions; no visual recognition, keyword precomputation, full archive or current photo rights certification',
        }, indent=2) + '\n')
    except BaseException:
        shutil.rmtree(output)
        raise
    return {'output_dir': output.relative_to(ROOT).as_posix(), 'image_id': IMAGE_ID, 'rows': len(rows), 'sha256': digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations-zip', type=Path, required=True)
    parser.add_argument('--images-zip', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.annotations_zip, args.images_zip, args.output_dir)))
    except Exception as error:
        parser.exit(1, f'error: {error}\n')


if __name__ == '__main__':
    main()
