"""Acceptance archival contracts use independent synthetic evidence, no engine claims."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from harnesslib.acceptance_archive import archive_run
from harnesslib.policy import HarnessError


class AcceptanceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.common = self.root/'git-common'
        self.run = self.fixture('run')

    def fixture(self, name, trace=b'{"run":"first"}\n', logfile='nested/container-a.log'):
        directory = self.root/name
        directory.mkdir()
        (directory/'result.json').write_bytes(b'{"passed":true,"code":"fixed"}\n')
        if trace is not None:
            (directory/'trace.json').write_bytes(trace)
        if logfile:
            path = directory/logfile
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'actual fixture log\n')
        return directory

    def archive(self, directory=None):
        return archive_run(self.common, 'm1', directory or self.run)

    def snapshot(self, directory):
        return {p.relative_to(directory).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in directory.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_complete_replay_reuses_archive_without_modifying_old_files(self):
        destination = self.archive()
        before = self.snapshot(destination)
        duplicate = self.fixture('duplicate')
        self.assertEqual(self.archive(duplicate), destination)
        self.assertEqual(self.snapshot(destination), before)
        manifest_raw = (destination/'manifest.json').read_bytes()
        self.assertEqual(destination.name, hashlib.sha256(manifest_raw).hexdigest())
        manifest = json.loads(manifest_raw)
        self.assertEqual(set(manifest['files']), {'result.json', 'trace.json', 'nested/container-a.log'})
        for name, checksum in manifest['files'].items():
            self.assertEqual(hashlib.sha256((destination/name).read_bytes()).hexdigest(), checksum)

    def test_same_result_with_different_trace_or_log_is_a_distinct_execution(self):
        first = self.archive()
        original = self.snapshot(first)
        cases = [self.fixture('different-trace', trace=b'{"run":"different-path"}\n'),
                 self.fixture('different-log-name', logfile='nested/container-b.log'),
                 self.fixture('different-log-bytes')]
        (cases[-1]/'nested/container-a.log').write_bytes(b'different execution output\n')
        destinations = {first}
        for case in cases:
            self.assertEqual((case/'result.json').read_bytes(), (self.run/'result.json').read_bytes())
            destinations.add(self.archive(case))
        self.assertEqual(len(destinations), 4)
        self.assertEqual(self.snapshot(first), original)

    def test_concurrent_publish_converges_on_one_complete_immutable_archive(self):
        runs = [self.fixture('parallel-'+str(n)) for n in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            destinations = list(pool.map(self.archive, runs))
        self.assertEqual(len(set(destinations)), 1)
        destination = destinations[0]
        before = self.snapshot(destination)
        self.assertEqual(self.archive(), destination)
        self.assertEqual(self.snapshot(destination), before)
        self.assertFalse(list(destination.parent.glob('.staging-*')))

    def test_existing_damage_missing_extra_or_symlink_fails_without_repair(self):
        for damage in ('changed', 'missing', 'extra', 'empty-directory', 'symlink', 'manifest'):
            with self.subTest(damage=damage):
                common = self.root/('common-'+damage)
                destination = archive_run(common, 'm1', self.run)
                path = destination/'nested/container-a.log'
                if damage == 'changed':
                    path.write_bytes(b'corrupted')
                elif damage == 'missing':
                    path.unlink()
                elif damage == 'extra':
                    (destination/'extra.log').write_bytes(b'unrecorded')
                elif damage == 'empty-directory':
                    (destination/'unexpected').mkdir()
                elif damage == 'symlink':
                    path.unlink()
                    path.symlink_to(self.run/'nested/container-a.log')
                else:
                    (destination/'manifest.json').write_bytes(b'corrupt manifest')
                before = self.snapshot(destination)
                paths_before = sorted(p.relative_to(destination).as_posix() for p in destination.rglob('*'))
                with self.assertRaises(HarnessError):
                    archive_run(common, 'm1', self.run)
                self.assertEqual(self.snapshot(destination), before)
                self.assertEqual(sorted(p.relative_to(destination).as_posix() for p in destination.rglob('*')), paths_before)
                if damage == 'symlink':
                    self.assertTrue(path.is_symlink())

    def test_result_required_optional_trace_and_source_symlink_rejected(self):
        without_trace = self.fixture('without-trace', trace=None, logfile=None)
        destination = self.archive(without_trace)
        self.assertEqual(set(json.loads((destination/'manifest.json').read_bytes())['files']), {'result.json'})
        (without_trace/'result.json').unlink()
        with self.assertRaises(HarnessError):
            self.archive(without_trace)
        (self.run/'trace.json').unlink()
        (self.run/'trace.json').symlink_to(destination/'result.json')
        with self.assertRaises(HarnessError):
            self.archive()

    def test_symlinked_source_directory_or_archive_parent_is_not_followed(self):
        outside = self.root/'outside'
        outside.mkdir()
        (outside/'trace.json').write_bytes(b'outside evidence')
        link = self.run/'linked-directory'
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HarnessError):
            self.archive()
        link.unlink()
        self.common.mkdir()
        (self.common/'guradb').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HarnessError):
            self.archive()
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['trace.json'])

    def test_failed_staging_is_not_published_and_legacy_archive_is_untouched(self):
        legacy = self.common/'guradb'/'m1-evidence'/'legacy-result-hash'
        legacy.mkdir(parents=True)
        (legacy/'result.json').write_bytes(b'legacy evidence')
        before = self.snapshot(legacy)
        with patch('harnesslib.acceptance_archive._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.archive()
        base = legacy.parent/'v2'
        self.assertEqual([p.name for p in base.iterdir()], ['.publish.lock'])
        destination = self.archive()
        self.assertTrue(destination.is_dir())
        self.assertEqual(self.snapshot(legacy), before)


if __name__ == '__main__':
    unittest.main()
