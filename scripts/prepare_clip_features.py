#!/usr/bin/env python3
"""Offline fixed OpenCLIP feature preparation; never part of Rust serving."""
import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

MODEL = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
REVISION = '1a25a446712ba5ee05982a381eed697ef9b435cf'
FILES = {
    'open_clip_model.safetensors': (605143316, 'ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6'),
    'open_clip_config.json': (604, '4302a891b495ad0966d1e7eeff102b5f34a3f1e647e57a9198933f862d5f8ba7'),
    'README.md': (7464, 'd0600101ba66849bd84eeae14e0b1ccd56cd962ea94aec5d60c415d9ce4e5f28'),
}
ROOT = Path(__file__).resolve().parents[1]
RSS_LIMIT = 4 * 1024**3
TIME_LIMIT = 600


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def read_json(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('JSON byte bound exceeded')
    return json.loads(raw, object_pairs_hook=unique_object)


def validate_model(directory):
    for name, (size, sha) in FILES.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size or digest(path) != sha:
            raise ValueError('fixed official model/config/card identity differs')
    return read_json(directory / 'open_clip_config.json', 16384)


def queries(path):
    value = read_json(path, 65536)
    if type(value) is not dict or set(value) != {'format_version', 'queries'} or type(value['format_version']) is not int or value['format_version'] != 1:
        raise ValueError('unsupported query-list format')
    rows = value['queries']
    if type(rows) is not list or not 1 <= len(rows) <= 8:
        raise ValueError('query list needs 1..8 entries')
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != {'id', 'text'}:
            raise ValueError('query list accepts only id/text')
        key, text = row['id'], row['text']
        if type(key) is not str or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', key) or key in seen:
            raise ValueError('invalid/duplicate query ID')
        seen.add(key)
        words = re.findall(r'[A-Za-z0-9]+', text) if type(text) is str else []
        if type(text) is not str or not text.isascii() or len(text) > 256 or not 1 <= len(words) <= 8 or any(len(word) > 64 for word in words) or any(ord(c) < 32 or ord(c) > 126 for c in text):
            raise ValueError('query requires 1..8 bounded printable ASCII words')
    return rows


def corpus(config):
    import pyarrow as pa
    import pyarrow.parquet as pq
    cfg = read_json(config, 16384)
    if type(cfg) is not dict or set(cfg) != {'source', 'sha256', 'timeout_ms'} or type(cfg['source']) is not str or type(cfg['sha256']) is not str or not re.fullmatch(r'[a-f0-9]{64}', cfg['sha256']):
        raise ValueError('unsupported fixed corpus config')
    if Path(cfg['source']).name != cfg['source'] or not cfg['source'].endswith('.parquet') or type(cfg['timeout_ms']) is not int or not 1 <= cfg['timeout_ms'] <= 10000:
        raise ValueError('invalid local source name or query timeout')
    source = config.parent / cfg['source']
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 1024**2:
        raise ValueError('source unavailable or exceeds 1 MiB offline bound')
    raw = source.read_bytes()
    if len(raw) > 1024**2 or hashlib.sha256(raw).hexdigest() != cfg['sha256']:
        raise ValueError('fixed corpus SHA differs')
    parquet = pq.ParquetFile(pa.BufferReader(raw))
    md = parquet.metadata
    if not 1 <= md.num_rows <= 200 or sum(md.row_group(i).column(j).total_uncompressed_size for i in range(md.num_row_groups) for j in range(md.num_columns)) > 64 * 1024**2:
        raise ValueError('corpus row/decode bound exceeded')
    expected = pa.schema([('doc_id', pa.string()), ('text', pa.string()), ('text_version', pa.int64()),
                          ('image_id', pa.int64()), ('image_path', pa.string()), ('media_version', pa.int64()),
                          ('media_bytes', pa.int64()), ('media_sha256', pa.string())])
    if not parquet.schema_arrow.equals(expected):
        raise ValueError('export requires generic text-version-1 media corpus')
    rows = parquet.read(use_threads=False).to_pylist()
    assets, seen, text_bytes, tokens = {}, set(), 0, 0
    for row in rows:
        key, text = row['doc_id'], row['text']
        if type(key) is not str or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', key) or key in seen or type(text) is not str or len(text) > 8192 or not text.isascii() or row['text_version'] != 1 or row['media_version'] != 1:
            raise ValueError('invalid text/media document')
        seen.add(key)
        words = re.findall(r'[A-Za-z0-9]+', text)
        text_bytes += len(text)
        tokens += len(words)
        if not words or any(len(word) > 64 for word in words) or len(words) > 2048 or text_bytes > 256 * 1024 or tokens > 65536 or any(ord(c) < 32 and c not in '\t\r\n' or ord(c) > 126 for c in text):
            raise ValueError('text/token contract bound exceeded')
        image_id, locator = row['image_id'], row['image_path']
        if type(image_id) is not int or not 1 <= image_id <= 999999999999 or type(locator) is not str:
            raise ValueError('invalid asset identity')
        if locator != f'images/{image_id:012}.jpg':
            raise ValueError('media-v1 requires exact images/{image_id:012}.jpg locator')
        relative = Path(locator)
        if relative.is_absolute() or not relative.parts or any(p in ('.', '..') for p in relative.parts) or '\\' in locator:
            raise ValueError('invalid media locator')
        path = config.parent
        for part in relative.parts:
            path /= part
            if path.is_symlink():
                raise ValueError('media symlink unsupported')
        identity = {k: row[k] for k in ('image_id', 'image_path', 'media_version', 'media_bytes', 'media_sha256')}
        if image_id in assets:
            if assets[image_id]['identity'] != identity:
                raise ValueError('conflicting asset identity')
            continue
        if len(assets) == 3 or not path.is_file() or not 1 <= row['media_bytes'] <= 512 * 1024 or path.stat().st_size != row['media_bytes']:
            raise ValueError('media asset/file bound differs')
        payload = path.read_bytes()
        if len(payload) != row['media_bytes'] or hashlib.sha256(payload).hexdigest() != row['media_sha256'] or not payload.startswith(b'\xff\xd8\xff'):
            raise ValueError('media bytes/SHA differs')
        assets[image_id] = {'identity': identity, 'path': path, 'payload': payload}
    return cfg, source, rows, assets


def environment():
    lock = ROOT / 'requirements-clip-macos-arm64.lock'
    versions = {}
    for line in lock.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})', line)
        if not match or importlib.metadata.version(match[1]) != match[2]:
            raise ValueError('offline environment differs from pinned wheel versions')
        versions[match[1]] = {'version': match[2], 'wheel_sha256': match[3]}
    if sys.version_info[:2] != (3, 12) or platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('this locked offline recipe supports macOS arm64 CPython 3.12 only')
    return versions, digest(lock)


