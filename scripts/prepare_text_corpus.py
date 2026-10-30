#!/usr/bin/env python3
"""Offline version-1 JSONL/local-material to fixed Parquet; no online scoring."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import wave
import io
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
BASE = {'doc_id', 'text'}
MEDIA = {'image_id', 'image_file'}
MEDIA2 = {'asset_id', 'asset_type', 'asset_file'}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def prepare(input_path, output_dir):
    if output_dir.is_absolute():
        raise ValueError('output must be a new relative artifacts directory')
    output = (ROOT / output_dir).resolve()
    if not output.is_relative_to(ROOT / 'artifacts') or output == ROOT / 'artifacts':
        raise ValueError('output must be inside repository artifacts')
    if output.exists() or (ROOT / output_dir).is_symlink():
        raise ValueError('output exists; nothing overwritten')
    source = input_path.resolve(strict=True)
    if not source.is_file() or source.stat().st_size > 1024 * 1024:
        raise ValueError('input must be a regular JSONL file at most 1 MiB')
    with source.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('JSONL exceeds 1 MiB')
    original = [json.loads(line, object_pairs_hook=unique_object) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if not 1 <= len(original) <= 200:
        raise ValueError('input needs 1..200 documents')
    rows, assets, seen = [], {}, set()
    text_bytes = total_tokens = 0
    first = set(original[0]) if type(original[0]) is dict else set()
    version = 2 if first == BASE | MEDIA2 else 1
    with_media = first in (BASE | MEDIA, BASE | MEDIA2)
    expected = BASE | (MEDIA2 if version == 2 else MEDIA) if with_media else BASE
    for item in original:
        if type(item) is not dict or set(item) != expected:
            raise ValueError('unknown fields or mixed text-only/image document layouts')
        key, text = item['doc_id'], item['text']
        if type(key) is not str or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', key) or key in seen:
            raise ValueError('invalid or duplicate doc_id')
        seen.add(key)
        if type(text) is not str or len(text) > 8192 or any(not (' ' <= c <= '~' or c in '\t\r\n') for c in text):
            raise ValueError('text requires at most 8192 printable ASCII bytes')
        tokens = re.findall(r'[A-Za-z0-9]+', text.lower())
        if not tokens or any(len(t) > 64 for t in tokens) or len(tokens) > 2048:
            raise ValueError('document token bounds exceeded or text has no words')
        text_bytes += len(text)
        total_tokens += len(tokens)
        if text_bytes > 256 * 1024 or total_tokens > 65536:
            raise ValueError('corpus text/token bounds exceeded')
        row = {'doc_id': key, 'text': text, 'text_version': 1}
        if with_media:
            image_id = item['asset_id' if version == 2 else 'image_id']
            locator = item['asset_file' if version == 2 else 'image_file']
            kind = item['asset_type'] if version == 2 else 'image/jpeg'
            if type(kind) is not str or kind not in {'image/jpeg', 'audio/wav', 'video/x-msvideo'}:
                raise ValueError('unsupported asset_type')
            if type(image_id) is not int or not 1 <= image_id <= 999999999999 or type(locator) is not str:
                raise ValueError('invalid image ID or local locator')
            relative = Path(locator)
            if relative.is_absolute() or not relative.parts or any(p in {'.', '..'} for p in relative.parts) or '\\' in locator:
                raise ValueError('image_file must be a root-relative local path without traversal')
            image_path = source.parent
            for part in relative.parts:
                image_path /= part
                if image_path.is_symlink():
                    raise ValueError('image symlinks are unsupported')
            if not image_path.resolve().is_relative_to(source.parent) or not image_path.is_file():
                raise ValueError('image is unavailable or outside input root')
            if image_id in assets:
                if assets[image_id]['source'] != str(image_path) or assets[image_id]['type'] != kind:
                    raise ValueError('image ID has conflicting source paths')
            else:
                extensions = {'image/jpeg': {'.jpg', '.jpeg'}, 'audio/wav': {'.wav'}, 'video/x-msvideo': {'.avi'}}
                if image_path.suffix.lower() not in extensions[kind]:
                    raise ValueError('asset filename does not match its supported media type')
                if len(assets) >= 3 or image_path.stat().st_size > 512 * 1024:
                    raise ValueError('at most three bounded 512 KiB media assets')
                with image_path.open('rb') as stream:
                    data = stream.read(512 * 1024 + 1)
                if kind == 'image/jpeg' and (not data.startswith(b'\xff\xd8\xff') or (version == 2 and not data.endswith(b'\xff\xd9'))):
                    raise ValueError('unsupported JPEG signature; no decoding performed')
                if kind == 'audio/wav':
                    if len(data) < 44 or data[:4] != b'RIFF' or data[8:16] != b'WAVEfmt ' or data[36:40] != b'data':
                        raise ValueError('unsupported WAV layout')
                    riff_size, fmt_size = struct.unpack_from('<I', data, 4)[0], struct.unpack_from('<I', data, 16)[0]
                    code, channels, rate, byte_rate, align, bits = struct.unpack_from('<HHIIHH', data, 20)
                    count = struct.unpack_from('<I', data, 40)[0]
                    if (riff_size != len(data) - 8 or fmt_size != 16 or code != 1 or channels not in {1, 2}
                            or rate != 44100 or bits != 16 or align != channels * 2 or byte_rate != rate * align
                            or not count or count % align or len(data) != 44 + count):
                        raise ValueError('unsupported PCM16 WAV contract')
                    with wave.open(io.BytesIO(data), 'rb') as reader:
                        if len(reader.readframes(reader.getnframes())) != count:
                            raise ValueError('incomplete PCM frames')
                if kind == 'video/x-msvideo':
                    if (len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'AVI '
                            or struct.unpack_from('<I', data, 4)[0] != len(data) - 8):
                        raise ValueError('unsupported bounded RIFF AVI bytes; Rust verifies frames and timing')
                if len(data) > 512 * 1024:
                    raise ValueError('media byte bounds exceeded')
                assets[image_id] = {'source': str(image_path), 'payload': data, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'type': kind,
                                    'path': (f'images/{image_id:012}.jpg' if kind == 'image/jpeg' else
                                             f'audio/{image_id:012}.wav' if kind == 'audio/wav' else
                                             f'videos/{image_id:012}.avi')}
            asset = assets[image_id]
            row.update(media_version=version, media_bytes=asset['bytes'], media_sha256=asset['sha256'])
            if version == 1:
                row.update(image_id=image_id, image_path=asset['path'])
            else:
                row.update(asset_id=image_id, asset_path=asset['path'], asset_type=kind)
        rows.append(row)
    fields = [('doc_id', pa.string()), ('text', pa.string()), ('text_version', pa.int64())]
    if with_media:
        fields += ([('image_id', pa.int64()), ('image_path', pa.string())] if version == 1 else
                   [('asset_id', pa.int64()), ('asset_path', pa.string()), ('asset_type', pa.string())])
        fields += [('media_version', pa.int64()), ('media_bytes', pa.int64()), ('media_sha256', pa.string())]
    output.mkdir(parents=True, exist_ok=False)
    try:
        for directory in {Path(a['path']).parent for a in assets.values()}:
            (output / directory).mkdir()
        for asset in assets.values():
            (output / asset['path']).write_bytes(asset['payload'])
        parquet = output / 'records.parquet'
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(fields)), parquet, compression='snappy')
        if parquet.stat().st_size > 1024 * 1024:
            raise ValueError('Parquet exceeds 1 MiB')
        digest = hashlib.sha256(parquet.read_bytes()).hexdigest()
        (output / 'config.json').write_text(json.dumps({'source': 'records.parquet', 'sha256': digest, 'timeout_ms': 5000}, indent=2) + '\n')
        provenance = {'text_contract_version': 1, 'input_jsonl': str(source), 'input_bytes': len(raw),
                      'input_sha256': hashlib.sha256(raw).hexdigest(), 'documents': len(rows),
                      'text_bytes': text_bytes, 'tokens': total_tokens, 'parquet_sha256': digest,
                      'parquet_bytes': parquet.stat().st_size,
                      'assets': {str(key): {k: v for k, v in value.items() if k != 'payload'} for key, value in assets.items()},
                      'attribution': 'caller supplies and retains source attribution/rights; no rights or decode certification',
                      'scope': ('offline captured bytes; no keyword labels/ranking/download/transcoding/image-or-model decoding; PCM16 framing read and validated; AVI signature/length only, Rust owns frame/index/timing validation' if version == 2 else 'offline captured bytes; no keyword labels or ranking; no download or decoding')}
        (output / 'source.json').write_text(json.dumps(provenance, indent=2) + '\n')
    except BaseException:
        shutil.rmtree(output)
        raise
    return {'output_dir': output.relative_to(ROOT).as_posix(), 'documents': len(rows), 'assets': len(assets), 'sha256': digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.input, args.output_dir)))
    except Exception as error:
        parser.exit(1, f'error: {error}\n')


if __name__ == '__main__':
    main()
