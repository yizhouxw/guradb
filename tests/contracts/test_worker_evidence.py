"""Real worker crashes retain bounded private evidence without changing failure."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from modules.cluster import local
from modules.common.contracts import Budget, Failure


class WorkerEvidenceTests(unittest.TestCase):
    def test_real_crash_keeps_stderr_after_temporary_inputs_are_deleted(self):
        payload = {'kind': 'scan', 'request': {}, 'scope': {'tenant': 't', 'subject': 's', 'dataset': 'd'},
                   'bundle': {'manifest': {'dataset_id': 'd'}, 'rows': [{'private': 'input-not-to-retain'}]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(Failure) as caught:
                local.fanout('modules.query.worker', [payload]*3, Budget(seconds=10), root)
            self.assertEqual(caught.exception.code, 'worker_failed')
            evidence = json.loads((root/'worker-failure.json').read_bytes())
            self.assertEqual(evidence['version'], 1)
            self.assertEqual(len(evidence['workers']), 3)
            self.assertTrue(any(item['returncode'] == 1 for item in evidence['workers']))
            logs = [path.read_bytes() for path in root.glob('*.failure.log')]
            self.assertTrue(any(b'KeyError' in raw for raw in logs))
            self.assertTrue(all(len(raw) <= 8192 and b'input-not-to-retain' not in raw for raw in logs))
            self.assertFalse(list(root.glob('shards-*')))

    def test_log_tail_is_bounded_and_diagnostic_write_failure_cannot_mask_crash(self):
        real_popen, real_put = subprocess.Popen, local.put
        command = [sys.executable, '-c', 'import sys,time; sys.stderr.buffer.write(b"x"*50000+b"CRASH_MARKER"); '
                   'sys.stderr.flush(); time.sleep(.1); sys.exit(7)']
        def crash(args, **kwargs):
            return real_popen(command, **kwargs)
        def disk_full(path, raw):
            if str(path).endswith('.failure.log'):
                raise OSError('fixture diagnostic disk full')
            return real_put(path, raw)
        with tempfile.TemporaryDirectory() as directory, patch.object(local.subprocess, 'Popen', side_effect=crash):
            root = Path(directory)
            for name in ('bounded', 'disk-full'):
                writer = disk_full if name == 'disk-full' else real_put
                with patch.object(local, 'put', side_effect=writer), self.assertRaises(Failure) as caught:
                    local.fanout('modules.query.worker', [{}, {}, {}], Budget(seconds=5), root/name)
                self.assertEqual(caught.exception.code, 'worker_failed')
            for path in (root/'bounded').glob('*.failure.log'):
                self.assertLessEqual(path.stat().st_size, 8192)
            self.assertTrue(any(b'CRASH_MARKER' in path.read_bytes() for path in (root/'bounded').glob('*.failure.log')))
            # Existing immutable diagnostics may conflict, but must not replace the query error.
            with self.assertRaises(Failure) as caught:
                local.fanout('modules.query.worker', [{}, {}, {}], Budget(seconds=5), root/'bounded')
            self.assertEqual(caught.exception.code, 'worker_failed')


if __name__ == '__main__':
    unittest.main()
