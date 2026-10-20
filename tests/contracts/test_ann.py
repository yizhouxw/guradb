"""Real native-process cancellation and immutable Lance mapping contracts."""
import os
from contextlib import chdir
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from modules.index import ann, ann_worker
from modules.common.contracts import Budget, Failure, key
from modules.common.process import run_process
from modules.index.ann import build, build_many, candidates
from modules.index.shards import build_snapshot
from modules.query.snapshot import construct


class ANNContract(unittest.TestCase):
    def test_null_ann_configuration_is_rejected_before_catalog_access(self):
        target = {'metadata_uri': 'file:///not-read', 'metadata_sha256': '0'*64, 'snapshot_id': '1',
                  'features_uri': 'file:///not-read', 'features_sha256': '0'*64, 'ann': None}
        with self.assertRaises(Failure) as caught:
            construct(None, 'dataset', 'operation', target, '/not-created')
        self.assertEqual(caught.exception.code, 'invalid_request')

    def test_snapshot_builds_global_and_three_independent_shards_in_one_process(self):
        rows = [{'logical_key': key(i, 'long'), 'vector': [float(i), float(i % 3)],
                 'record_version': 'record-'+str(i), 'values': {'id': i}, 'media': []} for i in range(96)]
        model = {'dimension': 2, 'model': 'test-space', 'metric': 'squared_l2', 'preprocessing': 'identity-v1'}
        bundle = {'rows': list(reversed(rows)), 'revision': 'revision', 'model': model}
        with tempfile.TemporaryDirectory() as directory, patch.object(ann, 'run_process', wraps=run_process) as calls:
            built = build_snapshot(bundle, Path(directory), Budget(seconds=30), {'partitions': 1})
            self.assertEqual(calls.call_count, 1)
            self.assertEqual(len(calls.call_args.args[1]['tasks']), 4)
            self.assertEqual(built['ann']['rows'], 96)
            self.assertEqual([item['rows'] for item in built['shards']], [32, 32, 32])
            for index, facts in [(built['ann'], rows)]+[(item['ann'], rows[n::3]) for n,item in enumerate(built['shards'])]:
                view = {'ann': index, 'rows': facts, 'revision': 'revision', 'model': model}
                found, _ = candidates(view, [7.25, 1.0], {r['logical_key'] for r in facts}, 4, 1, Budget())
                expected = sorted([(r['logical_key'], -sum((a-b)**2 for a,b in zip(r['vector'], [7.25, 1.0])))
                                   for r in facts], key=lambda r: (-r[1], r[0]))[:4]
                self.assertEqual(found, expected)
            self.assertNotIn('ann', bundle, 'construct metadata only after the whole batch succeeds')

    def test_batch_preserves_independent_versions_and_exhaustive_truth(self):
        model = {'dimension': 2, 'model': 'test-space', 'metric': 'squared_l2', 'preprocessing': 'identity-v1'}
        with tempfile.TemporaryDirectory() as directory:
            entries = [(Path(directory)/str(shard), [
                {'logical_key': key(i, 'long'), 'vector': [float(i), float(i % 3)],
                 'record_version': 'record-'+str(i)} for i in range(shard, 96, 3)]) for shard in range(3)]
            # The overflow case must keep the same valid individual-index inputs.
            for fallback in (False, True):
                selected = [(path/str(fallback), list(reversed(rows))) for path, rows in entries]
                class Oversized:
                    def __len__(self):
                        return ann.MAX_BYTES+1
                encoder = (lambda _: Oversized()) if fallback else ann.encoded
                with patch.object(ann, 'encoded', side_effect=encoder), patch.object(ann, 'run_process', wraps=run_process) as calls:
                    indexes = build_many(selected, 'revision', model, {'partitions': 1}, Budget(seconds=30))
                self.assertEqual(calls.call_count, 3 if fallback else 1)
                for (_, rows), index in zip(selected, indexes):
                    self.assertEqual(index['rows'], len(rows))
                    self.assertTrue(0 < index['native_rss_bytes'] <= 512 << 20)
                    query = [7.25, 1.0]  # Avoid an ANN cutoff tie between equidistant source rows.
                    bundle = {'ann': index, 'revision': 'revision', 'model': model, 'rows': rows}
                    hits, _ = candidates(bundle, query, {r['logical_key'] for r in rows}, 4, 1, Budget())
                    expected = sorted([(r['logical_key'], -sum((a-b)**2 for a,b in zip(r['vector'], query)))
                                       for r in rows], key=lambda r: (-r[1], r[0]))[:4]
                    self.assertEqual(hits, expected)

    def test_batch_rejects_conflicts_and_partial_native_results(self):
        rows = [{'logical_key': key(i, 'long'), 'vector': [float(i)]} for i in range(16)]
        model = {'dimension': 1}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'index'
            for entries in ([], [(path, rows)]*2, [(path, rows)]*5):
                with self.assertRaises(Failure):
                    build_many(entries, 'revision', model, {'partitions': 1}, Budget())
            self.assertFalse(path.exists(), 'preflight errors must not start native writes')
            with patch.object(ann, 'run_process', return_value={'value': [], 'native_rss_bytes': 1}):
                with self.assertRaises(Failure) as caught:
                    build_many([(path, rows)], 'revision', model, {'partitions': 1}, Budget())
            self.assertEqual(caught.exception.code, 'native_failed')
            for tasks in ([], [{'kind': 'query'}], [{'kind': 'build'}]*5):
                with self.assertRaises(Failure):
                    ann_worker.execute({'kind': 'build-many', 'tasks': tasks})

    def test_batch_worker_versions_reference_distinct_datasets(self):
        with tempfile.TemporaryDirectory() as directory:
            tasks = [{'kind': 'build', 'path': str(Path(directory)/str(shard)),
                      'rows': [{'logical_key': key(i, 'long'), 'record_version': 'record-'+str(i),
                                'vector': [float(i)]} for i in range(shard, 64, 2)],
                      'revision': 'revision', 'model': {'dimension': 1}, 'partitions': 1}
                     for shard in range(2)]
            versions = ann_worker.execute({'kind': 'build-many', 'tasks': tasks})
            self.assertEqual(len(versions), 2)
            for task, version in zip(tasks, versions):
                query = {'kind': 'query', 'index': {'path': task['path'], 'version': version['version'], 'rows': 32},
                         'condition': "logical_key IS NOT NULL", 'query': task['rows'][0]['vector'], 'limit': 1, 'probes': 1}
                found = ann_worker.execute(query)
                self.assertEqual(found[0]['logical_key'], task['rows'][0]['logical_key'])
                self.assertEqual(found[0]['record_version'], task['rows'][0]['record_version'])

    def test_batch_cancellation_leaves_no_publishable_reference(self):
        rows = [{'logical_key': key(i, 'long'), 'vector': [float(i)]} for i in range(256)]
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory)/'first'
            with self.assertRaises(Failure) as caught:
                build_many([(first, rows), (Path(directory)/'second', rows)], 'revision',
                           {'dimension': 1}, {'partitions': 1}, Budget(cancelled=first.exists, seconds=10))
            self.assertEqual(caught.exception.code, 'cancelled')
            self.assertTrue(first.exists(), 'cancel only after real native construction starts')

    def test_live_native_cancellation_and_timeout_reap(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/'pid'
            script = 'import os,pathlib,time; pathlib.Path('+repr(str(marker))+').write_text(str(os.getpid())); time.sleep(60)'
            for code in ('cancelled', 'timeout'):
                marker.unlink(missing_ok=True)
                budget = Budget(cancelled=marker.exists if code == 'cancelled' else lambda: False,
                                seconds=2 if code == 'timeout' else 10)
                started = time.monotonic()
                with self.assertRaises(Failure) as caught:
                    run_process([sys.executable, '-c', script], {}, budget)
                self.assertEqual(caught.exception.code, code)
                self.assertTrue(marker.exists(), 'cancellation must occur inside live worker')
                self.assertLess(time.monotonic()-started, 4)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(marker.read_text()), 0)

    def test_native_failure_and_byte_limits(self):
        for script, code in [('raise RuntimeError("native boom")', 'native_failed'),
                             ('import pathlib,sys; pathlib.Path(sys.argv[-1]).write_text("x" * (33554433))', 'resource_limit')]:
            with self.assertRaises(Failure) as caught:
                run_process([sys.executable, '-c', script], {}, Budget())
            self.assertEqual(caught.exception.code, code)

    def test_real_lance_mapping_delete_rebuild(self):
        rows = [{'logical_key': key(i, 'long'), 'vector': [float(i), float(i % 3)]} for i in range(32)]
        model = {'dimension': 2, 'model': 'test-space', 'metric': 'squared_l2', 'preprocessing': 'identity-v1'}
        with tempfile.TemporaryDirectory() as directory:
            def prepare(name, facts, revision):
                index = build(Path(directory)/name, facts, revision, model, {'partitions': 1}, Budget(seconds=30))
                self.assertTrue(0 < index['native_rss_bytes'] <= 512 << 20)
                return {'ann': index, 'revision': revision, 'model': model, 'rows': facts}
            with chdir(directory):
                old = prepare('old', rows, 'rev-old')
            query = [7.0, 1.0]
            ranked, costs = candidates(old, query, {r['logical_key'] for r in rows}, 4, 1, Budget())
            self.assertTrue(0 < costs['native_rss_bytes'] <= 512 << 20)
            expected = sorted([(r['logical_key'], -sum((a-b)**2 for a,b in zip(r['vector'], query)))
                               for r in rows], key=lambda r: (-r[1], r[0]))[:4]
            self.assertEqual(ranked, expected)
            deleted = rows[7]['logical_key']
            remaining = [r for r in reversed(rows) if r['logical_key'] != deleted]
            new = prepare('new', remaining, 'rev-new')
            hits, _ = candidates(new, query, {r['logical_key'] for r in remaining}, 4, 1, Budget())
            self.assertNotIn(deleted, {key for key, _ in hits})
            # Old immutable view still retains its identity/version mapping after rebuild.
            old_hits, _ = candidates(old, query, {r['logical_key'] for r in rows}, 1, 1, Budget())
            self.assertEqual(old_hits[0][0], deleted)
            wrong = dict(new, revision='wrong-revision')
            with self.assertRaises(Failure) as caught:
                candidates(wrong, query, {r['logical_key'] for r in remaining}, 4, 1, Budget())
            self.assertEqual(caught.exception.code, 'source_invalid')


if __name__ == '__main__':
    unittest.main()
