#!/usr/bin/env python3
"""Measure unit/contract coverage of every Python and Rust production source."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import traceback
from importlib.metadata import version
from coverage_policy import read_lcov, summarize
from harnesslib.policy import load
from harnesslib.runner import checkout_digest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PhaseEvidence:
    """Append durable boundaries; an unmatched start never proves completion."""

    def __init__(self, directory):
        self.path = directory/'phases.jsonl'
        self.sequence = 0
        self.origin = time.monotonic_ns()
        with self.path.open('x') as stream:
            self._write(stream, {'event': 'run_started'})

    def _write(self, stream, payload):
        record = {'schema_version': 1, 'monotonic_ns': time.monotonic_ns(), **payload}
        stream.write(json.dumps(record, sort_keys=True, allow_nan=False)+'\n')
        stream.flush()
        os.fsync(stream.fileno())

    def record(self, event, **payload):
        with self.path.open('a') as stream:
            self._write(stream, {'event': event, **payload})

    def run(self, name, operation):
        self.sequence += 1
        phase_id = self.sequence
        started = time.monotonic_ns()
        self.record('started', phase=name, phase_id=phase_id,
                    elapsed_seconds=(started-self.origin)/1_000_000_000)
        try:
            result = operation()
        except BaseException as error:
            self.record('failed', phase=name, phase_id=phase_id,
                        duration_seconds=(time.monotonic_ns()-started)/1_000_000_000,
                        exception_type=type(error).__name__)
            raise
        self.record('failed' if result is False else 'finished', phase=name, phase_id=phase_id,
                    duration_seconds=(time.monotonic_ns()-started)/1_000_000_000,
                    outcome='rejected' if result is False else 'completed')
        return result


def measured(evidence, name, operation):
    return operation() if evidence is None else evidence.run(name, operation)


def evidence_inputs():
    paths = {ROOT/'Cargo.lock', ROOT/'rust-toolchain.toml', ROOT/'.coveragerc',
             ROOT/'harness/coverage-exclusions.json', ROOT/'tools/test-coverage/Dockerfile',
             ROOT/'scripts/unit_coverage.py', *ROOT.glob('requirements*.lock')}
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def image_identity(evidence, image):
    value = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                                    cwd=ROOT, text=True).strip()
    if len(value) != 71 or not value.startswith('sha256:') or any(c not in '0123456789abcdef' for c in value[7:]):
        raise ValueError('Docker image identity is not a SHA-256 ID')
    evidence.record('tool_identity', image_tag=image, image_id=value, observation='after_image_build')


def record_identity(evidence, observation):
    value = identity()
    evidence.record('source_identity', observation=observation, identity=value, inputs=evidence_inputs())
    return value


@contextmanager
def exclusive_run(root):
    # cargo-llvm-cov cleans/merges a shared target profile directory. Concurrent
    # exports from this checkout must never borrow another run's counters.
    path = root/'artifacts/unit-coverage.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('coverage already running in this checkout') from None
        yield


def python_coverage(directory):
    import coverage
    cov = coverage.Coverage(config_file=str(ROOT/'.coveragerc'), data_file=str(directory/'python.data'))
    cov.start()
    suite = unittest.TestSuite()
    for path in ('tests/contracts', 'tests/unit'):
        suite.addTests(unittest.TestLoader().discover(str(ROOT/path)))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    cov.stop()
    # Namespace packages and never-imported modules must remain in the denominator.
    sources = sorted(p for base in ('modules', 'clients') for p in (ROOT/base).rglob('*.py'))
    cov.get_data().touch_files([str(p) for p in sources])
    cov.save()
    cov.json_report(outfile=str(directory/'python.json'))
    cov.html_report(directory=str(directory/'python-html'))
    cov.report()
    payload = json.loads((directory/'python.json').read_text())
    complete = set(payload['files']) == {p.relative_to(ROOT).as_posix() for p in sources}
    return result.wasSuccessful() and complete and payload['totals']['missing_lines'] == 0 and payload['totals']['excluded_lines'] == 0


def rust_coverage(directory, evidence=None):
    image = 'guradb-coverage:1.90.0'
    measured(evidence, 'docker_image_build', lambda: subprocess.run(
        ['docker', 'build', '-q', '-t', image, '-f', 'tools/test-coverage/Dockerfile', '.'], cwd=ROOT, check=True))
    if evidence is not None:
        evidence.run('docker_image_identity', lambda: image_identity(evidence, image))
    output = directory/'rust.json'
    measured(evidence, 'rust_collect_test_json', lambda: subprocess.run(
                    ['docker', 'run', '--rm', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
                    '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', image,
                    'cargo', 'llvm-cov', '--workspace', '--locked', '--ignore-filename-regex', '(^|/)tests/', '--json', '--output-path',
                    '/workspace/'+output.relative_to(ROOT).as_posix()], cwd=ROOT, check=True))
    lcov = directory/'rust.lcov'
    measured(evidence, 'rust_lcov_export', lambda: subprocess.run(
                    ['docker', 'run', '--rm', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
                    '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', image,
                    'cargo', 'llvm-cov', 'report', '--locked', '--ignore-filename-regex', '(^|/)tests/',
                    '--lcov', '--output-path', '/workspace/'+lcov.relative_to(ROOT).as_posix()], cwd=ROOT, check=True))
    return measured(evidence, 'rust_summary', lambda: rust_summary(directory, output, lcov))


def rust_summary(directory, output, lcov):
    payload = json.loads(output.read_text())
    sources = {p.relative_to(ROOT).as_posix() for p in (ROOT/'crates').glob('*/src/**/*.rs')}
    files = read_lcov(lcov, sources)
    # A second export must still describe the same source set, never silently
    # dropping an unexecuted file. Retain native totals including closure mappings.
    native = {Path(item['filename']).relative_to('/workspace').as_posix(): item['summary']['lines']
              for datum in payload['data'] for item in datum['files']}
    if set(native) != sources:
        raise ValueError('LLVM JSON source inventory mismatch')
    summary = summarize(ROOT, files, ROOT/'harness/coverage-exclusions.json')
    summary['llvm_native'] = native
    (directory/'rust-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({'rust_coverage': summary['totals'], 'metric': summary['metric']}, indent=2))
    return summary['totals']['missing_lines'] == 0


def identity():
    return {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'checkout_digest': checkout_digest(ROOT, load(ROOT)[0]),
            'python': sys.version, 'coverage': version('coverage'),
            'rust': '1.90.0', 'cargo_llvm_cov': '0.6.21'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=('python', 'rust', 'all'), default='all')
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if not directory.is_relative_to(ROOT):
        parser.error('run directory must be within workspace')
    directory.mkdir(parents=True, exist_ok=False)
    with exclusive_run(ROOT):
        evidence = PhaseEvidence(directory)
        before = evidence.run('identity_before', lambda: record_identity(evidence, 'before'))
        outcomes = {}
        for name, driver in (('python', python_coverage), ('rust', lambda path: rust_coverage(path, evidence))):
            if args.language in (name, 'all'):
                try:
                    outcomes[name] = evidence.run(name, lambda: driver(directory))
                except Exception:
                    traceback.print_exc()
                    outcomes[name] = False
        after = evidence.run('identity_after', lambda: record_identity(evidence, 'after'))
        outcomes['unchanged_source'] = before == after
        (directory/'identity.json').write_text(json.dumps({'before': before, 'after': after}, indent=2)+'\n')
        (directory/'result.json').write_text(json.dumps(outcomes, indent=2)+'\n')
    return 0 if all(outcomes.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
