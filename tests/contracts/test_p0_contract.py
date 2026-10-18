"""Freeze the synthetic dataset and preserve the previous P0 request coverage."""
import hashlib
import json
import unittest

from scripts.p0lib.contract import document, input_vectors, workload_contract


class P0Inputs(unittest.TestCase):
    def test_dataset_digest_survives_json_roundtrip_without_changing_vectors(self):
        def digest(value):
            raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()
            return hashlib.sha256(raw).hexdigest()

        for duration, offsets in ((0, [0, 0]), (60, [60*(.05+.85*i/7) for i in range(8)])):
            with self.subTest(duration=duration):
                contract, inputs = workload_contract(duration, 2, offsets, 'http')
                saved = json.loads(json.dumps(inputs))
                self.assertEqual(digest(saved), contract['dataset_digest'])
                original = input_vectors(inputs['documents'])
                self.assertEqual(inputs['vectors'], {str(key): vector for key, vector in original.items()})
                self.assertEqual({int(key): vector for key, vector in saved['vectors'].items()}, original)
                # Integer keys sort numerically before JSON changes them to strings.
                legacy = dict(inputs, vectors=original)
                self.assertNotEqual(digest(legacy), digest(json.loads(json.dumps(legacy))))

    def test_source_and_query_digests_are_frozen(self):
        contract, inputs = workload_contract(60, 2, [60*(.05+.85*i/7) for i in range(8)], 'http')
        self.assertEqual(contract['dataset_digest'],
                         '4423a6b2a160beb0d3bc800dc85e4b5fcaaab761c588634a54f97913cc1242f4')
        self.assertEqual(contract['query_digest'],
                         'ce4b14b1d86017d692be00c95fda77e73d8a152676b26322988a8966d7c1d44d')
        self.assertEqual(len(inputs['documents']), 384)
        self.assertEqual(contract['final_population']['nulls'], {'title': 8, 'active': 8})
        self.assertEqual(contract['final_population']['unique_keys'], 384)
        self.assertEqual(len(contract['query_pairs']), 5)
        self.assertEqual([request[0] for pair in contract['query_pairs'][:3] for request in pair],
                         ['search', 'export', 'search', 'graph', 'search', 'scan'])
        self.assertEqual(contract['budgets']['required_recall_at_10'], 1.0)

    def test_original_rows_and_short_run_size_are_preserved(self):
        for i in range(256):
            self.assertEqual(document(i), {'id': i,
                'title': ['alpha alpha beta', 'beta', 'gamma database', 'database alpha'][i % 4],
                'active': i % 2 == 0})
        contract, _ = workload_contract(0, 2, [0, 0], 'local')
        self.assertEqual(contract['final_population']['rows'], 288)
        self.assertEqual(contract['cache_cases']['true_cold'], 'not_run')
        self.assertEqual(contract['cache_cases']['over_total_cache_capacity'], 'not_run')


if __name__ == '__main__':
    unittest.main()
