"""Real native-process cancellation and immutable Lance mapping contracts."""
import os
from contextlib import chdir
from pathlib import Path
import sys
import tempfile
import time
import unittest

from modules.common.contracts import Budget, Failure, key
from modules.common.process import run_process
from modules.index.ann import build, candidates


class ANNContract(unittest.TestCase):
    def test_live_native_cancellation_and_timeout_reap(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/'pid'
            script = 'import os,pathlib,time; pathlib.Path('+repr(str(marker))+').write_text(str(os.getpid())); time.sleep(60)'
            for code in ('cancelled', 'timeout'):
                marker.unlink(missing_ok=True)
                budget = Budget(cancelled=marker.exists if code == 'cancelled' else lambda: False,
                                seconds=2 if code == 'timeout' else 10)
                started = time.monotonic()
                with self.assertRaises(Failure) as caught:
                    run_process([sys.executable, '-c', script], {}, budget)
                self.assertEqual(caught.exception.code, code)
                self.assertTrue(marker.exists(), 'cancellation must occur inside live worker')
                self.assertLess(time.monotonic()-started, 4)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(marker.read_text()), 0)

    def test_native_failure_and_byte_limits(self):
        for script, code in [('raise RuntimeError("native boom")', 'native_failed'),
                             ('import pathlib,sys; pathlib.Path(sys.argv[-1]).write_text("x" * (33554433))', 'resource_limit')]:
            with self.assertRaises(Failure) as caught:
                run_process([sys.executable, '-c', script], {}, Budget())
            self.assertEqual(caught.exception.code, code)

    def test_real_lance_mapping_delete_rebuild(self):
        rows = [{'logical_key': key(i, 'long'), 'vector': [float(i), float(i % 3)]} for i in range(32)]
        model = {'dimension': 2, 'model': 'test-space', 'metric': 'squared_l2', 'preprocessing': 'identity-v1'}
        with tempfile.TemporaryDirectory() as directory:
            def prepare(name, facts, revision):
                index = build(Path(directory)/name, facts, revision, model, {'partitions': 1}, Budget(seconds=30))
                self.assertTrue(0 < index['native_rss_bytes'] <= 512 << 20)
                return {'ann': index, 'revision': revision, 'model': model, 'rows': facts}
            with chdir(directory):
                old = prepare('old', rows, 'rev-old')
            query = [7.0, 1.0]
            ranked, costs = candidates(old, query, {r['logical_key'] for r in rows}, 4, 1, Budget())
            self.assertTrue(0 < costs['native_rss_bytes'] <= 512 << 20)
            expected = sorted([(r['logical_key'], -sum((a-b)**2 for a,b in zip(r['vector'], query)))
                               for r in rows], key=lambda r: (-r[1], r[0]))[:4]
            self.assertEqual(ranked, expected)
            deleted = rows[7]['logical_key']
            remaining = [r for r in reversed(rows) if r['logical_key'] != deleted]
            new = prepare('new', remaining, 'rev-new')
            hits, _ = candidates(new, query, {r['logical_key'] for r in remaining}, 4, 1, Budget())
            self.assertNotIn(deleted, {key for key, _ in hits})
            # Old immutable view still retains its identity/version mapping after rebuild.
            old_hits, _ = candidates(old, query, {r['logical_key'] for r in rows}, 1, 1, Budget())
            self.assertEqual(old_hits[0][0], deleted)
            wrong = dict(new, revision='wrong-revision')
            with self.assertRaises(Failure) as caught:
                candidates(wrong, query, {r['logical_key'] for r in remaining}, 4, 1, Budget())
            self.assertEqual(caught.exception.code, 'source_invalid')


if __name__ == '__main__':
    unittest.main()
