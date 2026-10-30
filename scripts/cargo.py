#!/usr/bin/env python3
"""Run the existing locked local Rust toolchain without network bootstrap."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:09bc0a87408c56bd4fe912df3ba3d499ea2279ea32cdeddf051a7a3dd3ddb52f'


def run(args):
    actual = subprocess.check_output(
        ['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}} {{.Os}} {{.Architecture}}'],
        cwd=ROOT, text=True, timeout=10).strip()
    if actual != IMAGE + ' linux arm64':
        raise RuntimeError('the existing locked Linux ARM64 toolchain image is required')
    print('Locked offline Rust toolchain: ' + IMAGE, flush=True)
    return subprocess.run(
        ['docker', 'run', '--rm', '--pull=never', '--network', 'none',
         '-e', 'CARGO_NET_OFFLINE=true', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
         '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', IMAGE,
         'cargo', *args], cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:]))
