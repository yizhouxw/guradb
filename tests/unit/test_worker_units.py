"""Direct worker entrypoint tests: immutable file truth, scoped tasks and errors."""
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.contracts import Budget, Failure, digest, encoded, key
from modules.index import ann_worker
from modules.query import worker
from modules.query.distributed import execute as distributed
from modules.storage.objects import put


def fact_bundle():
    return {'revision': 'rev', 'context': {'view': 'fixed'}, 'model': {'model': 'test', 'dimension': 2},
            'retention_mode': 'managed-copy', 'index_path': 'test', 'index_files': [],
            'manifest': {'dataset_id': 'd', 'files': [], 'schema': [
                {'name': 'id', 'data_type': 'int8'}, {'name': 'title', 'data_type': 'text'},
                {'name': 'active', 'data_type': 'bool'}]},
            'rows': [{'logical_key': key(i, 'long'), 'values': {'id': i, 'title': 'alpha', 'active': True},
                      'media': [], 'vector': [float(i), 0.], 'record_version': 'stable'} for i in range(3)]}


def task(bundle, kind='scan', request=None):
    payload = {'bundle': bundle, 'kind': kind, 'request': request or {},
               'scope': {'tenant': 't', 'subject': 's', 'dataset': 'd'}, 'ann_partitions': 2}
    return {'deadline': time.monotonic()+20, 'task_id': 'a'*32, 'shard': 0, 'payload': payload,
            'fingerprint': digest(encoded(payload)), 'limits': Budget().allocation(1)}


