#!/usr/bin/env python3
"""Run the locked Rust toolchain in the same container locally and in CI."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'guradb-rust:1.90.0'

def run(args):
    subprocess.run(['docker', 'build', '-q', '-t', IMAGE, '-f', 'tools/m0/Dockerfile', '.'], cwd=ROOT, check=True)
    return subprocess.run(['docker', 'run', '--rm', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
                           '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', IMAGE,
                           'cargo', *args], cwd=ROOT).returncode

if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:]))
