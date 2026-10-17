"""Independent review of physical shards, global BM25/RRF and empty filters."""
import math
from pathlib import Path
import tempfile
import unittest

from modules.common.contracts import Budget, Failure, key
from modules.index.bm25 import build as bm25
from modules.index.shards import build as shards
from modules.query.distributed import execute


class ShardReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        texts = ['alpha alpha beta', 'alpha', 'beta beta', '', 'alpha beta beta beta']
        self.rows = [{'logical_key': key(i, 'long'), 'record_version': 'original-'+str(i),
                      'values': {'id': i, 'title': text, 'active': i % 2 == 0},
                      'vector': [float(i)], 'media': []} for i, text in enumerate(texts)]
        self.bundle = {'revision': 'new-revision', 'context': {'view': 'fixed'}, 'model': {
            'model': 'unit', 'dimension': 1, 'metric': 'squared_l2', 'preprocessing': 'identity-v1'},
            'retention_mode': 'managed-copy', 'rows': self.rows,
            'manifest': {'dataset_id': 'dataset', 'schema': [
                {'name': 'active', 'data_type': 'bool'}, {'name': 'id', 'data_type': 'int8'}]},
            'index_path': 'unused', 'index_files': []}
        self.bundle['bm25'] = bm25(self.root/'bm25', self.rows, 'title', Budget())
        self.bundle['shards'] = shards(self.bundle, self.root/'shards', Budget())

    def call(self, request):
        return execute(self.bundle, 'search', request, Budget(), self.root/'workers',
                       {'tenant': 'tenant', 'subject': 'subject'})

    def test_global_scores_and_rrf_independent_truth(self):
        # Independent closed formula: N=5, df(alpha)=3, df(beta)=3, avgdl=2.0.
        lengths = [3, 1, 2, 0, 4]
        frequencies = [(2, 1), (1, 0), (0, 2), (0, 0), (1, 3)]
        text_scores = {}
        for i, counts in enumerate(frequencies):
            score = sum(math.log1p(2.5/3.5)*tf*2.2/(tf+1.2*(.25+.75*lengths[i]/2.0))
                        for tf in counts if tf)
            if score:
                text_scores[key(i, 'long')] = score
        text_order = sorted(text_scores, key=lambda logical: (-text_scores[logical], logical))
        text_actual = self.call({'text': 'alpha beta', 'top_k': 5, 'candidate_limit': 5})
        self.assertEqual([hit['logical_key'] for hit in text_actual['hits']], text_order)
        for hit in text_actual['hits']:
            self.assertAlmostEqual(hit['score'], text_scores[hit['logical_key']], places=14)
        vector_order = [key(i, 'long') for i in (2, 1, 3, 0, 4)]
        actual = self.call({'text': 'alpha beta', 'vector': [2.0], 'model': 'unit',
                            'top_k': 5, 'candidate_limit': 5})
        scores = {}
        for ranking in (text_order, vector_order):
            for rank, logical in enumerate(ranking, 1):
                scores[logical] = scores.get(logical, 0)+1/(60+rank)
        expected = sorted(scores, key=lambda logical: (-scores[logical], logical))
        self.assertEqual([hit['logical_key'] for hit in actual['hits']], expected)
        self.assertEqual([hit['score'] for hit in actual['hits']], [scores[k] for k in expected])
        self.assertTrue(all(hit['record_version'].startswith('original-') for hit in actual['hits']))

    def test_empty_filter_and_whole_request_rejection(self):
        self.assertEqual(self.call({'text': 'alpha', 'filter': {'field': 'id', 'equals': '999'}})['hits'], [])
        with self.assertRaises(Failure):
            self.call({'text': 'alpha', 'vector_index': 'ann'})

    def test_physical_empty_partitions(self):
        self.bundle['rows'] = self.rows[:1]
        self.bundle['bm25'] = bm25(self.root/'one-bm25', self.rows[:1], 'title', Budget())
        self.bundle['shards'] = shards(self.bundle, self.root/'one-shards', Budget())
        actual = self.call({'text': 'alpha', 'top_k': 1, 'candidate_limit': 1})
        self.assertEqual([hit['logical_key'] for hit in actual['hits']], [key(0, 'long')])
        self.assertEqual([w['records'] for w in actual['execution']['workers']], [1, 0, 0])

    def test_real_workers_share_remaining_source_budget(self):
        lengths = [Path(item['file']['path']).stat().st_size for item in self.bundle['shards']]
        self.assertGreater(sum(lengths), max(lengths)+1)
        budget = Budget()
        # Every file separately fits this amount; their combined workload does not.
        budget.limits['bytes'] = max(lengths)+1
        with self.assertRaises(Failure) as rejected:
            execute(self.bundle, 'scan', {'limit': 100}, budget, self.root/'restricted-workers',
                    {'tenant': 'tenant', 'subject': 'subject'})
        self.assertEqual(rejected.exception.code, 'resource_limit')
        complete = Budget()
        result = execute(self.bundle, 'scan', {'limit': 100}, complete, self.root/'complete-workers',
                         {'tenant': 'tenant', 'subject': 'subject'})
        self.assertEqual(len(result['rows']), len(self.rows))
        self.assertEqual(complete.bytes, sum(lengths))
        self.assertEqual(complete.reads, 3)
