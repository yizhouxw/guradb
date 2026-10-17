"""Real local process searches retain global candidate/ranking semantics."""
from pathlib import Path
import tempfile
import math
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.contracts import Budget, Failure, key, digest
from modules.index.retrieval import build, search
from modules.index.ann import build as build_ann
from modules.index.shards import build as build_shards
from modules.query.distributed import execute
from modules.query.worker import execute as worker_execute


class DistributedContract(unittest.TestCase):
    def test_real_indexes_global_ranks_empty_shards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [{'logical_key': key(i, 'long'), 'values': {'id': i, 'body': 'alpha ' * (i % 7 + 1) + 'beta', 'active': i % 2 == 0},
                     'vector': [float(i), float(i % 3)], 'media': [], 'record_version': 'stable'} for i in range(96)]
            bundle = {'revision': 'rev', 'context': {'view': 'fixed'}, 'retention_mode': 'managed-copy',
                      'model': {'model': 'space', 'dimension': 2, 'metric': 'squared_l2', 'preprocessing': 'identity-v1'},
                      'manifest': {'dataset_id': 'dataset', 'files': [], 'schema': [
                          {'name': 'id', 'data_type': 'int8'}, {'name': 'body', 'data_type': 'text'},
                          {'name': 'active', 'data_type': 'bool'}]}, 'rows': rows,
                      'index_path': str(root/'text')}
            bundle['index_files'] = build(root/'text', rows, 'body', Budget())
            bundle['ann'] = build_ann(root/'ann', rows, 'rev', bundle['model'], {'partitions': 2}, Budget())
            facts = root/'facts.parquet'
            pq.write_table(pa.Table.from_pylist([row['values'] for row in rows]), facts)
            raw = facts.read_bytes()
            bundle['manifest'].update(backend={'root': str(root)}, files=[
                {'key': facts.name, 'sha256': digest(raw), 'size_bytes': len(raw)}])
            bundle['source'] = {'key_field': 'id', 'key_type': 'long'}
            principal = {'tenant': 't', 'subject': 's'}
            for request in ({'text': 'alpha', 'top_k': 7},
                            {'vector': [11., 2.], 'model': 'space', 'top_k': 7},
                            {'text': 'alpha', 'vector': [11., 2.], 'model': 'space', 'top_k': 7},
                            {'text': 'alpha', 'filter': {'field': 'active', 'equals': True}},
                            {'vector': [11., 2.], 'model': 'space', 'vector_index': 'ann', 'nprobes': 2, 'top_k': 7}):
                result = execute(bundle, 'search', request, Budget(seconds=30), root/'jobs', principal)
                self.assertEqual(result['hits'], search(bundle, request, Budget())['hits'])
                self.assertEqual(len({w['pid'] for w in result['execution']['workers']}), 3)
                self.assertTrue(all(w['work']['index_queries'] > 0 for w in result['execution']['workers']))
            bundle['shards'] = build_shards(bundle, root/'shards', Budget())
            physical = execute(bundle, 'search', {'vector': [11., 2.], 'model': 'space', 'vector_index': 'ann', 'nprobes': 2, 'top_k': 7}, Budget(), root/'jobs', principal)
            self.assertEqual(physical['hits'], search(bundle, {'vector': [11., 2.], 'model': 'space', 'top_k': 7}, Budget())['hits'])
            oracle = sorted(rows, key=lambda row: (math.fsum((a-b)**2 for a,b in zip(row['vector'], [11., 2.])), row['logical_key']))[:7]
            self.assertEqual([h['logical_key'] for h in physical['hits']], [r['logical_key'] for r in oracle])
            self.assertTrue(all(w['work']['vector_index'] == 'ann-shard' for w in physical['execution']['workers']))
            exported = execute(bundle, 'export', {'seed': 'fixed'}, Budget(), root/'jobs', principal)
            self.assertEqual(exported['rows'], len(rows))
            self.assertTrue(all(w['work']['source_files'] == 1 and w['work']['source_bytes'] > 0
                                for w in exported['execution']['workers']))
            self.assertEqual(pq.read_table(exported['parquet']['path'])['logical_key'].to_pylist(),
                             [row['logical_key'] for row in rows])
            # Empty workers must validate ANN options rather than early-returning success.
            small = {name: value for name, value in bundle.items() if name != 'shards'}
            small['rows'] = rows[:1]
            result = execute(small, 'search', {'vector': [0., 0.], 'model': 'space'}, Budget(), root/'jobs', principal)
            self.assertEqual([w['records'] for w in result['execution']['workers']], [1, 0, 0])
            small['ann'] = bundle['ann']
            small['shards'] = build_shards(small, root/'small-shards', Budget())
            fallback = execute(small, 'search', {'vector': [0., 0.], 'model': 'space', 'vector_index': 'ann', 'nprobes': 2},
                               Budget(), root/'jobs', principal)
            self.assertTrue(all(w['work']['vector_index'] == 'exact-small-shard' for w in fallback['execution']['workers']))
            for request in ({'text': 'alpha', 'nprobes': 1},
                            {'vector': [0., 0.], 'model': 'space', 'vector_index': 'ann', 'nprobes': 0},
                            {'vector': [0., 0.], 'model': 'space', 'nprobes': 1}):
                with self.assertRaises(Failure):
                    execute(bundle, 'search', request, Budget(), root/'jobs', principal)

    def test_invalid_protocol(self):
        for task in ({}, {'deadline': 'later'}, {'deadline': 0}):
            with self.assertRaises(Failure):
                worker_execute(task)


if __name__ == '__main__':
    unittest.main()
