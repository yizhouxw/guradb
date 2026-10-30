"""Install protocol negatives with tiny nonexecuted ELF-shaped payloads."""
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import time
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('preview_install', ROOT/'scripts/preview_install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class PreviewInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive(self, version=1, architecture='linux-arm64', bad_hash=False, extra=None, executable=False):
        elf = bytearray(64)
        elf[:6] = b'\x7fELF\x02\x01'
        elf[18:20] = (183).to_bytes(2, 'little')
        files = {'bin/guradb': b'#!/bin/sh\n', 'lib/engine': bytes(elf),
                 'lib/launcher.py': b'# fixture, never executed\n', 'lib/capabilities.json': b'{}'}
        rows = {k: {'bytes': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for k, v in files.items()}
        if bad_hash:
            rows['lib/engine']['sha256'] = '0'*64
        m = {'format_version': version, 'host': 'darwin-arm64', 'engine_arch': architecture,
             'runtime_image': 'sha256:'+'a'*64, 'files': rows}
        path = self.root/('archive-'+str(len(list(self.root.iterdir())))+'.pyz')
        with zipfile.ZipFile(path, 'x') as z:
            z.writestr('__main__.py', (ROOT/'scripts/preview_install.py').read_bytes() if executable else b'# fixture\n')
            z.writestr('payload/manifest.json', json.dumps(m))
            for name, value in files.items():
                z.writestr('payload/'+name, value)
            if extra:
                z.writestr(extra, b'outside')
        return path, installer.digest(path)

    def test_fresh_atomic_prefix_and_no_overwrite(self):
        path, sha = self.archive()
        prefix = self.root/'new prefix'
        value = installer.install(path, sha, prefix)
        self.assertEqual(value['installed'], str(prefix))
        before = {str(p.relative_to(prefix)): p.read_bytes() for p in prefix.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'must not exist'):
            installer.install(path, sha, prefix)
        self.assertEqual(before, {str(p.relative_to(prefix)): p.read_bytes() for p in prefix.rglob('*') if p.is_file()})
        self.assertEqual(list(self.root.glob('.guradb-install-*')), [])

    def test_empty_directory_and_symlink_targets_untouched(self):
        path, sha = self.archive()
        empty = self.root/'empty'
        empty.mkdir()
        link = self.root/'link'
        link.symlink_to(empty, target_is_directory=True)
        for prefix in (empty, link):
            with self.assertRaisesRegex(ValueError, 'must not exist'):
                installer.install(path, sha, prefix)
        self.assertTrue(link.is_symlink())
        self.assertEqual(list(empty.iterdir()), [])

    def test_committed_prefix_term_does_not_block_on_final_stdout_flush(self):
        path, sha = self.archive(executable=True)
        prefix = self.root/'committed'
        rd, wr = os.pipe()
        proc = None
        try:
            os.set_blocking(wr, False)
            try:
                while True:
                    os.write(wr, b'x'*4096)
            except BlockingIOError:
                pass
            os.set_blocking(wr, True)
            proc = subprocess.Popen(['/usr/bin/python3', str(path), 'install', '--sha256', sha,
                                     '--prefix', str(prefix)], stdout=wr, stderr=subprocess.PIPE)
            os.close(wr)
            wr = None
            until = time.monotonic()+3
            while not prefix.exists() and time.monotonic() < until:
                time.sleep(.01)
            self.assertTrue(prefix.is_dir())
            proc.send_signal(signal.SIGTERM)
            self.assertEqual(proc.wait(timeout=2), 143)
            self.assertEqual(list(self.root.glob('.guradb-install-*')), [])
            self.assertTrue((prefix/'manifest.json').is_file())
        finally:
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=2)
                proc.stderr.close()
            os.close(rd)
            if wr is not None:
                os.close(wr)

    def test_hash_version_architecture_layout_and_payload_refuse_cleanly(self):
        variants = [self.archive(), self.archive(version=2), self.archive(version=True), self.archive(architecture='linux-amd64'),
                    self.archive(bad_hash=True), self.archive(extra='../escaped')]
        for i, (path, sha) in enumerate(variants):
            if i == 0:
                sha = '0'*64
            prefix = self.root/('bad-'+str(i))
            with self.assertRaises(ValueError):
                installer.install(path, sha, prefix)
            self.assertFalse(prefix.exists())
            self.assertEqual(list(self.root.glob('.guradb-install-*')), [])
        self.assertFalse((self.root.parent/'escaped').exists())


if __name__ == '__main__':
    unittest.main()
