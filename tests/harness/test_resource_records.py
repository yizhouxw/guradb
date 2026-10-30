"""Real private filesystem truth; resource records grant no deletion authority."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from harnesslib import resource_records as rr


class ResourceRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def owner(self):
        package = self.root / 'retained.pyz'
        package.write_bytes(b'zip-bytes')
        consumer = self.root / 'consumer'
        consumer.mkdir()
        (consumer / 'copied.pyz').write_bytes(b'zip-bytes')
        for name, content in [('prefix', b'installed'), ('data', b'dataset'), ('observer', b'observation')]:
            directory = consumer / name
            directory.mkdir()
            (directory / 'file').write_bytes(content)
        components = [
            {'role': 'retained_package', 'snapshot': rr.snapshot(package)},
            {'role': 'consumer_tree', 'snapshot': rr.snapshot(consumer)},
        ]
        return rr.account('private-test', components, package, consumer)

    def test_full_consumer_zip_prefix_data_observer_and_retained_package_count(self):
        value = self.owner()
        self.assertEqual(value['totals']['logical_file_bytes'], 9 + 9 + 9 + 7 + 11)
        self.assertEqual(value['totals']['unique_inode_file_bytes'], 45)
        self.assertEqual(value['totals']['files'], 5)
        self.assertEqual(rr.validate_owner(value)['historical_peak'], 'UNKNOWN')
        self.assertFalse(value['deletion_authorized'])
        partial = copy.deepcopy(value)
        partial['components'][1]['snapshot'] = rr.snapshot(self.root / 'consumer' / 'prefix')
        with self.assertRaises(rr.RecordError):
            rr.validate_owner(partial)
        incomplete = copy.deepcopy(value)
        incomplete['components'].pop()
        with self.assertRaises(rr.RecordError):
            rr.validate_owner(incomplete)

    def test_invalid_old_version_type_incomplete_owner_never_changes_private_files(self):
        value = self.owner()
        watched = self.root / 'consumer' / 'copied.pyz'
        original = (watched.read_bytes(), rr.metadata(watched.lstat()))
        invalid = [{}, {'pass': True}, {'schema_version': 999}, []]
        for key, wrong in [('schema_version', True), ('schema_version', 2), ('owner', None),
                           ('status', 'exited'), ('historical_peak', 1), ('scope', 'whole_project'),
                           ('attribution', 'owned'), ('deletion_authorized', True)]:
            changed = copy.deepcopy(value)
            changed[key] = wrong
            invalid.append(changed)
        missing = copy.deepcopy(value)
        del missing['owner']
        invalid.append(missing)
        boolean_count = copy.deepcopy(value)
        boolean_count['components'][0]['snapshot']['totals']['directories'] = False
        invalid.append(boolean_count)
        partial = copy.deepcopy(value)
        partial['components'][1]['snapshot']['status'] = 'partial'
        invalid.append(partial)
        contradictory = copy.deepcopy(value)
        contradictory['totals']['logical_file_bytes'] += 1
        invalid.append(contradictory)
        for record in invalid:
            with self.assertRaises(rr.RecordError):
                rr.validate_owner(record)
            self.assertEqual((watched.read_bytes(), rr.metadata(watched.lstat())), original)

    def test_hardlink_path_bytes_unique_inode_bytes_symlink_never_follows_target(self):
        tree = self.root / 'tree'
        tree.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'secret').write_bytes(b'not-in-scope')
        (tree / 'one').write_bytes(b'123')
        os.link(tree / 'one', tree / 'two')
        (tree / 'link').symlink_to(outside, target_is_directory=True)
        value = rr.validate_snapshot(rr.snapshot(tree))
        self.assertEqual(value['totals']['logical_file_bytes'], 6)
        self.assertEqual(value['totals']['unique_inode_file_bytes'], 3)
        self.assertEqual(value['totals']['symlinks'], 1)
        self.assertEqual({e['path'] for e in value['entries']}, {'one', 'two', 'link'})
        self.assertEqual(next(e for e in value['entries'] if e['type'] == 'symlink')['target'], str(outside))
        with self.assertRaises((OSError, rr.RecordError)):
            rr.snapshot(tree / 'link')

    def test_diff_new_replaced_growth_removed_and_same_size_metadata_change(self):
        tree = self.root / 'tree'
        tree.mkdir()
        for name in ['growth', 'replacement', 'removed', 'same-size']:
            (tree / name).write_bytes(b'aa')
        before = rr.snapshot(tree)
        old_inode = (tree / 'replacement').stat().st_ino
        (tree / 'staged').write_bytes(b'bb')
        os.replace(tree / 'staged', tree / 'replacement')
        self.assertNotEqual((tree / 'replacement').stat().st_ino, old_inode)
        with (tree / 'growth').open('ab') as out:
            out.write(b'bbb')
        (tree / 'removed').unlink()
        (tree / 'new').write_bytes(b'new')
        (tree / 'same-size').chmod(0o600)
        after = rr.snapshot(tree)
        result = rr.compare(before, after)
        expected = {'new': 'new', 'removed': 'removed', 'replaced': 'replacement',
                    'same_inode_growth': 'growth', 'metadata_changed': 'same-size'}
        for category, name in expected.items():
            self.assertEqual([e['path'] for e in result['changes'][category]], [name])
            self.assertEqual(result['changes'][category][0]['attribution'], 'unattributed')
        self.assertEqual(result['historical_peak'], 'UNKNOWN')
        self.assertFalse(result['deletion_authorized'])
        renamed = self.root / 'renamed'
        tree.rename(renamed)
        current = rr.snapshot(renamed)
        with self.assertRaises(rr.RecordError):
            rr.compare(after, current)
        self.assertTrue(rr.compare(after, current, True)['root_renamed'])

    def test_bounds_and_output_inside_root_existing_output_no_partial_complete(self):
        tree = self.root / 'tree'
        tree.mkdir()
        (tree / 'one').write_bytes(b'keep')
        (tree / 'sub').mkdir()
        (tree / 'sub' / 'child').write_bytes(b'child')
        for options in [{'max_entries': 1}, {'max_depth': 1}, {'max_bytes': 1}, {'timeout': 0}]:
            with self.assertRaises(rr.RecordError):
                rr.snapshot(tree, **options)
        value = rr.snapshot(tree)
        with self.assertRaises(rr.RecordError):
            rr.write_new(tree / 'out.json', value, [tree])
        self.assertFalse((tree / 'out.json').exists())
        alias = self.root / 'out-alias'
        alias.symlink_to(tree, target_is_directory=True)
        with self.assertRaises(OSError):
            rr.write_new(alias / 'out.json', value, [tree])
        self.assertFalse((tree / 'out.json').exists())
        out = self.root / 'out.json'
        out.write_bytes(b'previous')
        with self.assertRaises(FileExistsError):
            rr.write_new(out, value, [tree])
        self.assertEqual(out.read_bytes(), b'previous')
        self.assertEqual((tree / 'one').read_bytes(), b'keep')

    def test_account_cli_validates_complete_roots_and_refuses_output_alias_inside_consumer(self):
        value = self.owner()
        files = []
        for index, component in enumerate(value['components']):
            path = self.root / f'snapshot-{index}.json'
            path.write_bytes(rr.encode(component['snapshot']))
            files.extend(['--component', f"{component['role']}={path}"])
        command = [sys.executable, str(Path(__file__).resolve().parents[2] / 'scripts/harness.py'),
                   'resources', 'account', '--owner', 'cli-test',
                   '--retained-package', value['declared_roots']['retained_package'],
                   '--consumer-root', value['declared_roots']['consumer_tree'], *files]
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        output = self.root / 'account.json'
        result = subprocess.run(command + ['--out', str(output)], capture_output=True, text=True, env=env, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(rr.validate_owner(rr.read_record(output))['totals']['files'], 5)
        alias = self.root / 'alias'
        alias.symlink_to(self.root / 'consumer', target_is_directory=True)
        result = subprocess.run(command + ['--out', str(alias / 'injected.json')], capture_output=True, text=True, env=env, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertFalse((self.root / 'consumer' / 'injected.json').exists())

    def test_oversized_sparse_record_is_rejected_before_any_content_read(self):
        sparse = self.root / 'oversized.json'
        with sparse.open('wb') as output:
            output.truncate(rr.MAX_BYTES + 1)
        self.assertEqual(sparse.stat().st_size, rr.MAX_BYTES + 1)
        original_fdopen = os.fdopen
        read_calls = []
        def protect(fd, mode):
            source = original_fdopen(fd, mode)
            class Guard:
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    source.close()
                def fileno(self):
                    return source.fileno()
                def read(self, *args):
                    read_calls.append(args)
                    raise AssertionError('oversized record content was read')
            return Guard()
        with mock.patch.object(rr.os, 'fdopen', side_effect=protect):
            with self.assertRaisesRegex(rr.RecordError, 'byte limit exceeded before read'):
                rr.read_record(sparse)
        self.assertEqual(read_calls, [])
        self.assertEqual(sparse.stat().st_size, rr.MAX_BYTES + 1)

    def test_cli_structured_invalid_json_duplicate_keys_and_normalized_owner(self):
        value = self.owner()
        path = self.root / 'owner.json'
        path.write_bytes(rr.encode(value))
        self.assertEqual(rr.validate_owner(rr.read_record(path)), value)
        path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaises(rr.RecordError):
            rr.read_record(path)
        path.write_text('{"pass":true}')
        command = [sys.executable, str(Path(__file__).resolve().parents[2] / 'scripts/harness.py'),
                   'resources', 'validate', '--record', str(path)]
        result = subprocess.run(command, capture_output=True, text=True,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(json.loads(result.stderr)['status'], 'rejected')
        self.assertEqual(path.read_text(), '{"pass":true}')


if __name__ == '__main__':
    unittest.main()