def export_worker(config, model_dir, query_list, output):
    start = time.monotonic()
    versions, lock_sha = environment()
    cfg_model = validate_model(model_dir)
    query_sha = digest(query_list)
    query_rows = queries(query_list)
    config_sha = digest(config)
    cfg, source, docs, assets = corpus(config)
    import torch
    import open_clip
    from PIL import Image
    from safetensors.torch import load_file
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    Image.MAX_IMAGE_PIXELS = 4_000_000
    model = open_clip.model.CLIP(**cfg_model['model_cfg'])
    model.load_state_dict(load_file(str(model_dir / 'open_clip_model.safetensors'), device='cpu'), strict=True)
    model.float().eval()
    transform = open_clip.transform.image_transform(224, is_train=False, mean=cfg_model['preprocess_cfg']['mean'],
                                                  std=cfg_model['preprocess_cfg']['std'], interpolation='bicubic', resize_mode='shortest')
    tokenizer = open_clip.tokenizer.SimpleTokenizer(context_length=77)
    package = Path(open_clip.__file__).parent
    code = {str(p.relative_to(package)): digest(p) for p in sorted(package.rglob('*.py'))}
    bpe_sha = digest(Path(open_clip.tokenizer.default_bpe()))
    recipe = {'image_size': 224, 'resize': 'shortest-bicubic', 'crop': 'center', 'convert': 'RGB',
              'mean': cfg_model['preprocess_cfg']['mean'], 'std': cfg_model['preprocess_cfg']['std'],
              'tokenizer': 'OpenCLIP SimpleTokenizer/lower/context77', 'tokenizer_bpe_sha256': bpe_sha,
              'code_sha256': hashlib.sha256(json.dumps(code, sort_keys=True).encode()).hexdigest(),
              'preparation_script_sha256': digest(Path(__file__)),
              'environment_lock_sha256': lock_sha, 'compute': 'CPU fp32 eval inference_mode; raw projected f32 cast to f64; Rust normalizes'}
    recipe_sha = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    space = {'id': 'clip-laion2b-image-1a25a446-v1', 'dimensions': 512, 'dtype': 'f64', 'metric': 'cosine',
             'normalization': 'l2-scaled-f64-v1', 'origin': 'external-declared', 'model_id': MODEL,
             'model_revision': REVISION, 'preprocessing_id': 'sha256:' + recipe_sha,
             'license': 'MIT model-card label; original data rights separate'}
    images = []
    ids = sorted(assets)
    for key in ids:
        with Image.open(io.BytesIO(assets[key]['payload'])) as image:
            if image.format != 'JPEG' or image.width * image.height > 4_000_000:
                raise ValueError('unsupported/bounded JPEG pixels')
            images.append(transform(image))
    with torch.inference_mode():
        image_vectors = model.encode_image(torch.stack(images)).double().tolist()
        text_vectors = model.encode_text(tokenizer([row['text'] for row in query_rows])).double().tolist()
    for vector in image_vectors + text_vectors:
        if len(vector) != 512 or not all(math.isfinite(v) for v in vector) or not any(v != 0 for v in vector):
            raise ValueError('encoder produced invalid vector')
    validate_model(model_dir)
    if digest(config) != config_sha or digest(query_list) != query_sha or digest(source) != cfg['sha256'] or any(digest(a['path']) != a['identity']['media_sha256'] for a in assets.values()):
        raise ValueError('corpus/media changed before publication')
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if rss > RSS_LIMIT or time.monotonic() - start > TIME_LIMIT:
        raise ValueError('inference RSS/time bound exceeded')
    by_id = dict(zip(ids, image_vectors))
    features = output / 'features.jsonl'
    with features.open('x') as stream:
        stream.write(json.dumps({'format_version': 1, 'source_sha256': cfg['sha256'], 'documents': len(docs), 'space': space}) + '\n')
        for doc in docs:
            stream.write(json.dumps({'doc_id': doc['doc_id'], 'vector': by_id[doc['image_id']]}) + '\n')
    (output / 'queries').mkdir()
    emitted = []
    for row, vector in zip(query_rows, text_vectors):
        path = output / 'queries' / (row['id'] + '.json')
        path.write_text(json.dumps({'format_version': 1, 'source_sha256': cfg['sha256'], 'space': space, 'vector': vector}) + '\n')
        emitted.append({**row, 'file': str(path.relative_to(output)), 'sha256': digest(path)})
    manifest = {'model': MODEL, 'revision': REVISION, 'model_files': {n: {'bytes': sz, 'sha256': h} for n, (sz, h) in FILES.items()},
                'space': space, 'recipe': recipe, 'open_clip_python_files': code, 'packages': versions,
                'source_sha256': cfg['sha256'], 'documents': len(docs), 'document_representation': 'image vector reused per asset, each caption retains distinct DocID',
                'assets': [assets[key]['identity'] for key in ids], 'doc_assets': {d['doc_id']: d['image_id'] for d in docs},
                'features_file': 'features.jsonl', 'features_sha256': digest(features), 'query_input_sha256': query_sha, 'config_sha256': config_sha, 'queries': emitted,
                'observed': {'seconds': time.monotonic() - start, 'rss_bytes': rss, 'torch_threads': torch.get_num_threads(), 'interop_threads': torch.get_num_interop_threads()},
                'runtime': {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(), 'device': 'cpu', 'precision': 'fp32'},
                'scope': 'actual fixed model features; frozen small-domain observations separately; no generalization or model/data rights certification'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return {'output_dir': str(output), 'documents': len(docs), 'assets': len(ids), 'queries': len(query_rows),
            'features_sha256': manifest['features_sha256'], 'observed': manifest['observed']}


def export(config, model_dir, query_list, output_dir):
    output = (ROOT / output_dir).resolve()
    if output_dir.is_absolute() or not output.is_relative_to(ROOT / 'artifacts') or output == ROOT / 'artifacts' or (ROOT / output_dir).is_symlink():
        raise ValueError('output must be a new relative repository artifacts directory')
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(Path(__file__).resolve()), '_worker', '--config', str(config.resolve()),
               '--model-dir', str(model_dir.resolve()), '--queries', str(query_list.resolve()), '--output-dir', str(output)]
    env = {**os.environ, 'OMP_NUM_THREADS': '4', 'OPENBLAS_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4',
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'TOKENIZERS_PARALLELISM': 'false',
           'GURADB_CLIP_PARENT': str(os.getpid())}
    start, peak, process = time.monotonic(), 0, None
    try:
        with tempfile.TemporaryFile() as logs:
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=logs, stderr=logs, start_new_session=True)
            while process.poll() is None:
                value = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(process.pid)], capture_output=True, text=True, check=False).stdout.strip()
                if value.isdigit():
                    peak = max(peak, int(value) * 1024)
                if peak > RSS_LIMIT or time.monotonic() - start > TIME_LIMIT:
                    raise ValueError('export worker RSS/time limit exceeded')
                time.sleep(0.25)
            logs.seek(0)
            raw = logs.read(1024 * 1024 + 1)
            if process.returncode or len(raw) > 1024 * 1024:
                raise ValueError('offline export failed: ' + raw[:8192].decode('utf-8', 'replace'))
        manifest = read_json(output / 'manifest.json', 1024 * 1024)
        manifest['watchdog'] = {'sampled_peak_rss_bytes': peak, 'elapsed_seconds': time.monotonic() - start, 'pid': process.pid,
                                'poll_seconds': 0.25, 'limit_rss_bytes': RSS_LIMIT, 'limit_seconds': TIME_LIMIT}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return {'output_dir': output.relative_to(ROOT).as_posix(), 'features_sha256': manifest['features_sha256'],
                'documents': manifest['documents'], 'queries': len(manifest['queries']), 'observed': manifest['observed'], 'watchdog': manifest['watchdog']}
    except BaseException:
        try:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # Child exited after poll; wait still reaps it.
                process.wait()
        finally:
            shutil.rmtree(output)
        raise


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def download(directory):
    if directory.exists() or directory.is_symlink():
        raise ValueError('cache exists; nothing overwritten; use existing verified cache')
    directory.mkdir(parents=True)
    start = time.monotonic()
    records = []
    try:
        for name, (size, sha) in FILES.items():
            url = f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}'
            target = directory / name
            received = 0
            with urllib.request.urlopen(url, timeout=30) as response, target.open('xb') as out:
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != size:
                    raise ValueError('remote size differs from pinned source')
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > size or time.monotonic() - start > 600:
                        raise ValueError('download byte/time budget exceeded')
                    out.write(chunk)
                    if received % (64 * 1024 * 1024) == 0:
                        print(json.dumps({'file': name, 'received': received}), flush=True)
            if received != size or digest(target) != sha:
                raise ValueError('download differs from pinned size/SHA256')
            records.append({'file': name, 'bytes': received, 'sha256': sha, 'source': url})
        manifest = {'model': MODEL, 'revision': REVISION, 'files': records,
                    'payload_bytes': sum(row['bytes'] for row in records),
                    'elapsed_seconds': time.monotonic() - start,
                    'scope': 'fixed official safetensors only; model card research/English/domain limits apply'}
        (directory / 'download.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return manifest
    except BaseException:
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()
        raise


def main():
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('download')
    fetch.add_argument('--model-dir', type=Path, required=True)
    for name in ('export', '_worker'):
        item = sub.add_parser(name)
        item.add_argument('--config', type=Path, required=True)
        item.add_argument('--model-dir', type=Path, required=True)
        item.add_argument('--queries', type=Path, required=True)
        item.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'download':
            result = download(args.model_dir)
        elif args.command == 'export':
            result = export(args.config, args.model_dir, args.queries, args.output_dir)
        else:
            if os.environ.get('GURADB_CLIP_PARENT') != str(os.getppid()):
                raise ValueError('internal worker requires the monitored export parent')
            result = export_worker(args.config, args.model_dir, args.queries, args.output_dir)
        print(json.dumps(result))
    except Exception as error:
        parser.exit(1, f'error: {error}\n')


if __name__ == '__main__':
    main()
