"""Offline preparation write-scope and exact-record regressions."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('projected_prepare_tests', ROOT/'scripts/prepare_projected_parquet.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class ProjectedPreparation(unittest.TestCase):
    def data(self, root):
        rows = [{'id': i, 'text': None if i == 2 else 'row'+str(i), 'active': bool(i % 2)} for i in range(6)]
        table = pa.Table.from_pylist(rows, schema=pa.schema([('id', pa.int64()), ('text', pa.string()), ('active', pa.bool_())]))
        source = root/'input.parquet'
        pq.write_table(table, source)
        return source, rows

    def args(self, source, out):
        return SimpleNamespace(input=str(source), out=str(out), columns='0,2', row_groups='0,2',
                               origin='http://127.0.0.1:38081', key='metadata/v1/records.parquet', etag='"fixed-v1"')

    def test_prepare_preserves_every_record_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, rows = self.data(root)
            out = root/'prepared'
            cost = prepare.prepare(self.args(source, out))
            self.assertEqual(pq.read_table(out/'data.parquet').to_pylist(), rows)
            self.assertEqual(cost['input_full_rows'], 6)
            self.assertEqual(cost['planned_consumer_GETs'], 6)
            original = {p.name: p.read_bytes() for p in out.iterdir()}
            with self.assertRaises(ValueError):
                prepare.prepare(self.args(source, out))
            self.assertEqual(original, {p.name: p.read_bytes() for p in out.iterdir()})

    def test_linked_parent_and_parent_traversal_never_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, _ = self.data(root)
            target = root/'target'
            target.mkdir()
            sentinel = target/'sentinel'
            sentinel.write_bytes(b'unchanged')
            before = sentinel.stat()
            link = root/'parent-link'
            link.symlink_to(target, target_is_directory=True)
            for out in (link/'escaped', root/'target'/'..'/'escaped'):
                with self.assertRaises(ValueError):
                    prepare.prepare(self.args(source, out))
            self.assertEqual(list(target.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b'unchanged')
            self.assertEqual(sentinel.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertFalse((root/'escaped').exists())


if __name__ == '__main__':
    unittest.main()
