"""Pair startup failure preservation without containers, services or timed load."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.source_support import fixed_catalog_pair_runner as driver


class PairRunnerTests(unittest.TestCase):
    def test_spawn_failure_keeps_watchdog_error_and_closes_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)/'run'
            directory.mkdir()
            handles = []
            def spawn(*args, **kwargs):
                handles.extend([kwargs['stdout'], kwargs['stderr']])
                raise OSError('unit spawn failure')
            with patch.object(driver, 'ROOT', Path(temporary)), patch.object(driver.subprocess, 'Popen', side_effect=spawn):
                self.assertEqual(driver.bounded(directory), 1)
            self.assertTrue(all(handle.closed for handle in handles))
            watchdog = json.loads((directory/'watchdog.json').read_text())
            self.assertEqual(watchdog['primary_error']['error_class'], 'OSError')
            self.assertIsNone(watchdog['worker_returncode'])
            self.assertFalse(json.loads((directory/'failure.json').read_text())['cleanup_confirmed'])

    def test_initial_identity_failure_preserves_ownership_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)/'run'
            directory.mkdir()
            with patch('scripts.fixed_sources_acceptance.identity', side_effect=OSError('unit identity failure')):
                self.assertEqual(driver.run(directory), 1)
            record = json.loads((directory/'failure.json').read_text())
            self.assertEqual(record['primary_error']['error_class'], 'OSError')
            owner = json.loads((directory/'owned-resources.json').read_text())
            self.assertEqual(owner['container_attempts'], [])
            self.assertEqual(owner['network_attempts'], [])
            self.assertFalse(owner['cleanup_confirmed'])
            self.assertIsNone(record['identity_before'])


if __name__ == '__main__':
    unittest.main()
