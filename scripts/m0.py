#!/usr/bin/env python3
"""Run real M0 functional, component performance or fault acceptance; fail closed."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import traceback
import runpy
import time
import hashlib
from harnesslib.policy import load
from harnesslib.runner import checkout_digest

from m0lib.kit import ROOT, fixture, mapped, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite', choices=['functional', 'performance-smoke', 'stability-component', 'fixture'])
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    directory = (args.run_dir or ROOT/'artifacts'/'m0'/ (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+args.suite)).resolve()
    if not directory.is_relative_to(ROOT):
        parser.error('run directory must be within the workspace for the isolated Docker mount')
    directory.mkdir(parents=True, exist_ok=True)
    if args.suite == 'fixture':
        manifest, _ = fixture(directory/'objects')
        write(directory/'manifest.json', manifest)
        write(directory/'auth.json', {'principals':[{'token_sha256':hashlib.sha256(b'm0-local-example').hexdigest(),
                                                    'tenant_id':'demo','principal_id':'reader','datasets':[manifest['dataset_id']]}]})
        write(directory/'server.json', {'listen':'0.0.0.0:8080','manifests':[{'path':mapped(directory/'manifest.json'),
                         'sha256':hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest()}], 'auth_file':mapped(directory/'auth.json')})
        print(directory/'server.json')
        return 0
    # Build the real executable: cargo test alone only creates a binary test harness.
    started = time.perf_counter()
    subprocess.run([sys.executable, 'scripts/cargo.py', 'build', '--workspace', '--locked'], cwd=ROOT, check=True)
    build_seconds = time.perf_counter() - started
    driver_paths = {'functional':'tests/functional/m0.py', 'performance-smoke':'tests/performance/component/m0.py', 'stability-component':'tests/faults/component/m0.py'}
    driver = runpy.run_path(str(ROOT/driver_paths[args.suite]))['run']
    try:
        result = driver(directory)
        result.update(build_seconds=build_seconds, git_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
                      dependency_lock_sha256=hashlib.sha256((ROOT/"Cargo.lock").read_bytes()).hexdigest(),
                      checkout_digest=checkout_digest(ROOT,load(ROOT)[0]))
        if (directory/"trace.json").exists():
            result["trace_sha256"] = hashlib.sha256((directory/"trace.json").read_bytes()).hexdigest()
    except Exception:
        write(directory/'failure.json', {'suite':args.suite, 'passed':False, 'traceback':traceback.format_exc()})
        print(traceback.format_exc(), file=sys.stderr)
        return 1
    write(directory/'result.json', result)
    print(json.dumps({'passed':result['passed'], 'suite':args.suite, 'evidence':str(directory/'result.json'), 'sha256':hashlib.sha256((directory/'result.json').read_bytes()).hexdigest()}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
