"""Container log collection order and failure preservation without Docker."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from m0lib.kit import Lab


class M0LogCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.lab = Lab.__new__(Lab)
        self.lab.directory = Path(self.temp.name)
        self.lab.names = ['gura-012345abcdef-0']
        self.lab.removed = set()
        self.lab.trace = []
        self.lab.network = 'isolated-test-network'
        self.calls = []

    def docker(self, *args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'final output' if args[0] == 'logs' else '', '')

    def test_collects_before_remove_and_close_does_not_overwrite(self):
        name = self.lab.names[0]
        with patch('m0lib.kit.docker', side_effect=self.docker):
            self.lab.remove(name)
            path = self.lab.directory/(name+'.log')
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            self.lab.close()
        self.assertEqual([call[0] for call in self.calls], ['unpause', 'kill', 'logs', 'rm', 'network'])
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(self.lab.trace[0]['returncode'], 0)

    def test_nonzero_log_capture_preserves_error_and_container(self):
        def docker(*args, **kwargs):
            self.calls.append(args)
            return subprocess.CompletedProcess(args, 1 if args[0] == 'logs' else 0, '', 'capture unavailable')
        with patch('m0lib.kit.docker', side_effect=docker):
            with self.assertRaisesRegex(RuntimeError, 'preserve container'):
                self.lab.close()
        self.assertNotIn('rm', [call[0] for call in self.calls])
        self.assertEqual((self.lab.directory/(self.lab.names[0]+'.log')).read_text(), 'capture unavailable')
        self.assertEqual(self.lab.removed, set())
        self.assertEqual(self.lab.trace[0]['returncode'], 1)

    def test_timeout_keeps_container_and_successful_empty_log_is_valid(self):
        def docker(*args, **kwargs):
            self.calls.append(args)
            if args[0] == 'logs':
                raise subprocess.TimeoutExpired(args, 120)
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch('m0lib.kit.docker', side_effect=docker):
            with self.assertRaises(RuntimeError):
                self.lab.close()
        self.assertNotIn('rm', [call[0] for call in self.calls])
        self.assertEqual(self.lab.removed, set())
        with patch('m0lib.kit.docker', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.lab.close()
        self.assertEqual((self.lab.directory/(self.lab.names[0]+'.log')).read_bytes(), b'')

    def test_failed_kill_requires_confirmed_stopped_container(self):
        for state in ('true', 'unknown', 'false'):
            self.calls = []
            def docker(*args, **kwargs):
                self.calls.append(args)
                if args[0] == 'kill':
                    return subprocess.CompletedProcess(args, 1, '', 'not killed')
                if args[0] == 'inspect':
                    return subprocess.CompletedProcess(args, 1 if state == 'unknown' else 0, state, '')
                return subprocess.CompletedProcess(args, 0, '', '')
            with self.subTest(state=state), patch('m0lib.kit.docker', side_effect=docker):
                if state == 'false':
                    self.lab.close()
                    self.assertIn('logs', [call[0] for call in self.calls])
                else:
                    with self.assertRaisesRegex(RuntimeError, 'stop not confirmed'):
                        self.lab.close()
                    self.assertNotIn('logs', [call[0] for call in self.calls])
                    self.assertNotIn('rm', [call[0] for call in self.calls])


if __name__ == '__main__':
    unittest.main()
