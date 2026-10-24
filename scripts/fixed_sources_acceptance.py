#!/usr/bin/env python3
"""P04 narrow fixed-source component evidence; real S3 or actual TCP faults."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def identity():
    from scripts.harnesslib.policy import load
    from scripts.harnesslib.runner import checkout_digest
    return {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'checkout_digest': checkout_digest(ROOT, load(ROOT)[0]),
        'locks': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                  ('requirements-dev.lock', 'requirements-m0.lock', 'requirements-m1.lock', 'Cargo.lock')}}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')



def runtime_components():
    from m0lib.kit import S3, docker, laboratory
    from tests.source_support.fixed_backend_cases import real_backend
    from tests.source_support.fixed_fault_cases import faults
    from tests.storage_support.log_capture import PrivateLogs
    return S3, docker, laboratory, real_backend, faults, PrivateLogs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('functional', 'performance', 'fault', 'pair'), required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    arguments = parser.parse_args()
    directory = arguments.run_dir.resolve()
    if not directory.is_relative_to(ROOT/'artifacts') or directory.exists():
        parser.error('run directory must be new and inside artifacts')
    directory.mkdir(parents=True)
    if arguments.mode == 'pair':
        from tests.source_support.fixed_catalog_pair_runner import bounded
        return bounded(directory)
    # The diagnostic helper imports only stdlib; no runtime I/O can precede identity.
    from tests.source_support.fixed_evidence import error_record, lab_record
    try:
        before = identity()
    except Exception as error:
        write(directory/'failure.json', {'passed': False, 'stage': 'identity_before',
              'primary_error': error_record(error), 'runtime_started': False})
        return 1
    result, failure, logging = None, None, None
    lab = private = docker = None
    lifecycle = identity_error = None
    try:
        S3, docker, laboratory, real_backend, faults, PrivateLogs = runtime_components()
        with PrivateLogs() as captured:
            try:
                if arguments.mode == 'fault':
                    result = faults(directory)
                else:
                    # Auth/config/raw service logs stay outside every harness upload tree.
                    private = ROOT/'artifacts'/'private'/('p04-' + uuid.uuid4().hex)
                    with laboratory(private/'lab') as lab:
                        result = real_backend(lab, directory, arguments.mode)
            finally:
                logging = captured.audit()
        assert result['passed'] is True
        result['environment'] = {'python': sys.version, 'host': platform.platform(), 'image': S3,
            'scope': 'local loopback simulation only', 'production_native_decoder': False,
            'proxy': 'P03 custom read socket via explicit numeric loopback; no ambient proxy in read transport',
            'fixture_sdk': 'not used' if arguments.mode == 'fault' else 'explicit direct; actual certification in report',
            'cache': '256KiB application cache; OS cache uncontrolled',
            'deadline': 'parent query plus original1s/page and5s/cohort; external whole-call timing'}
    except Exception as error:
        failure = {'passed': False, 'primary_error': error_record(error)}
        chain, context = [], error.__context__
        while context is not None and len(chain) < 4:
            chain.append(error_record(context))
            context = context.__context__
        failure['error_contexts'] = chain
        failure['earliest_error'] = chain[-1] if chain else failure['primary_error']
    finally:
        after = None
        try:
            after = identity()
        except Exception as error:
            identity_error = error_record(error)
        try:
            lifecycle = lab_record(lab, private, docker) if arguments.mode != 'fault' else None
        except Exception as error:
            lifecycle = {'cleanup_confirmed': False, 'diagnostic_error': error_record(error),
                         'private_lab': str(private/'lab') if private is not None else None}
        if failure is None and (identity_error is not None or after != before):
            failure = {'passed': False, 'code': 'source_identity_unavailable_or_changed'}
        if failure is None and arguments.mode != 'fault' and lifecycle['cleanup_confirmed'] is not True:
            failure = {'passed': False, 'code': 'service_cleanup_not_confirmed'}
        record = failure if failure is not None else result
        record.update(identity_before=before, identity_after=after, identity_error=identity_error,
                      lifecycle=lifecycle, logging=logging, mode=arguments.mode)
        raw = []
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                content = path.read_bytes()
                raw.append({'path': path.relative_to(directory).as_posix(),
                            'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
        record['evidence_files'] = raw
        report = directory/('failure.json' if failure is not None else 'report.json')
        write(report, record)
    print(json.dumps({'passed': failure is None, 'mode': arguments.mode, 'report': str(report)}))
    return int(failure is not None)


if __name__ == '__main__':
    raise SystemExit(main())
