#!/usr/bin/env python3
"""Real Rust CLI black-box evidence; Python only prepares independent fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
from cargo import IMAGE

ROOT = Path(__file__).resolve().parents[1]


def require(value, message):
    if not value:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    require(run.is_relative_to(ROOT/'artifacts'), 'run directory must be inside artifacts')
    run.mkdir(parents=True, exist_ok=False)
    source = run/'records.parquet'
    # Literal rows and expected output are independent of Rust implementation.
    pq.write_table(pa.table({'record_id': ['r3', 'r1', 'r2', 'r0'],
                            'title': ['third', 'first', 'second', None],
                            'rank': pa.array([3, 1, 2, 0], type=pa.int64()),
                            'active': [True, True, False, True]}), source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    results = []
    containers = []
    command = 'SELECT record_id, title, rank FROM records WHERE active = true ORDER BY rank DESC LIMIT 2'

    def config(name, path=source, digest=sha, timeout=5000):
        destination = run/(name+'.json')
        destination.write_text(json.dumps({'source': path.name, 'sha256': digest, 'timeout_ms': timeout}))
        return destination

    def argv(config_path, sql=command):
        name = 'guradb-alpha-'+uuid.uuid4().hex[:12]
        containers.append(name)
        return name, ['docker', 'run', '--rm', '--name', name, '--network', 'none',
            '--memory', '512m', '--pids-limit', '128', '-v', f'{ROOT}:/workspace:ro', '-w', '/workspace',
            IMAGE, '/workspace/target/debug/guradb', 'query', '--config',
            '/workspace/'+config_path.relative_to(ROOT).as_posix(), '--sql', sql]

    def finished(name):
        check = subprocess.run(['docker', 'inspect', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        require(check.returncode != 0, 'container/process must be removed after exit')

    def invoke(case, config_path, sql=command, expected=None):
        name, command_argv = argv(config_path, sql)
        start = time.monotonic()
        result = subprocess.run(command_argv, capture_output=True, timeout=20)
        (run/(case+'.stdout')).write_bytes(result.stdout)
        (run/(case+'.stderr')).write_bytes(result.stderr)
        finished(name)
        if expected is None:
            require(result.returncode == 0, f'{case}: success failed: {result.stderr!r}')
            payload = json.loads(result.stdout)
            require(payload['source_sha256'] == sha, 'source binding changed')
            require(payload['rows'] == [['r3', 'third', '3'], ['r1', 'first', '1']], 'independent SQL truth mismatch')
            require(payload['truncated'] is False, 'unexpected truncation')
        else:
            require(result.returncode != 0 and not result.stdout, f'{case}: failure published success bytes')
            require(json.loads(result.stderr)['code'] == expected, f'{case}: wrong error: {result.stderr!r}')
        results.append({'case': case, 'exit': result.returncode, 'seconds': time.monotonic()-start,
                        'container_removed': True})

    try:
        good = config('good')
        invoke('success', good)
        invoke('wrong-hash', config('wrong-hash', digest='0'*64), expected='source_changed')
        broken = run/'broken.parquet'
        broken.write_bytes(b'not parquet')
        invoke('broken-parquet', config('broken', broken, hashlib.sha256(broken.read_bytes()).hexdigest()), expected='source_invalid')
        invoke('missing-input', config('missing', run/'absent.parquet'), expected='source_invalid')
        invoke('unsupported-sql', good, 'SELECT count(*) FROM records', expected='unsupported')
        # Deliberate change to the configured source, preserving the old digest.
        original = source.read_bytes()
        source.write_bytes(original+b'changed')
        invoke('changed-input', good, expected='source_changed')
        source.write_bytes(original)
        invoke('rerun-after-failures', good)

        invoke('rerun-final', good)
        evidence = {'kind': 'simple-rust-alpha-real-cli', 'passed': True,
                    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
                    'fixture_sha256': sha, 'cases': results}
        (run/'result.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps(evidence, indent=2))
    finally:
        for name in containers:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
