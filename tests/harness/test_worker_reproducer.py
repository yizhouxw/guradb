from io import StringIO
from pathlib import Path
import runpy
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
Capture = runpy.run_path(str(ROOT/'tests/harness/worker_probe.py'))['Capture']


class WorkerReproducerTests(unittest.TestCase):
    def test_frozen_source_and_failure_are_not_retried_or_ignored(self):
        workflow = yaml.load((ROOT/'.github/workflows/worker-reproducer.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertNotIn('pull_request', workflow['on'])
        job = workflow['jobs']['reproduce']
        frozen = [s for s in job['steps'] if s.get('with', {}).get('ref')]
        self.assertEqual(frozen[0]['with']['ref'], '4828d4aaebca94c642377e1c93148d60eaf85a53')
        self.assertGreaterEqual(int(job['timeout-minutes'])*60, 3630+600)
        for step in job['steps']:
            self.assertNotIn('continue-on-error', step)
            if 'uses' in step:
                self.assertRegex(step['uses'], r'^[\w./-]+@[0-9a-f]{40}$')
        probe = next(s['run'] for s in job['steps'] if s.get('name') == 'Capture the first real worker failure')
        self.assertIn('timeout --signal=INT --kill-after=30s 3600', probe)
        self.assertNotIn('||', probe)
        self.assertEqual(job['steps'][-1]['if'], 'always()')

    def test_capture_runs_before_fixture_cleanup_and_only_retains_bounded_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root/'fixture'
            fixture.mkdir()
            (fixture/'0.failure.log').write_bytes(b'x'*12000+b'CRASH')
            (fixture/'worker-failure.json').write_text('{"returncode": -6}')
            (fixture/'private.input').write_text('do-not-retain')
            test = unittest.FunctionTestCase(lambda: None)
            test.root = fixture
            result = Capture(StringIO(), True, 1, directory=root/'evidence')
            try:
                raise RuntimeError('real runner failure fixture')
            except RuntimeError:
                result.addError(test, sys.exc_info())
            self.assertFalse(result.wasSuccessful())
            saved = root/'evidence/failure'
            self.assertEqual((saved/'0.failure.log').stat().st_size, 8192)
            self.assertTrue((saved/'0.failure.log').read_bytes().endswith(b'CRASH'))
            self.assertEqual({p.name for p in saved.iterdir()}, {'0.failure.log', 'worker-failure.json'})
