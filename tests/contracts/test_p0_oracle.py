"""Hand-checkable source truth and mutations for the synthetic P0 driver."""
import ast
from copy import deepcopy
import math
from pathlib import Path
import unittest

from scripts.p0lib.oracle import SourceOracle, assert_accepted_context, logical_key, split_bucket


KEYS = ['01000000010200000008000000000000000' + str(i) for i in range(6)]
TEXTS = ['alpha alpha beta', 'alpha', 'beta beta', None, 'alpha beta beta beta']
MEDIA = {'uri': 'file:///synthetic/object.bin', 'sha256': 'a' * 64, 'size_bytes': 7}


def fixture():
    rows = [{'id': i, 'title': text, 'active': i % 2 == 0 if i != 3 else None}
            for i, text in enumerate(TEXTS)]
    features = {'model': 'synthetic-fixed', 'dimension': 2, 'metric': 'squared_l2',
                'preprocessing': 'identity-v1', 'records': [
                    {'logical_key': KEYS[i], 'vector': [float(i), 0.0],
                     'media': [deepcopy(MEDIA)] if i == 1 else []} for i in range(5)]}
    return rows, features


def make_oracle(rows=None, features=None, revision='revision-1', previous=None):
    default_rows, default_features = fixture()
    return SourceOracle(default_rows if rows is None else rows,
                        default_features if features is None else features,
                        dataset_id='fixture-dataset', revision=revision,
                        read_context={'data_revision_id': revision, 'read_view_id': 'view-' + revision},
                        previous=previous)


def search_result(oracle, request):
    return {'hits': oracle.expected_hits(request), 'read_context': deepcopy(oracle.read_context),
            'ranking': 'rrf-k60' if 'text' in request and 'vector' in request else (
                'bm25' if 'text' in request else 'exact-squared-l2')}


def training_result(oracle, request):
    return {'samples': oracle.expected_samples(request), 'read_context': deepcopy(oracle.read_context),
            'model': deepcopy(oracle.model), 'rows': oracle.row_count,
            'seed': request.get('seed', '0'), 'train_basis_points': request.get('train_basis_points', 8000),
            'retention_mode': 'managed-copy'}


