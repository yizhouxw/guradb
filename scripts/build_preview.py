"""Build one local stdlib zipapp, never copy a build cache or publish remotely."""
import argparse
import hashlib
import json
import os
import platform
import resource
import signal
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SHIM = b'#!/bin/sh\nbase=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd) || exit 1\nexec /usr/bin/python3 "$base/lib/launcher.py" "$@"\n'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def build(binary, output, runtime):
    start = time.monotonic()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('output must be fresh with an existing parent')
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('preview producer supports macOS arm64 only')
    if not runtime.startswith('sha256:') or len(runtime) != 71 or any(c not in '0123456789abcdef' for c in runtime[7:]):
        raise ValueError('runtime must be a fixed image Id')
    with binary.open('rb') as f:
        header = f.read(64)
    if header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 183:
        raise ValueError('binary must be Linux ARM64 ELF')
    image = subprocess.check_output(['docker', 'image', 'inspect', runtime, '--format', '{{.Id}} {{.Os}} {{.Architecture}}'], text=True, timeout=10).strip()
    if image != runtime+' linux arm64':
        raise ValueError('fixed existing runtime image must be Linux ARM64')
    files = {'lib/engine': binary, 'lib/launcher.py': ROOT/'scripts/preview_launcher.py',
             'lib/capabilities.json': ROOT/'api/capabilities/v1.json'}
    if any(not p.is_file() or p.is_symlink() for p in files.values()) or sum(p.stat().st_size for p in files.values())+len(SHIM) > 1024**3:
        raise ValueError('payload requires bounded regular files, expanded total at most 1 GiB')
    if files['lib/launcher.py'].stat().st_size > 65536 or files['lib/capabilities.json'].stat().st_size > 65536:
        raise ValueError('payload metadata exceeds bound')
    rows = {name: {'bytes': p.stat().st_size, 'sha256': digest(p)} for name, p in files.items()}
    rows['bin/guradb'] = {'bytes': len(SHIM), 'sha256': hashlib.sha256(SHIM).hexdigest()}
    m = {'format_version': 1, 'engine_arch': 'linux-arm64', 'host': 'darwin-arm64',
         'runtime_image': runtime, 'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
         'engine_rust_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD:crates/guradb'], cwd=ROOT, text=True).strip(),
         'packaging_sources_sha256': {name: digest(ROOT/'scripts'/name) for name in ('build_preview.py', 'preview_install.py', 'preview_launcher.py')},
         'optional_tools': 'source preparation, model encoder and PyTorch reader are not bundled',
         'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
         'engineering_python': 'system /usr/bin/python3 >=3.9 standard library; no development venv',
         'files': rows}
    temp = output.with_name(output.name+'.partial')
    if temp.exists():
        raise ValueError('partial output already exists')
    try:
        with zipfile.ZipFile(temp, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(ROOT/'scripts/preview_install.py', '__main__.py')
            z.writestr('payload/manifest.json', json.dumps(m, indent=2)+'\n')
            z.writestr('payload/bin/guradb', SHIM)
            for name, path in files.items():
                z.write(path, 'payload/'+name)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if temp.stat().st_size > 1024**3 or time.monotonic()-start > 120 or rss > 512*1024**2:
            raise ValueError('build size/time limit exceeded')
        os.rename(temp, output)
        return {'artifact': str(output), 'bytes': output.stat().st_size, 'sha256': digest(output), 'engine_sha256': rows['lib/engine']['sha256'], 'seconds': time.monotonic()-start, 'rss_bytes': rss, 'provenance': m}
    finally:
        if temp.exists():
            temp.unlink()


if __name__ == '__main__':
    def timeout(_sig, _frame):
        raise TimeoutError('preview build deadline exceeded')
    def stop(sig, _frame):
        raise SystemExit(128+sig)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(120)
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-image', required=True)
    a = parser.parse_args()
    try:
        print(json.dumps(build(a.binary.resolve(strict=True), a.output.absolute(), a.runtime_image)), flush=True)
    except Exception as e:
        print(json.dumps({'code': 'build_failed', 'message': str(e)}), file=sys.stderr, flush=True)
        sys.exit(1)
    finally:
        fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(fd, 1)
            os.dup2(fd, 2)
        finally:
            os.close(fd)
        signal.alarm(0)
