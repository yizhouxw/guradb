#!/usr/bin/env python3
"""Code-bound P03 module acceptance, with real local S3 and explicit faults."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harnesslib.policy import load
from harnesslib.runner import checkout_digest
from m0lib.kit import S3, laboratory, write
from tests.storage_support.acceptance import FixturePutFailure, faults, real_backend
from tests.storage_support.fixtures import input_manifest
from tests.storage_support.log_capture import PrivateLogs


def identity():
    return {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'checkout_digest': checkout_digest(ROOT, load(ROOT)[0]),
            'locks': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                      for name in ('requirements-dev.lock', 'requirements-m0.lock', 'requirements-m1.lock', 'Cargo.lock')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('functional', 'performance', 'faults'), required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    arguments = parser.parse_args()
    directory = arguments.run_dir.resolve()
    if not directory.is_relative_to(ROOT/'artifacts') or directory.exists():
        parser.error('run directory must be new and inside artifacts')
    directory.mkdir(parents=True)
    before = identity()
    write(directory/'input-manifest.json', input_manifest())
    try:
        with PrivateLogs() as captured:
            try:
                if arguments.suite == 'faults':
                    result = faults()
                else:
                    with laboratory(directory/'lab') as lab:
                        result = real_backend(lab, arguments.suite)
            finally:
                # Audit successful and exceptional execution, never persist a leaking capture.
                log_audit = captured.audit()
        after = identity()
        assert after == before, 'source changed during acceptance'
        assert result['passed'] is True
        result.update(identity=after, suite=arguments.suite, logging=log_audit,
                      environment={'python': sys.version, 'host': platform.platform(), 'image': S3,
                                   'scope': 'local loopback simulation only', 'proxy': 'explicit local pass-through; no ambient proxy'},
                      input_sha256=input_manifest()['sha256'])
        write(directory/'result.json', result)
        print(json.dumps({'passed': True, 'suite': arguments.suite, 'report': str(directory/'result.json')}))
        return 0
    except Exception as error:
        # Persist code locations, not exception strings/source lines containing URLs or credentials.
        trace = [{'file': str(Path(item.filename).relative_to(ROOT)) if Path(item.filename).is_relative_to(ROOT)
                  else Path(item.filename).name, 'line': item.lineno, 'function': item.name}
                 for item in traceback.extract_tb(error.__traceback__)]
        diagnostic = {'fixture': error.diagnostics()} if isinstance(error, FixturePutFailure) else {}
        write(directory/'failure.json', {'passed': False, 'suite': arguments.suite,
              'error_class': type(error).__name__, 'code': getattr(error, 'code', 'driver_assertion'),
              'trace': trace, 'identity': before, **diagnostic})
        print(json.dumps({'passed': False, 'report': str(directory/'failure.json')}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
