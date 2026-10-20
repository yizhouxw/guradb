"""Frozen-source diagnosis; retain worker evidence before unittest cleans fixtures."""
import argparse
import functools
import json
from pathlib import Path
import platform
import subprocess
import sys
import unittest


class Capture(unittest.TextTestResult):
    def __init__(self, *args, directory, **kwargs):
        super().__init__(*args, **kwargs)
        self.directory = Path(directory)

    def addError(self, test, err):
        root = getattr(test, 'root', None)
        if root:
            paths = sorted(path for path in Path(root).rglob('*')
                           if path.name in {'worker-failure.json', '0.failure.log', '1.failure.log', '2.failure.log'})
            for path in paths[:16]:
                raw = path.read_bytes()[-8192:]
                destination = self.directory/'failure'/path.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
                print(str(path.relative_to(root)), repr(raw), flush=True)
        super().addError(test, err)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(Path.cwd()))
    import coverage
    from tests.contracts.test_shard_review import ShardReview
    cov = coverage.Coverage(config_file='.coveragerc', data_file=str(args.run_dir/'python.data'))
    cov.start()
    suite = unittest.TestSuite(ShardReview('test_real_workers_share_remaining_source_budget') for _ in range(300))
    result = unittest.TextTestRunner(resultclass=functools.partial(Capture, directory=args.run_dir),
                                    verbosity=1, failfast=True).run(suite)
    cov.stop()
    identity = {'tested_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'python': sys.version, 'machine': platform.machine(), 'tests': result.testsRun,
                'passed': result.wasSuccessful()}
    (args.run_dir/'result.json').write_text(json.dumps(identity, indent=2)+'\n')
    print(json.dumps(identity), flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
