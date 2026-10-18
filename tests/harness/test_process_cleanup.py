"""Real process-group cleanup, including macOS unreaped zombie behavior."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib import runner as executor


@unittest.skipUnless(os.name == 'posix', 'process groups require POSIX')
class ProcessCleanupTests(unittest.TestCase):
    def cleanup(self, process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # Test teardown only: always reap the owned child. Assertions below
            # validate the production helper without swallowing its errors.
            if process.poll() is None:
                process.kill()
        process.wait(timeout=5)

    def test_live_leader_and_exited_leader_both_kill_helpers(self):
        for live_leader in (True, False):
            with self.subTest(live_leader=live_leader), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                marker, ready = root/'leaked', root/'ready'
                helper = f'import time,pathlib; time.sleep(.5); pathlib.Path({str(marker)!r}).write_text("leaked")'
                command = ('import subprocess,sys,pathlib,time; '
                           f'subprocess.Popen([sys.executable,"-c",{helper!r}]); '
                           f'pathlib.Path({str(ready)!r}).write_text("ready"); '
                           + ('time.sleep(30)' if live_leader else ''))
                process = subprocess.Popen([sys.executable, '-c', command], start_new_session=True)
                try:
                    deadline = time.monotonic() + 3
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(.005)
                    self.assertTrue(ready.exists())
                    if not live_leader:
                        self.assertEqual(process.wait(timeout=3), 0)
                    executor.stop_group(process)
                    self.assertIsNotNone(process.returncode)
                    time.sleep(.6)
                    self.assertFalse(marker.exists(), 'native helper survived cleanup')
                finally:
                    self.cleanup(process)

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS zombie-only killpg EPERM regression')
    def test_unreaped_zombie_group_is_reaped_without_permission_failure(self):
        process = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
        try:
            # getpgid reports ESRCH for Darwin zombies without reaping them.
            # Do not poll/wait before stop_group: that would hide the defect.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.getpgid(process.pid)
                except ProcessLookupError:
                    break
                time.sleep(.005)
            else:
                self.fail('owned child did not become an unreaped zombie')
            self.assertIsNone(process.returncode)
            executor.stop_group(process)
            self.assertEqual(process.returncode, 0)
        finally:
            self.cleanup(process)

    def test_exit_transition_waits_when_nonblocking_poll_cannot_reap(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        kill_group = os.killpg
        first = True

        def exiting_group(pid, sig):
            nonlocal first
            if first:
                first = False
                # Model the observed OS ordering: termination has begun,
                # killpg says EPERM, and WNOHANG still cannot reap the leader.
                os.kill(pid, signal.SIGTERM)
                raise PermissionError('owned child is exiting')
            return kill_group(pid, sig)

        try:
            with patch.object(process, 'poll', return_value=None), patch.object(executor.os, 'killpg', side_effect=exiting_group):
                executor.stop_group(process)
            self.assertEqual(process.returncode, -signal.SIGTERM)
        finally:
            self.cleanup(process)

    def test_live_permission_error_is_not_suppressed(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        try:
            with patch.object(executor.os, 'killpg', side_effect=PermissionError('denied')):
                with self.assertRaises(PermissionError):
                    executor.stop_group(process)
            self.assertIsNone(process.poll())
        finally:
            self.cleanup(process)

    def test_permission_error_for_remaining_group_is_not_suppressed(self):
        process = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
        process.wait(timeout=3)
        with patch.object(executor.os, 'killpg', side_effect=PermissionError('denied helper group')):
            with self.assertRaises(PermissionError):
                executor.stop_group(process)


if __name__ == '__main__':
    unittest.main()
