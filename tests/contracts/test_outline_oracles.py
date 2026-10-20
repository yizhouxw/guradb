"""Hand-checkable P01 goldens and adversarial mutations, independent of operators."""
import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.outline_oracles import FixtureError, OutlineOracle, load_fixture
from tests.outline_oracles.fixture import MANIFEST_SHA256, ROOT, validate_fixture
from tests.outline_oracles.truth import cf1_int8_or_null


def record(record_id, version='1'):
    return {'record_id': record_id, 'record_version': version}


def mutate(documents, case):
    document = documents[case['document']]
    path = case['path']
    parent = document
    for segment in path[:-1]:
        parent = parent[segment]
    last = path[-1]
    if case['operation'] == 'duplicate':
        parent.append(deepcopy(parent[last]))
    else:
        parent[last] = deepcopy(case['value'])


class OutlineOracleContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_fixture()

    def oracle(self, view_id='view-v2'):
        return OutlineOracle(self.fixture, view_id)

    def test_manifest_freezes_original_bytes_and_all_inputs(self):
        documents = self.fixture
        self.assertEqual(hashlib.sha256((ROOT / 'manifest.json').read_bytes()).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(documents['manifest']['evidence_class'], 'module-only-synthetic')
        self.assertFalse(documents['corpus']['public_api'])
        self.assertEqual(documents['corpus']['language'], 'zh-CN')
        self.assertEqual(documents['corpus']['license'], 'CC0-1.0')
        for entry in documents['manifest']['inputs']:
            raw = (ROOT / entry['path']).read_bytes()
            self.assertEqual(len(raw), entry['size_bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
        self.assertEqual(self.oracle().verify_golden()['visible_records'], 11)

    def test_digest_corruption_missing_extra_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / 'fixture'
            shutil.copytree(ROOT, copied)
            target = copied / 'assets/a.svg'
            original = target.read_bytes()
            target.write_bytes(original + b'\n')
            with self.assertRaisesRegex(FixtureError, 'input_mismatch'):
                load_fixture(copied)
            target.write_bytes(original)
            target.unlink()
            with self.assertRaisesRegex(FixtureError, 'missing_input'):
                load_fixture(copied)
            target.symlink_to(ROOT / 'assets/a.svg')
            with self.assertRaisesRegex(FixtureError, 'invalid_path'):
                load_fixture(copied)
            target.unlink()
            target.write_bytes(original)
            extra = copied / 'unlisted.json'
            extra.write_text('{}')
            with self.assertRaisesRegex(FixtureError, 'unexpected_input'):
                load_fixture(copied)
            extra.unlink()
            manifest = copied / 'manifest.json'
            manifest.write_bytes(manifest.read_bytes() + b'\n')
            with self.assertRaisesRegex(FixtureError, 'manifest_mismatch'):
                load_fixture(copied)

    def test_semantic_negative_case_manifest_covers_each_declared_rejection(self):
        for case in self.fixture['negatives']:
            documents = deepcopy(self.fixture)
            mutate(documents, case)
            with self.subTest(case=case['case_id']), self.assertRaises(FixtureError) as rejected:
                validate_fixture(documents)
            self.assertEqual(rejected.exception.code, case['error'])

    def test_exact_duplicate_detection_does_not_trust_declared_cluster_names(self):
        documents = deepcopy(self.fixture)
        duplicate = documents['corpus']['records'][4]
        duplicate['group_id'] = 'family-b'
        duplicate['duplicate_cluster'] = 'disguised-duplicate'
        with self.assertRaisesRegex(FixtureError, 'cross_split_duplicate'):
            validate_fixture(documents)

    def test_reference_postings_cannot_drop_or_change_source_term_frequency(self):
        for mutation in ('drop', 'frequency', 'bool-frequency', 'version'):
            documents = deepcopy(self.fixture)
            postings = documents['token_index']['postings']['权限']
            if mutation == 'drop':
                postings.pop()
            elif mutation == 'frequency':
                postings[0]['tf'] += 1
            elif mutation == 'bool-frequency':
                postings[0]['tf'] = True
            else:
                postings[0]['record_version'] = '1'
            with self.subTest(mutation=mutation), self.assertRaisesRegex(FixtureError, 'invalid_postings'):
                validate_fixture(documents)

    def test_full_int8_and_null_wire_goldens(self):
        expected = [
            (-9223372036854775808, {'type': 'int8', 'value': '-9223372036854775808'}),
            (9223372036854775807, {'type': 'int8', 'value': '9223372036854775807'}),
            (-9007199254740993, {'type': 'int8', 'value': '-9007199254740993'}),
            (9007199254740993, {'type': 'int8', 'value': '9007199254740993'}),
            (0, {'type': 'int8', 'value': '0'}), (None, {'type': 'null', 'value': None})]
        for native, wire in expected:
            self.assertEqual(cf1_int8_or_null(native), wire)
            self.assertEqual(json.loads(json.dumps(native)), native)
        for rejected in (True, False, 0.0, '0', 2**63, -(2**63) - 1):
            with self.subTest(value=rejected), self.assertRaisesRegex(FixtureError, 'invalid_int8'):
                cf1_int8_or_null(rejected)

    def test_relation_null_and_integer_selection_are_source_values(self):
        oracle = self.oracle()
        self.assertEqual(oracle.selection({'field': 'title', 'op': 'eq', 'value': None}), [])
        self.assertEqual(oracle.selection({'field': 'active', 'op': 'is_null'}), [record('r-c3'), record('r-null')])
        self.assertEqual(oracle.selection({'field': 'priority', 'op': 'ge', 'value': 9007199254740993}),
                         [record('r-a1', '2'), record('r-b1')])
        for predicate in ({'field': 'priority', 'op': 'eq', 'value': True},
                          {'field': 'active', 'op': 'eq', 'value': 1},
                          {'field': 'priority', 'op': 'eq', 'value': '9223372036854775807'},
                          {'field': 'priority', 'op': 'eq', 'value': 2**63},
                          {'field': 'priority', 'op': 'eq', 'value': 1.0},
                          {'field': 'title', 'op': 'ge', 'value': 'x'},
                          {'field': 'other', 'op': 'eq', 'value': 1},
                          {'field': 'title', 'op': 'is_null', 'value': None},
                          {'field': 'title', 'op': 'eq'}):
            with self.subTest(predicate=predicate), self.assertRaisesRegex(FixtureError, 'unsupported_predicate'):
                oracle.selection(predicate)

    def test_exact_l2_uses_hand_coordinates_and_stable_identity_ties(self):
        oracle = self.oracle()
        hits = oracle.exact_l2([0, 0, 0])
        self.assertEqual([hit['distance'] for hit in hits], [0, 0, 1, 4, 4, 4, 9, 9, 16, 16])
        self.assertEqual([hit['record_id'] for hit in hits],
                         ['r-a1', 'r-a1-copy', 'r-a2', 'r-a3', 'r-b1', 'r-c1', 'r-b2', 'r-c2', 'r-b3', 'r-c3'])
        self.assertEqual(hits[0]['record_version'], '2')
        for vector in ([0, 0], [0, False, 0], [0, float('nan'), 0], [float('inf'), 0, 0]):
            with self.subTest(vector=vector), self.assertRaisesRegex(FixtureError, 'wrong_feature_space'):
                oracle.exact_l2(vector)
        with self.assertRaisesRegex(FixtureError, 'wrong_feature_space'):
            oracle.exact_l2([0, 0, 0], model_version='newest')
        with self.assertRaisesRegex(FixtureError, 'wrong_feature_space'):
            oracle.exact_l2([0, 0, 0], space_id='same-dimension-wrong-space')

    def test_bm25_hand_formula_counts_null_and_filters_after_statistics(self):
        oracle = self.oracle()
        # 11 visible rows, including NULL title: total token length 22 => avgdl=2.
        # Each query term has df=3. Both three-token a1 rows have two matches.
        idf = math.log(24 / 7)
        two_matches = 2 * idf * 2.2 / (1 + 1.2 * (.25 + .75 * 3 / 2))
        one_match = idf * 2.2 / (1 + 1.2 * (.25 + .75 * 2 / 2))
        hits = oracle.bm25(['权限', '缓存'])
        self.assertEqual([hit['record_id'] for hit in hits], ['r-a1', 'r-a1-copy', 'r-a2', 'r-a3'])
        for actual, expected in zip(hits, [two_matches, two_matches, one_match, one_match]):
            self.assertAlmostEqual(actual['score'], expected, delta=1e-12)
        filtered = oracle.bm25(['权限', '缓存'], {'field': 'active', 'op': 'eq', 'value': True})
        self.assertEqual(filtered, hits[:3])
        twice = oracle.bm25(['权限', '权限'])
        once = oracle.bm25(['权限'])
        self.assertEqual([hit['record_id'] for hit in twice], ['r-a2', 'r-a1', 'r-a1-copy'])
        for actual, expected in zip(twice, once):
            self.assertAlmostEqual(actual['score'], 2 * expected['score'], delta=1e-12)
        with self.assertRaisesRegex(FixtureError, 'invalid_tokens'):
            oracle.bm25([])

    def test_typed_graph_depth_cycle_and_fixed_version(self):
        oracle = self.oracle()
        self.assertEqual(oracle.graph(record('r-a1', '2'), max_depth=1), [dict(record('r-a2'), depth=1)])
        self.assertEqual(oracle.graph(record('r-a1', '2'), max_depth=3),
                         [dict(record('r-a2'), depth=1), dict(record('r-a3'), depth=2)])
        for depth in (0, 4, True, None):
            with self.subTest(depth=depth), self.assertRaisesRegex(FixtureError, 'unsupported_graph'):
                oracle.graph(record('r-a1', '2'), max_depth=depth)
        with self.assertRaisesRegex(FixtureError, 'unsupported_graph'):
            oracle.graph(record('r-a1', '2'), relation='arbitrary')
        with self.assertRaisesRegex(FixtureError, 'unknown_record'):
            oracle.graph(record('r-a1', '1'))
        with self.assertRaisesRegex(FixtureError, 'index_view_mismatch'):
            self.oracle('view-v1').graph(record('r-a1', '1'))

    def test_samples_have_explicit_member_truth_and_split_isolation(self):
        samples = self.oracle().samples()
        self.assertEqual([(s['sample_id'], s['split']) for s in samples],
                         [('synthetic-sample-a', 'train'), ('synthetic-sample-b', 'validation'), ('synthetic-sample-c', 'test')])
        for group, sample in zip(('a', 'b', 'c'), samples):
            version = '2' if group == 'a' else '1'
            self.assertEqual([(m['role'], m['record']) for m in sample['members']], [
                ('query', record('r-' + group + '2')), ('positive', record('r-' + group + '1', version)),
                ('negative', record('r-' + group + '3')), ('image', record('r-' + group + '1', version))])
            self.assertEqual(sample['recipe']['processing'], 'identity/no-fitted-statistics')
            for member in sample['members']:
                self.assertEqual(member['values']['group_id'], 'family-' + group)
                self.assertEqual(member['values']['record_version'], member['record']['record_version'])
        self.assertEqual(samples[0]['members'][1]['values']['priority'], 9223372036854775807)
        self.assertEqual(self.fixture['training']['excluded'],
                         [{'record': record('r-null'), 'reason': 'missing_text_image_and_vector'}])
        self.assertEqual(self.fixture['golden']['business_relevance']['status'], 'missing')
        with self.assertRaisesRegex(FixtureError, 'wrong_member_version'):
            self.oracle('view-v1').samples()

    def test_result_validator_detects_drop_duplicate_order_values_version_and_context(self):
        oracle = self.oracle()
        expected = oracle.samples()
        valid = {'context': deepcopy(oracle.context), 'rows': expected}
        oracle.assert_result(valid, expected)
        for mutation in ('drop', 'duplicate', 'order', 'member_version', 'value', 'context'):
            actual = deepcopy(valid)
            if mutation == 'drop':
                actual['rows'].pop()
            elif mutation == 'duplicate':
                actual['rows'][1] = deepcopy(actual['rows'][0])
            elif mutation == 'order':
                actual['rows'].reverse()
            elif mutation == 'member_version':
                actual['rows'][0]['members'][1]['record']['record_version'] = '1'
            elif mutation == 'value':
                actual['rows'][0]['members'][1]['values']['priority'] -= 1
            else:
                actual['context']['read_view_id'] = 'latest'
            with self.subTest(mutation=mutation), self.assertRaises(FixtureError):
                oracle.assert_result(actual, expected)

    def test_score_tolerance_keeps_integer_and_boolean_values_exact(self):
        oracle = self.oracle()
        expected = oracle.bm25(['权限'])
        actual = {'context': deepcopy(oracle.context), 'rows': deepcopy(expected)}
        actual['rows'][0]['score'] += 5e-13
        oracle.assert_result(actual, expected)
        actual['rows'][0]['score'] += 2e-12
        with self.assertRaisesRegex(FixtureError, 'result_mismatch'):
            oracle.assert_result(actual, expected)
        for value in (9007199254740992.0, True):
            with self.subTest(value=value), self.assertRaisesRegex(FixtureError, 'result_mismatch'):
                oracle.assert_result({'context': oracle.context, 'rows': [value]}, [9007199254740993])
        with self.assertRaisesRegex(FixtureError, 'result_mismatch'):
            oracle.assert_result({'context': oracle.context, 'rows': [1]}, [True])

    def test_new_publication_does_not_change_accepted_old_source_values(self):
        previous = self.oracle('view-v1')
        current = self.oracle()
        self.assertEqual(previous.exact_l2([0, 0, 0])[1], dict(record('r-a1', '1'), distance=.25))
        self.assertEqual(current.exact_l2([0, 0, 0])[0], dict(record('r-a1', '2'), distance=0.0))
        self.assertEqual(previous.rows[('r-a1', '1')]['priority'], 0)
        documents = deepcopy(self.fixture)
        held = OutlineOracle(documents)
        before = held.samples()
        documents['corpus']['records'][1]['priority'] = -1
        self.assertEqual(held.samples(), before)
        with self.assertRaisesRegex(FixtureError, 'result_view_mismatch'):
            previous.assert_result({'context': current.context, 'rows': previous.selection()}, previous.selection())

    def test_working_set_categories_and_missing_claims_are_explicit(self):
        summary = self.oracle().summary()
        self.assertEqual(summary['feature_values_bytes'], 10 * 3 * 8)
        self.assertEqual(set(summary['working_sets']), {'facts', 'vectors', 'index', 'media'})
        self.assertEqual({name: value['fixture_bytes'] for name, value in summary['working_sets'].items()},
                         {'facts': 24895, 'vectors': 4169, 'index': 2457, 'media': 846})
        for budget in self.fixture['budgets']['working_sets'].values():
            self.assertIsNone(budget['production_bytes'])
            self.assertEqual(budget['production_cache_status'], 'missing')
        self.assertIn('independent-business-human-relevance', summary['missing'])
        self.assertEqual(self.fixture['comparisons']['status'], 'design-comparison-no-performance-result')
        self.assertTrue(all('missing' in item['measurement'] for item in self.fixture['comparisons']['alternatives']))

    def test_oracle_imports_cannot_use_production_query_index_or_split(self):
        directory = Path(__file__).resolve().parents[1] / 'outline_oracles'
        allowed = {'collections', 'copy', 'hashlib', 'json', 'math', 'pathlib'}
        for source in directory.glob('*.py'):
            for node in ast.walk(ast.parse(source.read_text())):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name, allowed)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertIn(node.module, allowed)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {'__import__', 'eval', 'exec'})


if __name__ == '__main__':
    unittest.main()
