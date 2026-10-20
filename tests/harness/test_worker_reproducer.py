from pathlib import Path
import os
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class WorkerReproducerTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load((ROOT / '.github/workflows/worker-reproducer.yml').read_text(),
                                  Loader=yaml.BaseLoader)
        self.job = self.workflow['jobs']['reproduce']

    def test_frozen_source_permissions_budget_and_evidence(self):
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(self.workflow['on']['push']['branches'], ['codex/worker-reproducer'])
        self.assertNotIn('pull_request', self.workflow['on'])
        self.assertEqual(self.job['strategy']['matrix']['python'], ['3.11', '3.14'])
        self.assertGreaterEqual(int(self.job['timeout-minutes']) * 60, 5 * 930 + 600)
        self.assertEqual(self.job['steps'][0]['with']['ref'], '949d484a3d06685d1dcd24cd8fe97a0dee375334')
        for step in self.job['steps']:
            if 'uses' in step:
                self.assertRegex(step['uses'], r'^[\w./-]+@[0-9a-f]{40}$')
            self.assertNotIn('continue-on-error', step)
        self.assertEqual(self.job['steps'][-1]['if'], 'always()')
        self.assertEqual(self.job['steps'][-1]['with']['retention-days'], '14')

    def test_all_five_samples_run_and_any_failure_is_sticky(self):
        script = next(step['run'] for step in self.job['steps']
                      if step.get('name') == 'Five independent real samples')
        for fail_at, expected in (('none', 0), ('attempt-2', 1)):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                timeout = root / 'timeout'
                timeout.write_text('#!/bin/sh\n[ "$1 $2 $3" = "--signal=INT --kill-after=30s 900" ] || exit 99\nshift 3\nexec "$@"\n')
                python = root / 'python'
                python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SAMPLE_LOG"\ncase "$*" in *"$FAIL_AT"*) exit 7;; esac\n')
                timeout.chmod(0o755)
                python.chmod(0o755)
                log = root / 'calls'
                result = subprocess.run(['bash', '-e', '-c', script], cwd=root,
                                        env={**os.environ, 'PATH': f'{root}:/usr/bin:/bin',
                                             'SAMPLE_LOG': str(log), 'FAIL_AT': fail_at}, check=False)
                self.assertEqual(result.returncode, expected)
                calls = log.read_text().splitlines()
                self.assertEqual(len(calls), 5)
                for index, call in enumerate(calls, 1):
                    self.assertEqual(call, f'scripts/m2_acceptance.py functional --run-dir artifacts/worker-reproducer/attempt-{index}')
