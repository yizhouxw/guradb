#!/usr/bin/env python3
"""Actual external PyTorch reader of Rust-owned fixed members; no model/training."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RSS_LIMIT = 4 * 1024**3
READER_SECONDS = 120
MEDIA_BYTES_LIMIT = 32 * 1024**2


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RustCLI:
    def __init__(self, config, selection, view_store=None, view=None, binary=None, runtime_image=None):
        self.selection = selection.resolve(strict=True)
        self.binary = (binary if binary is not None else ROOT/'target/debug/guradb').resolve(strict=True)
        if (binary is None) != (runtime_image is None):
            raise ValueError('explicit binary and fixed runtime-image must be provided together')
        if runtime_image is not None and (not runtime_image.startswith('sha256:') or len(runtime_image)!=71 or any(c not in '0123456789abcdef' for c in runtime_image[7:])):
            raise ValueError('runtime-image requires an exact existing image ID')
        self.view_store = view_store.resolve(strict=True) if view_store else None
        self.config = config.resolve(strict=True) if config else None
        if self.view_store:
            if not self.view_store.is_dir() or self.config is not None:
                raise ValueError('view transport requires one existing store directory')
            self.requested_view = view or 'current'
            if self.requested_view != 'current' and (len(self.requested_view) != 64 or any(c not in '0123456789abcdef' for c in self.requested_view)):
                raise ValueError('view must be current or an exact lowercase ID')
        elif self.config is None or not self.config.is_file() or self.config.stat().st_size > 16384 or view is not None:
            raise ValueError('transport requires one existing bounded config')
        if not self.selection.is_file() or self.selection.stat().st_size > 65536 or not self.binary.is_file():
            raise ValueError('transport requires existing bounded regular selection/binary files')
        self.view_id, self.source_sha256 = None, None
        self.image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', runtime_image or 'guradb-rust:1.90.0'], timeout=10))[0]['Id']
        if runtime_image is not None and self.image != runtime_image:
            raise ValueError('existing runtime image differs from requested ID')
        self.calls, self.counter, self.current = [], 0, None

    def call(self, mode, extra):
        self.counter += 1
        name = f'guradb-sample-{os.getpid()}-{self.counter}'
        command = ['docker', 'run', '--rm', '--pull', 'never', '--name', name, '--label', f'guradb.sample.owner={os.getpid()}', '--network', 'none', '--memory', '512m', '--cpus', '4',
                   '-v', str(self.binary)+':/guradb:ro', '-v', str(self.selection.parent)+':/selection:ro']
        if self.view_store:
            command += ['-v', str(self.view_store)+':/store', self.image, '/guradb', 'view', mode,
                        '--store', '/store', '--view', self.view_id or self.requested_view] + extra
        else:
            command += ['-v', str(self.config.parent)+':/data:ro', self.image, '/guradb', mode,
                        '--config', '/data/'+self.config.name] + extra
        self.current = name
        try:
            result = subprocess.run(command, capture_output=True, timeout=12)
            if result.returncode or len(result.stdout) > 2 * 1024**2:
                raise ValueError('Rust command failed: ' + result.stderr[:2048].decode('utf-8', 'replace'))
            value = json.loads(result.stdout)
            if self.view_store:
                view_id, source_sha = value['view_id'], value['source_sha256']
                if len(view_id) != 64 or any(c not in '0123456789abcdef' for c in view_id):
                    raise ValueError('Rust returned invalid fixed view ID')
                if self.view_id is None:
                    if mode != 'sample' or (self.requested_view != 'current' and view_id != self.requested_view) or value['result'].get('view_id') != view_id or value['result'].get('source_sha256') != source_sha:
                        raise ValueError('first view operation must fix Rust sample identity')
                    self.view_id, self.source_sha256 = view_id, source_sha
                if view_id != self.view_id or source_sha != self.source_sha256:
                    raise ValueError('Rust response changed the fixed view/source')
                value = value['result']
            self.calls.append({'mode': mode, 'view_id': self.view_id, 'exit_code': result.returncode, 'stdout_bytes': len(result.stdout),
                               'stdout_sha256': hashlib.sha256(result.stdout).hexdigest()})
            return value
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10, check=False)
            self.current = None


def worker(config, selection, output, batch_size, view_store=None, view=None, binary=None, runtime_image=None):
    start = time.monotonic()
    import importlib.metadata
    versions = {name: importlib.metadata.version(name) for name in ('torch', 'Pillow')}
    if versions != {'torch': '2.15.0', 'Pillow': '13.0.0'} or sys.version_info[:2] != (3, 12) or platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('use the existing hash-locked offline PyTorch/Pillow environment')
    cli = RustCLI(config, selection, view_store, view, binary, runtime_image)
    fixed = cli.call('sample', ['--selection', '/selection/'+cli.selection.name])
    if fixed.get('format_version') != 1 or fixed.get('model') != 'not_used' or fixed.get('algorithm') != 'asset-sha256-first-validation-v1':
        raise ValueError('unsupported Rust sample manifest')
    if len(json.dumps(fixed).encode()) > 1024**2:
        raise ValueError('manifest exceeds 1 MiB')
    members = fixed['train'] + fixed['validation']
    if not fixed['train'] or not fixed['validation'] or len(members) > 200:
        raise ValueError('Rust returned invalid fixed membership')
    if 2 * sum(row['media']['media_bytes'] for row in members) > MEDIA_BYTES_LIMIT:
        raise ValueError('two-epoch reader media budget exceeds 32 MiB')
    import torch
    from PIL import Image
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    Image.MAX_IMAGE_PIXELS = 4_000_000
    consumed = 0

    class Samples(torch.utils.data.Dataset):
        def __init__(self, rows):
            self.rows = rows

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, index):
            nonlocal consumed
            row = self.rows[index]
            media = row['media']
            extra = ['--asset-id', media['asset_id']]
            if not cli.view_store:
                extra += ['--source-sha256', fixed['source_sha256']]
            result = cli.call('media', extra)
            payload = bytes.fromhex(result['bytes_hex'])
            if result['source_sha256'] != fixed['source_sha256'] or any(result[k] != media[k] for k in ('asset_id', 'image_path', 'media_version', 'media_bytes', 'media_sha256')) or len(payload) != media['media_bytes'] or hashlib.sha256(payload).hexdigest() != media['media_sha256']:
                raise ValueError('Rust media differs from fixed member')
            consumed += len(payload)
            if consumed > MEDIA_BYTES_LIMIT or time.monotonic() - start > READER_SECONDS or resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > RSS_LIMIT:
                raise ValueError('reader resource budget exceeded')
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != 'JPEG' or image.width * image.height > 4_000_000:
                    raise ValueError('unsupported bounded JPEG')
                pixels = image.convert('RGB').resize((32, 32), resample=Image.Resampling.BILINEAR).tobytes()
            tensor = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(32, 32, 3).permute(2, 0, 1).contiguous()
            return {'doc_id': row['doc_id'], 'text': row['text'], 'asset_id': media['asset_id'],
                    'media_sha256': media['media_sha256'], 'media_bytes': media['media_bytes'],
                    'pixel_sha256': hashlib.sha256(tensor.numpy().tobytes()).hexdigest(), 'image': tensor}

    epochs = []
    for epoch in range(2):
        for split in ('train', 'validation'):
            loader = torch.utils.data.DataLoader(Samples(fixed[split]), batch_size=batch_size,
                                                shuffle=False, num_workers=0, drop_last=False)
            batches = []
            for batch in loader:
                batches.append({'doc_ids': batch['doc_id'], 'texts': batch['text'], 'asset_ids': batch['asset_id'],
                                'media_sha256': batch['media_sha256'], 'media_bytes': batch['media_bytes'].tolist(),
                                'pixel_sha256': batch['pixel_sha256'], 'tensor_shape': list(batch['image'].shape),
                                'tensor_dtype': str(batch['image'].dtype)})
            epochs.append({'epoch': epoch, 'split': split, 'members': len(fixed[split]), 'batches': batches})
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if rss > RSS_LIMIT or time.monotonic() - start > READER_SECONDS:
        raise ValueError('reader RSS/time budget exceeded')
    report = {'format_version': 1, 'model': 'not_used', 'source_sha256': fixed['source_sha256'],
              'view_id': cli.view_id,
              'selection_sha256': fixed['selection_sha256'], 'manifest_content_sha256': hashlib.sha256(json.dumps(fixed, sort_keys=True).encode()).hexdigest(),
              'manifest_hash_contract': 'python-json-sort-keys-default-separators-ascii-v1',
              'versions': versions, 'runtime': {'python': sys.version, 'platform': platform.platform(), 'device': 'cpu'},
              'client_script_sha256': digest(Path(__file__)),
              'rust_runtime': {'image_id': cli.image, 'binary_sha256': digest(cli.binary)},
              'transform': 'pillow13-rgb-bilinear32-uint8-chw-v1',
              'batch_size': batch_size, 'epochs': epochs, 'num_workers': 0, 'shuffle': False, 'drop_last': False,
              'observed': {'media_payload_bytes': consumed, 'seconds': time.monotonic()-start, 'rss_bytes': rss,
                           'torch_threads': torch.get_num_threads()}, 'rust_calls': cli.calls,
              'scope': 'fixed data/reader consumption only; no encoder, optimization or training-result reproduction'}
    membership_json = json.dumps(fixed, indent=2)+'\n'
    report_json = json.dumps(report, indent=2)+'\n'
    if len(membership_json.encode()) > 1024**2 or len(report_json.encode()) > 2*1024**2:
        raise ValueError('reader output byte limit exceeded')
    (output/'membership.json').write_text(membership_json)
    (output/'epochs.json').write_text(report_json)
    return {'view_id': cli.view_id, 'source_sha256': fixed['source_sha256'], 'train': len(fixed['train']), 'validation': len(fixed['validation']),
            'epochs': 2, 'observed': report['observed'], 'batch_lengths': [[len(b['doc_ids']) for b in e['batches']] for e in epochs]}


def run(config, selection, output_dir, batch_size, view_store=None, view=None, binary=None, runtime_image=None):
    if (binary is None) != (runtime_image is None):
        raise ValueError('explicit binary and fixed runtime-image must be provided together')
    if not 1 <= batch_size <= 8:
        raise ValueError('batch size requires 1..8')
    output = (ROOT/output_dir).resolve()
    if output_dir.is_absolute() or not output.is_relative_to(ROOT/'artifacts') or output == ROOT/'artifacts' or (ROOT/output_dir).is_symlink():
        raise ValueError('output must be a fresh relative artifacts directory')
    output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'OMP_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4', 'OPENBLAS_NUM_THREADS': '4',
           'GURADB_SAMPLE_PARENT': str(os.getpid())}
    mode = ['--view-store', str(view_store.resolve()), '--view', view or 'current'] if view_store else ['--config', str(config.resolve())]
    transport = ['--binary', str(binary.resolve()), '--runtime-image', runtime_image] if binary else []
    command = [sys.executable, str(Path(__file__).resolve()), *mode, *transport,
               '--selection', str(selection.resolve()), '--output-dir', str(output), '--batch-size', str(batch_size), '--worker']
    process = None
    start, peak = time.monotonic(), 0
    try:
        with tempfile.TemporaryFile() as logs:
            process = subprocess.Popen(command, env=env, stdout=logs, stderr=logs, start_new_session=True)
            while process.poll() is None:
                value = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(process.pid)], capture_output=True, text=True, check=False).stdout.strip()
                if value.isdigit():
                    peak = max(peak, int(value)*1024)
                if peak > RSS_LIMIT or time.monotonic()-start > READER_SECONDS:
                    raise ValueError('reader RSS/time limit exceeded')
                time.sleep(0.25)
            logs.seek(0)
            raw = logs.read(1024**2+1)
            if process.returncode or len(raw) > 1024**2:
                raise ValueError('reader worker failed: '+raw[:8192].decode('utf-8', 'replace'))
        report = json.loads((output/'epochs.json').read_text())
        report['watchdog'] = {'pid': process.pid, 'sampled_peak_rss_bytes': peak, 'seconds': time.monotonic()-start}
        (output/'epochs.json').write_text(json.dumps(report, indent=2)+'\n')
        return json.loads(raw.splitlines()[-1])
    except BaseException:
        try:
            if process is not None and process.poll() is None:
                # Worker handles TERM by removing its current owned container.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
        finally:
            try:
                if process is not None:
                    # A stopped/killed worker cannot run its own container finally.
                    ids = subprocess.run(['docker', 'ps', '-aq', '--filter', f'label=guradb.sample.owner={process.pid}'],
                                         capture_output=True, text=True, timeout=5, check=False).stdout.split()
                    if ids:
                        subprocess.run(['docker', 'rm', '-f', *ids], capture_output=True, timeout=10, check=False)
            finally:
                shutil.rmtree(output)
        raise


def main():
    def terminate(signum, _frame):
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--config', type=Path)
    mode.add_argument('--view-store', type=Path)
    parser.add_argument('--view')
    parser.add_argument('--binary', type=Path, help='explicit already-installed Linux ARM64 engine')
    parser.add_argument('--runtime-image', help='existing exact sha256 image ID; required with --binary')
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--batch-size', type=int, default=4)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (args.binary is None) != (args.runtime_image is None):
        parser.error('--binary and --runtime-image must be provided together')
    if args.config and args.view is not None:
        parser.error("--view requires --view-store")
    produced = None
    try:
        if args.worker:
            if os.environ.get('GURADB_SAMPLE_PARENT') != str(os.getppid()):
                raise ValueError('worker requires monitored parent')
            result = worker(args.config, args.selection, args.output_dir, args.batch_size, args.view_store, args.view, args.binary, args.runtime_image)
        else:
            result = run(args.config, args.selection, args.output_dir, args.batch_size, args.view_store, args.view, args.binary, args.runtime_image)
            produced = (ROOT/args.output_dir).resolve()
        print(json.dumps(result))
        sys.stdout.flush()
    except BaseException as error:
        if produced is not None:
            shutil.rmtree(produced)
        if isinstance(error, Exception):
            parser.exit(1, f'error: {error}\n')
        raise


if __name__ == '__main__':
    main()
