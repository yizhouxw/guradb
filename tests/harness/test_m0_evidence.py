"""M0 archive admission and driver failure tests; these are not engine evidence."""
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
import m0
from m0lib.evidence import archive
from harnesslib.policy import HarnessError


def publish(arguments):
    return str(archive(*arguments))


class M0EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.common = self.root/'common'
        self.run = self.fixture('run')

    def fixture(self, name):
        directory = self.root/name
        directory.mkdir()
        trace = [{'sequence': 0, 'action': 'container_created', 'name': 'gura-012345abcdef-0'},
                 {'sequence':1, 'action':'container_logs_collected', 'name':'gura-012345abcdef-0',
                  'returncode':0, 'sha256':hashlib.sha256(b'original container output\n').hexdigest()}]
        (directory/'trace.json').write_text(json.dumps(trace))
        (directory/'gura-012345abcdef-0.log').write_bytes(b'original container output\n')
        result = {'container_log_protocol':1, 'passed': True, 'suite': 'functional', 'git_commit': 'a'*40,
                  'checkout_digest': 'b'*64, 'dependency_lock_sha256': 'c'*64,
                  'trace_sha256': hashlib.sha256((directory/'trace.json').read_bytes()).hexdigest()}
        (directory/'result.json').write_text(json.dumps(result))
        return directory

    def test_m0_original_identity_duplicate_and_concurrent_publish(self):
        before = (self.run/'result.json').read_bytes()
        with ProcessPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(publish, [(self.common, self.run)]*8))
        self.assertEqual(len(set(paths)), 1)
        destination = Path(paths[0])
        self.assertIn('/m0-evidence/v2/', str(destination))
        original = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in destination.iterdir()}
        self.assertEqual(archive(self.common, self.fixture('repeat')), destination)
        self.assertEqual(original, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in destination.iterdir()})
        self.assertEqual((destination/'result.json').read_bytes(), before)
        manifest = json.loads((destination/'manifest.json').read_bytes())
        for name, digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((destination/name).read_bytes()).hexdigest(), digest)

    def test_missing_or_invalid_original_evidence_is_rejected_without_publication(self):
        for case in ('result', 'trace', 'log', 'trace-damage', 'identity', 'unsafe-name', 'failed', 'build-log'):
            with self.subTest(case=case):
                directory = self.fixture(case)
                result = json.loads((directory/'result.json').read_text())
                if case in ('result', 'trace', 'log'):
                    (directory/{'result':'result.json', 'trace':'trace.json', 'log':'gura-012345abcdef-0.log'}[case]).unlink()
                elif case == 'trace-damage':
                    (directory/'trace.json').write_bytes(b'[]')
                else:
                    if case == 'identity':
                        result['git_commit'] = 'unknown'
                    elif case == 'failed':
                        result['passed'] = False
                    elif case == 'build-log':
                        result['build_log_sha256'] = 'd'*64
                    else:
                        raw = json.dumps([{'sequence':0, 'action':'container_created', 'name':'../outside'}]).encode()
                        (directory/'trace.json').write_bytes(raw)
                        result['trace_sha256'] = hashlib.sha256(raw).hexdigest()
                    (directory/'result.json').write_text(json.dumps(result))
                before = {p.name:p.read_bytes() for p in directory.iterdir()}
                with self.assertRaises(HarnessError):
                    archive(self.common, directory)
                self.assertFalse(self.common.exists())
                self.assertEqual(before, {p.name:p.read_bytes() for p in directory.iterdir()})

    def test_changed_log_distinguishes_runs_and_corrupt_archive_is_never_repaired(self):
        first = archive(self.common, self.run)
        duplicate = self.fixture('changed-log')
        (duplicate/'gura-012345abcdef-0.log').write_bytes(b'another run')
        result = json.loads((duplicate/'result.json').read_text())
        result.pop('container_log_protocol')  # Historical bytes have no extraction receipt.
        (duplicate/'result.json').write_text(json.dumps(result))
        self.assertNotEqual(archive(self.common, duplicate), first)
        (first/'trace.json').write_bytes(b'corrupt preserved evidence')
        with self.assertRaises(HarnessError):
            archive(self.common, self.run)
        self.assertEqual((first/'trace.json').read_bytes(), b'corrupt preserved evidence')

    def run_driver(self, directory, driver, build_error=None, archive_error=None):
        (self.root/'Cargo.lock').write_text('fixed-lock')
        def build(*args, **kwargs):
            kwargs['stdout'].write(b'original build diagnostic\n')
            if build_error:
                raise build_error
        patches = [patch.object(m0, 'ROOT', self.root), patch.object(sys, 'argv', ['m0.py', 'functional', '--run-dir', str(directory)]),
                   patch.object(m0, 'load', return_value=({}, {})), patch.object(m0, 'checkout_digest', return_value='b'*64),
                   patch.object(m0.subprocess, 'check_output', side_effect=lambda args, **kw: str(self.common) if '--git-common-dir' in args else 'a'*40),
                   patch.object(m0.subprocess, 'run', side_effect=build), patch.object(m0.runpy, 'run_path', return_value={'run':driver})]
        from contextlib import ExitStack
        with ExitStack() as stack:
            for context in patches:
                stack.enter_context(context)
            if archive_error:
                stack.enter_context(patch.object(m0, 'archive', side_effect=archive_error))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            return m0.main()

    def test_driver_success_publishes_and_rejects_nonempty_reuse(self):
        directory = self.root/'success'
        def driver(path):
            source = self.fixture('driver-output')
            for file in source.iterdir():
                if file.name != 'result.json':
                    (path/file.name).write_bytes(file.read_bytes())
            return {'passed':True, 'suite':'functional'}
        self.assertEqual(self.run_driver(directory, driver), 0)
        self.assertTrue((archive(self.common, directory)/'build.log').exists())
        before = {p.name:p.read_bytes() for p in directory.iterdir()}
        with self.assertRaises(SystemExit):
            self.run_driver(directory, driver)
        self.assertEqual(before, {p.name:p.read_bytes() for p in directory.iterdir()})

    def test_driver_rejects_preexisting_empty_run_directory(self):
        directory = self.root/'already-owned'
        directory.mkdir()
        with self.assertRaises(SystemExit):
            self.run_driver(directory, lambda path: self.fail('driver must not start'))
        self.assertEqual(list(directory.iterdir()), [])

    def test_driver_build_and_execution_failure_preserve_diagnostics(self):
        for mode in ('build', 'driver', 'archive'):
            directory = self.root/mode
            def driver(path):
                (path/'trace.json').write_bytes(b'original partial trace')
                if mode == 'driver':
                    raise RuntimeError('injected driver error')
                return {'passed':True, 'suite':'functional'}
            result = self.run_driver(directory, driver,
                                     subprocess.CalledProcessError(1, 'build') if mode == 'build' else None,
                                     HarnessError('injected archive error') if mode == 'archive' else None)
            self.assertEqual(result, 1)
            self.assertEqual((directory/'build.log').read_bytes(), b'original build diagnostic\n')
            self.assertFalse(json.loads((directory/'failure.json').read_text())['passed'])
            if mode != 'build':
                self.assertEqual((directory/'trace.json').read_bytes(), b'original partial trace')
            self.assertFalse(self.common.exists())

    def test_new_log_protocol_rejects_incomplete_failed_or_corrupt_capture(self):
        for mode in ('receipt-missing', 'capture-failed', 'log-corrupt'):
            with self.subTest(mode=mode):
                directory = self.fixture(mode)
                trace = json.loads((directory/'trace.json').read_text())
                if mode == 'receipt-missing':
                    trace.pop()
                elif mode == 'capture-failed':
                    trace[1]['returncode'] = 1
                else:
                    (directory/'gura-012345abcdef-0.log').write_text('changed bytes')
                raw = json.dumps(trace).encode()
                (directory/'trace.json').write_bytes(raw)
                result = json.loads((directory/'result.json').read_text())
                result['trace_sha256'] = hashlib.sha256(raw).hexdigest()
                (directory/'result.json').write_text(json.dumps(result))
                with self.assertRaises(HarnessError):
                    archive(self.common, directory)
        self.assertFalse(self.common.exists())

    def test_checkout_change_during_driver_prevents_publication(self):
        directory = self.root/'code-changed'
        def driver(path):
            m0.checkout_digest.return_value = 'd'*64
            (path/'trace.json').write_bytes(b'original partial trace')
            return {'passed':True, 'suite':'functional'}
        self.assertEqual(self.run_driver(directory, driver), 1)
        self.assertIn('code changed', (directory/'failure.json').read_text())
        self.assertFalse(self.common.exists())
        self.assertFalse((directory/'result.json').exists())


if __name__ == '__main__':
    unittest.main()
