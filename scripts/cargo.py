#!/usr/bin/env python3
"""Run the existing locked local Rust toolchain without network bootstrap."""
import subprocess
import os
import stat
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:09bc0a87408c56bd4fe912df3ba3d499ea2279ea32cdeddf051a7a3dd3ddb52f'


def metadata(path):
    info = path.lstat()
    return tuple(getattr(info, 'st_' + key) for key in
                 ('dev', 'ino', 'mode', 'size', 'mtime_ns', 'ctime_ns', 'nlink'))


def cache_metadata():
    directory = ROOT / 'target' / 'debug' / 'deps'
    if any(p.is_symlink() for p in (ROOT / 'target', ROOT / 'target' / 'debug', directory)):
        raise RuntimeError('linked cache roots are unsupported')
    return {p: metadata(p) for p in directory.glob('*.rmeta')}


def finish_check_metadata(before):
    after = cache_metadata()
    owned = [(p, record) for p, record in after.items()
             if p not in before and stat.S_ISREG(record[2])
             and not os.path.lexists(p.with_suffix('.rlib'))]
    # Cargo has exited and the caller owns the serial build window. Check all
    # identities before unlinking any command-created check-only metadata.
    if any(metadata(p) != record for p, record in owned):
        raise RuntimeError('check metadata changed before guarded exit')
    for path, _ in owned:
        path.unlink()
    print(json.dumps({'check_metadata_guard': 'complete', 'files': [
        {'path': str(path.relative_to(ROOT)), 'identity': list(record)}
        for path, record in owned], 'bytes': sum(r[3] for _, r in owned),
        'borrowed_and_build_metadata_preserved': True}), flush=True)


def run(args):
    actual = subprocess.check_output(
        ['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}} {{.Os}} {{.Architecture}}'],
        cwd=ROOT, text=True, timeout=10).strip()
    if actual != IMAGE + ' linux arm64':
        raise RuntimeError('the existing locked Linux ARM64 toolchain image is required')
    print('Locked offline Rust toolchain: ' + IMAGE, flush=True)
    before = cache_metadata() if args and args[0] == 'clippy' else None
    result = subprocess.run(
        ['docker', 'run', '--rm', '--pull=never', '--network', 'none',
         '-e', 'CARGO_NET_OFFLINE=true', '-e', 'CARGO_BUILD_JOBS=1', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
         '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', IMAGE,
         'cargo', *args], cwd=ROOT).returncode
    if result == 0 and before is not None:
        finish_check_metadata(before)
    return result


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:]))
