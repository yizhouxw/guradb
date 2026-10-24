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
from coverage_policy import THRESHOLDS, meets_threshold, read_lcov, summarize
from coverage_scope import coverage_scope, ignore_regex, package_args, python_roots, production_sources
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
             ROOT/'scripts/unit_coverage.py', ROOT/'scripts/coverage_scope.py', ROOT/'scripts/coverage_policy.py',
             ROOT/'scripts/harnesslib/validation_registry.py', ROOT/'harness/architecture.toml',
             ROOT/'harness/policy.toml', ROOT/'harness/validation.toml', *ROOT.glob('requirements*.lock')}
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def checked_image_id(raw):
    value = raw.removesuffix(b'\n').decode('ascii')
    if len(value) != 71 or not value.startswith('sha256:') or any(c not in '0123456789abcdef' for c in value[7:]):
        raise ValueError('Docker image identity is not a SHA-256 ID')
    return value


def build_image(directory, evidence):
    path = directory/'coverage-image.id'
    if path.exists() or path.is_symlink():
        raise FileExistsError('preserve the existing coverage image identity')
    argv = ['docker', 'build', '-q', '--iidfile', str(path), '-t', 'guradb-coverage:1.90.0',
            '-f', 'tools/test-coverage/Dockerfile', '.']
    if evidence is not None:
        evidence.record('tool_invocation', phase='docker_image_build', phase_id=evidence.sequence,
                        argv=argv, iidfile=str(path))
    subprocess.run(argv, cwd=ROOT, check=True)
    if path.is_symlink() or not path.is_file():
        raise ValueError('build did not produce a regular coverage image identity file')
    with path.open('rb') as stream:
        return checked_image_id(stream.read(73))


def image_identity(evidence, image):
    argv = ['docker', 'image', 'inspect', '--format', '{{.Id}}', image]
    if evidence is not None:
        evidence.record('tool_invocation', phase='docker_image_identity', phase_id=evidence.sequence,
                        argv=argv, image_id=image)
    value = checked_image_id(subprocess.check_output(argv, cwd=ROOT))
    if value != image:
        raise ValueError('inspected image differs from the captured build identity')
    if evidence is not None:
        evidence.record('tool_identity', image_id=value, image_reference=image, observation='after_image_build')
    return value


def run_coverage_tool(evidence, phase, argv, image):
    def execute():
        if evidence is not None:
            evidence.record('tool_invocation', phase=phase, phase_id=evidence.sequence,
                            argv=argv, image_id=image)
        return subprocess.run(argv, cwd=ROOT, check=True)
    return measured(evidence, phase, execute)


def record_identity(evidence, observation, scope=None):
    value = identity()
    if scope is not None:
        value["coverage_scope"] = scope
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


def python_coverage(directory, scope=None):
    import coverage
    cov = coverage.Coverage(config_file=str(ROOT/'.coveragerc'), data_file=str(directory/'python.data'),
                            source=python_roots(ROOT, scope))
    cov.start()
    suite = unittest.TestSuite()
    for path in (scope['python_tests'] if scope else ('tests/contracts', 'tests/unit')):
        suite.addTests(unittest.TestLoader().discover(str(ROOT/path)))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    cov.stop()
    # Namespace packages and never-imported modules must remain in the denominator.
    sources = ([ROOT/name for name in scope['python_sources']] if scope else
               [ROOT/name for name in production_sources(ROOT) if name.endswith('.py')])
    cov.get_data().touch_files([str(p) for p in sources])
    cov.save()
    cov.json_report(outfile=str(directory/'python.json'))
    cov.html_report(directory=str(directory/'python-html'))
    cov.report()
    payload = json.loads((directory/'python.json').read_text())
    complete = set(payload['files']) == {p.relative_to(ROOT).as_posix() for p in sources}
    totals = payload['totals']
    (directory/'thresholds.json').write_text(json.dumps({'threshold_percent': THRESHOLDS})+'\n')
    return (result.wasSuccessful() and complete and type(totals['excluded_lines']) is int
            and totals['excluded_lines'] == 0
            and type(totals['missing_lines']) is int
            and totals['missing_lines'] == totals['num_statements'] - totals['covered_lines']
            and meets_threshold('python', totals['covered_lines'], totals['num_statements']))