class IndependentP0Truth(unittest.TestCase):
    def test_correct_results_from_another_known_view_are_rejected(self):
        previous = make_oracle()
        current = make_oracle(revision='revision-2')
        request = {'text': 'alpha'}
        result = search_result(previous, request)
        previous.assert_search(result, request)
        with self.assertRaisesRegex(AssertionError, 'accepted job view'):
            assert_accepted_context({'read_context': current.read_context}, result)
        assert_accepted_context({'read_context': previous.read_context}, result)

    def test_new_source_records_cannot_reuse_an_old_revision(self):
        rows, features = fixture()
        previous = make_oracle(rows, features)
        rows.append({'id': 5, 'title': 'new', 'active': True})
        features['records'].append({'logical_key': KEYS[5], 'vector': [5., 0.], 'media': []})
        with self.assertRaisesRegex(ValueError, 'new data revision'):
            make_oracle(rows, features, revision='revision-1', previous=previous)

    def test_oracle_imports_only_standard_library(self):
        source = Path(__file__).resolve().parents[2] / 'scripts/p0lib/oracle.py'
        imports = [node.module for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(ast.parse(source.read_text()))
                    if isinstance(node, ast.Import) for alias in node.names]
        self.assertEqual(set(imports), {'collections', 'copy', 'hashlib', 'json', 'math', 're'})

    def test_identity_golden_vectors_and_key_rejection(self):
        self.assertEqual(logical_key(0), KEYS[0])
        self.assertEqual(logical_key(-1), '01000000010200000008ffffffffffffffff')
        self.assertEqual(logical_key('中', 'string'), '01000000010100000003e4b8ad')
        for value in (None, True, 2**63, -(2**63) - 1, '0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                logical_key(value)
        rows, features = fixture()
        rows[1]['id'] = rows[0]['id']
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            make_oracle(rows, features)
        rows[1]['id'] = None
        with self.assertRaisesRegex(ValueError, 'non-NULL'):
            make_oracle(rows, features)

    def test_bm25_hand_formula_uses_whole_corpus_before_filter(self):
        oracle = make_oracle()
        # Five source rows, including NULL text: N=5, avgdl=2, df(alpha)=df(beta)=3.
        lengths = [3, 1, 2, 0, 4]
        counts = [(2, 1), (1, 0), (0, 2), (0, 0), (1, 3)]
        scores = {KEYS[i]: sum(math.log(12 / 7) * tf * 2.2 /
                              (tf + 1.2 * (.25 + .75 * lengths[i] / 2))
                              for tf in counts[i] if tf) for i in (0, 1, 2, 4)}
        expected = sorted(scores, key=lambda key: (-scores[key], key))
        request = {'text': 'alpha beta', 'top_k': 5, 'candidate_limit': 5}
        hits = oracle.expected_hits(request)
        self.assertEqual([hit['logical_key'] for hit in hits], expected)
        for hit in hits:
            self.assertAlmostEqual(hit['score'], scores[hit['logical_key']], places=14)
        filtered = oracle.expected_hits(dict(request, filter={'field': 'active', 'equals': True}))
        self.assertEqual([hit['logical_key'] for hit in filtered], [key for key in expected if key != KEYS[1]])
        for hit in filtered:
            self.assertAlmostEqual(hit['score'], scores[hit['logical_key']], places=14)
        # Recomputing N/avgdl/df after filtering would change every retained score.
        self.assertNotAlmostEqual(filtered[0]['score'], math.log(8 / 7), places=5)
        once = oracle.expected_hits(dict(request, text='alpha'))
        twice = oracle.expected_hits(dict(request, text='ALPHA alpha'))
        self.assertEqual([hit['logical_key'] for hit in once], [hit['logical_key'] for hit in twice])
        for one, two in zip(once, twice):
            self.assertAlmostEqual(two['score'], 2 * one['score'], places=14)

    def test_exact_l2_stable_order_and_typed_null_filter(self):
        oracle = make_oracle()
        request = {'vector': [2.0, 0.0], 'model': 'synthetic-fixed', 'top_k': 5, 'candidate_limit': 5}
        hits = oracle.expected_hits(request)
        self.assertEqual([hit['logical_key'] for hit in hits], [KEYS[i] for i in (2, 1, 3, 0, 4)])
        self.assertEqual([hit['score'] for hit in hits], [0.0, -1.0, -1.0, -4.0, -4.0])
        self.assertEqual(oracle.expected_hits(dict(request, filter={'field': 'id', 'equals': '2'})), hits[:1])
        null_hit = oracle.expected_hits(dict(request, filter={'field': 'active', 'equals': None}))
        self.assertEqual([hit['logical_key'] for hit in null_hit], [KEYS[3]])
        self.assertEqual(oracle.expected_hits(dict(request, filter={'field': 'id', 'equals': '999'})), [])
        for selected in ({'field': 'id', 'equals': True}, {'field': 'id', 'equals': '02'},
                         {'field': 'active', 'equals': 1}, {'field': 'id', 'equals': 2**53}):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                oracle.expected_hits(dict(request, filter=selected))

    def test_rrf_fuses_global_route_windows_before_final_top_k(self):
        oracle = make_oracle()
        # alpha-only BM25 is row 1 > row 0 > row 4; exact vector is 2 > 1 > 3 > 0 > 4.
        request = {'text': 'alpha', 'vector': [2.0, 0.0], 'model': 'synthetic-fixed',
                   'top_k': 3, 'candidate_limit': 3}
        hit = oracle.expected_hits(request)
        expected_scores = {KEYS[0]: 1 / 62, KEYS[1]: 1 / 61 + 1 / 62,
                           KEYS[2]: 1 / 61, KEYS[3]: 1 / 63, KEYS[4]: 1 / 63}
        self.assertEqual([item['logical_key'] for item in hit], [KEYS[1], KEYS[2], KEYS[0]])
        for item in hit:
            self.assertAlmostEqual(item['score'], expected_scores[item['logical_key']], places=14)
        # top_k=1 still keeps both 3-item route windows. Early route truncation
        # would fuse row 0 and row 3 at equal ranks and incorrectly choose row 0.
        request = dict(request, text='alpha beta', vector=[3.0, 0.0], top_k=1)
        self.assertEqual(oracle.expected_hits(request)[0]['logical_key'], KEYS[2])

    def test_oracle_refuses_out_of_contract_requests(self):
        oracle = make_oracle()
        rejected = [
            {'text': 'alpha', 'candidate_limit': 1001},
            {'text': 'alpha', 'top_k': 0},
            {'text': 'alpha', 'filter': None},
            {'text': 'alpha', 'model': 'synthetic-fixed'},
            {'text': 'alpha', 'vector_index': 'ann'},
            {'text': 'alpha', 'nprobes': 1},
            {'text': 'alpha OR beta?'},
            {'vector': [1.0], 'model': 'synthetic-fixed'},
            {'vector': [1.0, 0.0], 'model': 'different'},
            {'vector': [True, 0.0], 'model': 'synthetic-fixed'},
            {'vector': [1.0, 0.0], 'model': 'synthetic-fixed', 'vector_index': 'ann', 'nprobes': 0}]
        for request in rejected:
            with self.subTest(request=request), self.assertRaises(ValueError):
                oracle.expected_hits(request)
        for request in ({'train_basis_points': -1}, {'train_basis_points': 10001},
                        {'seed': 17}, {'seed': 'x' * 129}, {'filter': {'active': True}}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                oracle.expected_samples(request)

    def test_training_fixed_split_vectors_and_complete_golden_sample(self):
        oracle = make_oracle()
        self.assertEqual([split_bucket('seed-17', 'fixture-dataset', key) for key in KEYS[:5]],
                         [5423, 3036, 6186, 6256, 2746])
        samples = oracle.expected_samples({'seed': 'seed-17', 'train_basis_points': 5000})
        self.assertEqual([sample['split'] for sample in samples],
                         ['validation', 'train', 'validation', 'validation', 'train'])
        self.assertEqual(samples[1], {
            'dataset_id': 'fixture-dataset', 'entity_kind': 'record', 'logical_key': KEYS[1],
            'record_version': 'revision-1', 'split': 'train', 'vector': [1.0, 0.0],
            'values_json': '{"active":false,"id":"1","title":"alpha"}',
            'media_json': '[{"sha256":"' + 'a' * 64 + '","size_bytes":7,"uri":"file:///synthetic/object.bin"}]'})
        self.assertEqual(oracle.expected_samples({'seed': 'seed-17', 'train_basis_points': 3036})[1]['split'], 'validation')
        self.assertEqual(oracle.expected_samples({'seed': 'seed-17', 'train_basis_points': 3037})[1]['split'], 'train')
        self.assertTrue(all(s['split'] == 'validation' for s in oracle.expected_samples({'train_basis_points': 0})))
        self.assertTrue(all(s['split'] == 'train' for s in oracle.expected_samples({'train_basis_points': 10000})))

    def test_append_preserves_versions_and_freezes_source_inputs(self):
        rows, features = fixture()
        old = make_oracle(rows, features)
        rows.append({'id': 5, 'title': None, 'active': None})
        features['records'].append({'logical_key': KEYS[5], 'vector': [5.0, 0.0], 'media': []})
        new = make_oracle(rows, features, 'revision-2', old)
        self.assertEqual(old.row_count, 5)
        samples = new.expected_samples({})
        self.assertEqual([s['record_version'] for s in samples], ['revision-1'] * 5 + ['revision-2'])
        rows[0]['title'] = 'mutated input'
        features['records'][0]['vector'][0] = 999.0
        self.assertEqual(new.expected_samples({}), samples)
        with self.assertRaisesRegex(ValueError, 'rewrite'):
            make_oracle(rows, features, 'revision-3', new)
        with self.assertRaisesRegex(ValueError, 'rewrite'):
            make_oracle(*fixture(), revision='revision-3', previous=new)

    def test_feature_coverage_duplicate_and_media_reference_rejection(self):
        for mutation in ('missing', 'duplicate', 'extra', 'copy', 'dimension'):
            rows, features = fixture()
            if mutation == 'missing':
                features['records'].pop()
            elif mutation == 'duplicate':
                features['records'].append(deepcopy(features['records'][0]))
            elif mutation == 'extra':
                features['records'].append({'logical_key': KEYS[5], 'vector': [5.0, 0.0], 'media': []})
            elif mutation == 'copy':
                features['records'][1]['media'][0]['copy'] = {'path': 'observed-bundle'}
            else:
                features['records'][0]['vector'].append(0.0)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                make_oracle(rows, features)

    def test_search_mutations_catch_order_filter_version_score_payload_and_view(self):
        oracle = make_oracle()
        request = {'text': 'alpha beta', 'top_k': 3, 'candidate_limit': 5,
                   'filter': {'field': 'active', 'equals': True}}
        original = search_result(oracle, request)
        oracle.assert_search(original, request)
        for mutation in ('order', 'filter', 'version', 'score', 'payload', 'missing', 'duplicate', 'view'):
            result = deepcopy(original)
            if mutation == 'order':
                result['hits'].reverse()
            elif mutation == 'filter':
                result['hits'][0] = oracle.expected_hits({'text': 'alpha', 'filter': {'field': 'id', 'equals': '1'}})[0]
            elif mutation == 'version':
                result['hits'][0]['record_version'] = 'newest-but-wrong'
            elif mutation == 'score':
                result['hits'][0]['score'] += .001
            elif mutation == 'payload':
                result['hits'][0]['values']['active'] = False
            elif mutation == 'missing':
                result['hits'].pop()
            elif mutation == 'duplicate':
                result['hits'][1] = deepcopy(result['hits'][0])
            else:
                result['read_context']['read_view_id'] = 'latest'
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                oracle.assert_search(result, request)

    def test_training_mutations_catch_complete_identity_sample_feature_contract(self):
        oracle, request = make_oracle(), {'seed': 'seed-17'}
        original = training_result(oracle, request)
        oracle.assert_training(original, request)
        changes = {'record_version': 'wrong', 'dataset_id': 'wrong', 'logical_key': KEYS[0],
                   'entity_kind': 'asset', 'split': 'validation', 'vector': [999., 0.],
                   'media_json': '[]', 'values_json': '{}'}
        for name, value in changes.items():
            result = deepcopy(original)
            result['samples'][1][name] = value
            with self.subTest(field=name), self.assertRaises(AssertionError):
                oracle.assert_training(result, request)
        for mutation in ('drop', 'duplicate', 'order', 'view'):
            result = deepcopy(original)
            if mutation == 'drop':
                result['samples'].pop()
            elif mutation == 'duplicate':
                result['samples'][1] = deepcopy(result['samples'][0])
            elif mutation == 'order':
                result['samples'].reverse()
            else:
                result['read_context']['data_revision_id'] = 'latest'
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                oracle.assert_training(result, request)

    def test_materialized_and_scan_fail_on_missing_duplicate_or_reversion(self):
        oracle = make_oracle()
        rows, features = fixture()
        materialized = [{'logical_key': KEYS[i], 'record_version': 'revision-1', 'values': rows[i],
                         'vector': features['records'][i]['vector'], 'media': features['records'][i]['media']}
                        for i in range(5)]
        materialized[1]['media'][0]['copy'] = {'path': 'immutable-copy'}
        oracle.assert_materialized(materialized)
        for mutation in ('missing', 'duplicate', 'version', 'feature'):
            actual = deepcopy(materialized)
            if mutation == 'missing':
                actual.pop()
            elif mutation == 'duplicate':
                actual[1] = deepcopy(actual[0])
            elif mutation == 'version':
                actual[0]['record_version'] = 'latest'
            else:
                actual[1]['vector'][0] = 99.0
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                oracle.assert_materialized(actual)
        scan = {'read_context': deepcopy(oracle.read_context), 'truncated': False, 'rows': []}
        for row in materialized:
            scan['rows'].append({'logical_key': row['logical_key'], 'record_version': row['record_version'],
                                 'values': dict(row['values'], id=str(row['values']['id'])),
                                 'media': [deepcopy(MEDIA)] if row['logical_key'] == KEYS[1] else []})
        oracle.assert_scan(scan)
        scan['rows'][1] = deepcopy(scan['rows'][0])
        with self.assertRaises(AssertionError):
            oracle.assert_scan(scan)


if __name__ == '__main__':
    unittest.main()
