#!/usr/bin/env python3
"""Measure unit/contract coverage of every Python and Rust production source."""
import argparse
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import unittest
import traceback
from importlib.metadata import version
from coverage_policy import read_lcov, summarize
from harnesslib.policy import load
from harnesslib.runner import checkout_digest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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


def rust_coverage(directory):
    image = 'guradb-coverage:1.90.0'
    subprocess.run(['docker', 'build', '-q', '-t', image, '-f', 'tools/test-coverage/Dockerfile', '.'], cwd=ROOT, check=True)
    output = directory/'rust.json'
    subprocess.run(['docker', 'run', '--rm', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
                    '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', image,
                    'cargo', 'llvm-cov', '--workspace', '--locked', '--ignore-filename-regex', '(^|/)tests/', '--json', '--output-path',
                    '/workspace/'+output.relative_to(ROOT).as_posix()], cwd=ROOT, check=True)
    lcov = directory/'rust.lcov'
    subprocess.run(['docker', 'run', '--rm', '-v', f'{ROOT}:/workspace', '-w', '/workspace',
                    '-v', 'guradb-cargo-registry:/usr/local/cargo/registry', image,
                    'cargo', 'llvm-cov', 'report', '--locked', '--ignore-filename-regex', '(^|/)tests/',
                    '--lcov', '--output-path', '/workspace/'+lcov.relative_to(ROOT).as_posix()], cwd=ROOT, check=True)
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
        before = identity()
        outcomes = {}
        for name, driver in (('python', python_coverage), ('rust', rust_coverage)):
            if args.language in (name, 'all'):
                try:
                    outcomes[name] = driver(directory)
                except Exception:
                    traceback.print_exc()
                    outcomes[name] = False
        after = identity()
        outcomes['unchanged_source'] = before == after
        (directory/'identity.json').write_text(json.dumps({'before': before, 'after': after}, indent=2)+'\n')
        (directory/'result.json').write_text(json.dumps(outcomes, indent=2)+'\n')
    return 0 if all(outcomes.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