class WorkerTest(unittest.TestCase):
    def test_scan_and_source_export_read_independent_parquet(self):
        with tempfile.TemporaryDirectory() as directory:
            root, bundle = Path(directory).resolve(), fact_bundle()
            self.assertEqual(worker.execute(task(bundle))['output']['rows'][0]['values']['id'], '0')
            path = root/'facts.parquet'
            pq.write_table(pa.Table.from_pylist([r['values'] for r in bundle['rows']]), path)
            raw = path.read_bytes()
            bundle['manifest']['backend'] = {'root': str(root)}
            bundle['source_key'] = {'key_field': 'id', 'key_type': 'long'}
            bundle['source_files'] = [{'key': path.name, 'sha256': digest(raw), 'size_bytes': len(raw)}]
            output = worker.execute(task(bundle, 'export'))
            self.assertEqual([s['logical_key'] for s in output['output']['samples']], [r['logical_key'] for r in bundle['rows']])
            self.assertEqual(output['work']['source_bytes'], len(raw))
            bundle['rows'][0]['values']['title'] = 'changed'
            with self.assertRaises(Failure) as caught:
                worker.execute(task(bundle, 'export'))
            self.assertEqual(caught.exception.code, 'source_invalid')

    def test_serving_shard_search_routes_and_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root, bundle = Path(directory), fact_bundle()
            sink = BytesIO()
            pq.write_table(pa.table({'row_json': [encoded(r).decode() for r in bundle['rows']]}), sink)
            bundle['serving_shard'] = {'file': put(root/'shard', sink.getvalue()), 'rows': 3,
                                       'revision': 'rev', 'shard': 0, 'vector_fallback': 'exact-small-shard'}
            query = {'text': 'alpha', 'vector': [1., 0.], 'model': 'test', 'vector_index': 'ann', 'nprobes': 1}
            with patch.object(worker, 'search', return_value={'hits': [], 'stats': {}}) as search:
                output = worker.execute(task(bundle, 'search', query))
                self.assertEqual(output['work']['index_queries'], 2)
                self.assertEqual(output['work']['vector_index'], 'exact-small-shard')
                self.assertEqual(search.call_args.args[1]['vector_index'], 'exact')
                worker.execute(task(bundle, 'search', {'text': 'alpha'}))
                bundle['serving_shard']['ann'] = {'format': 'test'}
                self.assertEqual(worker.execute(task(bundle, 'search', query))['work']['vector_index'], 'ann-shard')
            with patch.object(worker, 'expand', return_value={'paths': []}):
                self.assertEqual(worker.execute(task(bundle, 'graph'))['output'], {'paths': []})
            self.assertEqual(len(worker.execute(task(bundle, 'export'))['output']['samples']), 3)

    def test_main_success_failure_and_script_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = task(fact_bundle())
            source = put(root/'input', encoded(value))
            output = root/'output'
            with patch.object(sys, 'argv', ['worker', source['path'], source['sha256'], str(output)]):
                runpy.run_path(worker.__file__, run_name='__main__')
            self.assertEqual(json.loads(output.read_bytes())['records'], 3)
            value['payload']['kind'] = 'unsupported'
            value['fingerprint'] = digest(encoded(value['payload']))
            source = put(root/'invalid', encoded(value))
            output.unlink()
            with patch.object(sys, 'argv', ['worker', source['path'], source['sha256'], str(output)]):
                worker.main()
            self.assertEqual(json.loads(output.read_bytes())['error'], 'invalid_request')

    def test_distributed_global_merge_without_process_or_network(self):
        bundle = fact_bundle()
        bundle['ann'] = {'partitions': 1}
        bundle['bm25'] = {'files': [1, 2, 3]}
        principal = {'tenant': 't', 'subject': 's'}
        def fanout(module, tasks, budget, root):
            return [dict(task_id=str(i), shard=i, pid=i+1, rss_bytes=1, records=1,
                         read_context=bundle['context'], work={}, server_pid=i+4,
                         output=worker.execute(task(deepcopy(payload['bundle']), payload['kind'], payload['request']))['output'])
                    for i, payload in enumerate(tasks)]
        bundle['manifest']['schema'] += [{'name': 'left', 'data_type': 'int8'}, {'name': 'right', 'data_type': 'int8'}, {'name': 'type', 'data_type': 'text'}]
        for row in bundle['rows']:
            row['values'].update(left=1, right=2, type='edge')
        query = {'source_field': 'left', 'target_field': 'right', 'type_field': 'type', 'seeds': ['1'], 'type': 'edge'}
        with tempfile.TemporaryDirectory() as directory, patch('modules.query.distributed.fanout', side_effect=fanout), patch('modules.query.distributed.fanout_remote', side_effect=lambda tasks,b,r,*rest: fanout(None,tasks,b,r)):
            def found(part, request, budget):
                return {'hits': [{'logical_key': part['rows'][0]['logical_key'], 'score': 1.}], 'stats': {}}
            with patch.object(worker, 'search', side_effect=found):
                ranked = distributed(bundle, 'search', {'text': 'alpha', 'vector': [0., 0.], 'model': 'test', 'vector_index': 'ann'}, Budget(), directory, principal)
            self.assertEqual(ranked['ranking'], 'rrf-k60-ann')
            self.assertAlmostEqual(ranked['hits'][0]['score'], 2/61)
            result = distributed(bundle, 'graph', query, Budget(), directory, principal)
            self.assertEqual(len(result['paths']), 3)
            self.assertEqual(distributed(bundle, 'scan', {'limit': 2}, Budget(), directory, principal, transport=([], 'secret'))['execution']['mode'], 'loopback-http')
            path = Path(directory)/'facts.parquet'
            pq.write_table(pa.Table.from_pylist([r['values'] for r in bundle['rows']]), path)
            raw = path.read_bytes()
            bundle['manifest'].update(backend={'root': directory}, files=[{'key': path.name, 'sha256': digest(raw), 'size_bytes': len(raw)}])
            bundle['source'] = {'key_field': 'id', 'key_type': 'long'}
            self.assertEqual(distributed(bundle, 'export', {}, Budget(), directory, principal)['rows'], 3)


class NativeWorkerTest(unittest.TestCase):
    def test_lance_build_query_and_entrypoint_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [{'logical_key': key(i, 'long'), 'vector': [float(i), float(i%3)]} for i in range(32)]
            built = ann_worker.execute({'kind': 'build', 'path': str(root/'lance'), 'rows': rows,
                                        'model': {'dimension': 2}, 'revision': 'rev', 'partitions': 1})
            query = {'kind': 'query', 'index': {'path': str(root/'lance'), 'version': built['version'], 'rows': 32},
                     'query': [7., 1.], 'condition': 'logical_key IS NOT NULL', 'limit': 1, 'probes': 1}
            self.assertEqual(ann_worker.execute(query)[0]['logical_key'], key(7, 'long'))
            source, output = root/'input', root/'output'
            source.write_bytes(encoded(query))
            with patch.object(sys, 'argv', ['ann', str(source), str(output)]):
                runpy.run_path(ann_worker.__file__, run_name='__main__')
            self.assertIn('result', json.loads(output.read_bytes()))
            source.write_bytes(b'{invalid}')
            with patch.object(sys, 'argv', ['ann', str(source), str(output)]):
                ann_worker.main()
            self.assertEqual(json.loads(output.read_bytes()), {'error': 'native_failed'})