def rust_coverage(directory, evidence=None, scope=None):
    captured = measured(evidence, 'docker_image_build', lambda: build_image(directory, evidence))
    image = measured(evidence, 'docker_image_identity', lambda: image_identity(evidence, captured))
    output = directory/'rust.json'
    run_coverage_tool(evidence, 'rust_collect_test_json',
                    ['docker', 'run', '--rm', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
                    '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', image,
                    'cargo', 'llvm-cov', *package_args(scope), '--locked', '--ignore-filename-regex', ignore_regex(ROOT, scope), '--json', '--output-path',
                    '/workspace/'+output.relative_to(ROOT).as_posix()], image)
    lcov = directory/'rust.lcov'
    run_coverage_tool(evidence, 'rust_lcov_export',
                    ['docker', 'run', '--rm', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
                    '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', image,
                    'cargo', 'llvm-cov', 'report', *(package_args(scope) if scope else []), '--locked', '--ignore-filename-regex', ignore_regex(ROOT, scope),
                    '--lcov', '--output-path', '/workspace/'+lcov.relative_to(ROOT).as_posix()], image)
    return measured(evidence, 'rust_summary', lambda: rust_summary(directory, output, lcov, scope))


def rust_summary(directory, output, lcov, scope=None):
    payload = json.loads(output.read_text())
    all_sources = {name for name in production_sources(ROOT) if name.endswith('.rs')}
    sources = set(scope['rust_sources']) if scope else all_sources
    files = read_lcov(lcov, sources)
    # A second export must still describe the same source set, never silently
    # dropping an unexecuted file. Retain native totals including closure mappings.
    native = {Path(item['filename']).relative_to('/workspace').as_posix(): item['summary']['lines']
              for datum in payload['data'] for item in datum['files']}
    if set(native) != sources:
        raise ValueError('LLVM JSON source inventory mismatch')
    summary = summarize(ROOT, files, ROOT/'harness/coverage-exclusions.json',
                        universe=all_sources if scope else None)
    if scope is not None:
        summary['coverage_scope'] = scope
    summary['llvm_native'] = native
    summary['threshold_percent'] = dict(THRESHOLDS)
    (directory/'rust-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({'rust_coverage': summary['totals'], 'metric': summary['metric']}, indent=2))
    return meets_threshold('rust', summary['totals']['eligible_covered'], summary['totals']['eligible_lines'])


def identity():
    return {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'checkout_digest': checkout_digest(ROOT, load(ROOT)[0]),
            'production_sources': production_sources(ROOT),
            'python': sys.version, 'coverage': version('coverage'),
            'rust': '1.90.0', 'cargo_llvm_cov': '0.6.21', 'threshold_percent': dict(THRESHOLDS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=('python', 'rust', 'all'), default='all')
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--module', action='append', default=[], help='complete owner denominator; no changed-lines filter')
    args = parser.parse_args()
    scope = coverage_scope(ROOT, args.module) if args.module else None
    directory = args.run_dir.resolve()
    if not directory.is_relative_to(ROOT):
        parser.error('run directory must be within workspace')
    directory.mkdir(parents=True, exist_ok=False)
    with exclusive_run(ROOT):
        evidence = PhaseEvidence(directory)
        before = evidence.run('identity_before', lambda: record_identity(evidence, 'before', scope))
        outcomes = {}
        for name, driver in (('python', lambda path: python_coverage(path, scope)),
                             ('rust', lambda path: rust_coverage(path, evidence, scope))):
            if args.language in (name, 'all'):
                try:
                    outcomes[name] = evidence.run(name, lambda: driver(directory))
                except Exception:
                    traceback.print_exc()
                    outcomes[name] = False
        after = evidence.run('identity_after', lambda: record_identity(evidence, 'after', coverage_scope(ROOT, args.module) if scope else None))
        outcomes['unchanged_source'] = before == after
        (directory/'identity.json').write_text(json.dumps({'before': before, 'after': after}, indent=2)+'\n')
        (directory/'result.json').write_text(json.dumps(outcomes, indent=2)+'\n')
    return 0 if all(outcomes.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
