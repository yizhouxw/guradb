import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('cargo_cache_under_test', Path(__file__).resolve().parents[2] / 'scripts/cargo.py')
CARGO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CARGO)


class CargoCheckCacheTests(unittest.TestCase):
    def test_only_new_unpaired_check_metadata_exits(self):
        with tempfile.TemporaryDirectory() as name, mock.patch.object(CARGO, 'ROOT', Path(name)):
            deps = Path(name) / 'target/debug/deps'
            deps.mkdir(parents=True)
            old = deps / 'libold.rmeta'
            old.write_bytes(b'old')
            before = CARGO.cache_metadata()
            old.write_bytes(b'changed old remains borrowed')
            check = deps / 'libcheck.rmeta'
            check.write_bytes(b'check')
            build = deps / 'libbuild.rmeta'
            build.write_bytes(b'build')
            build.with_suffix('.rlib').write_bytes(b'paired library')
            link = deps / 'liblink.rmeta'
            link.symlink_to(old.name)
            with mock.patch('builtins.print'):
                CARGO.finish_check_metadata(before)
            self.assertFalse(check.exists())
            self.assertEqual(old.read_bytes(), b'changed old remains borrowed')
            self.assertTrue(build.exists())
            self.assertTrue(build.with_suffix('.rlib').exists())
            self.assertTrue(link.is_symlink())

    def test_identity_change_refuses_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as name, mock.patch.object(CARGO, 'ROOT', Path(name)):
            deps = Path(name) / 'target/debug/deps'
            deps.mkdir(parents=True)
            path = deps / 'libcheck.rmeta'
            path.write_bytes(b'first')
            real = CARGO.metadata
            calls = 0
            def changed(p):
                nonlocal calls
                calls += 1
                if calls == 2:
                    p.write_bytes(b'changed after collection')
                return real(p)
            with mock.patch.object(CARGO, 'metadata', side_effect=changed), self.assertRaises(RuntimeError):
                CARGO.finish_check_metadata({})
            self.assertTrue(path.exists())

    def test_linked_target_is_refused(self):
        with tempfile.TemporaryDirectory() as name, mock.patch.object(CARGO, 'ROOT', Path(name)):
            root = Path(name)
            (root / 'real').mkdir()
            (root / 'target').symlink_to('real')
            with self.assertRaises(RuntimeError):
                CARGO.cache_metadata()

    def test_failed_clippy_keeps_failure_artifacts(self):
        result = mock.Mock(returncode=7)
        with mock.patch.object(CARGO.subprocess, 'check_output', return_value=CARGO.IMAGE + ' linux arm64'), \
                mock.patch.object(CARGO.subprocess, 'run', return_value=result) as execute, \
                mock.patch.object(CARGO, 'cache_metadata', return_value={}), \
                mock.patch.object(CARGO, 'finish_check_metadata') as finish, \
                mock.patch('builtins.print'):
            self.assertEqual(CARGO.run(['clippy', '--workspace', '--locked']), 7)
            finish.assert_not_called()
            argv = execute.call_args.args[0]
            self.assertIn('CARGO_BUILD_JOBS=1', argv)
            self.assertIn('CARGO_NET_OFFLINE=true', argv)
            self.assertIn('--network', argv)
            self.assertIn('--locked', argv)

    def test_dangling_library_pair_is_conservatively_preserved(self):
        with tempfile.TemporaryDirectory() as name, mock.patch.object(CARGO, 'ROOT', Path(name)):
            deps = Path(name) / 'target/debug/deps'
            deps.mkdir(parents=True)
            path = deps / 'libbuild-hash.rmeta'
            path.write_bytes(b'uncertain build metadata')
            library = path.with_suffix('.rlib')
            library.symlink_to('missing-library')
            with mock.patch('builtins.print'):
                CARGO.finish_check_metadata({})
            self.assertTrue(path.is_file())
            self.assertTrue(library.is_symlink())
