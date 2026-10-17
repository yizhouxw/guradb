"""Graph request and immutable fact rejection contracts."""
import copy
import unittest

from modules.common.contracts import Budget, Failure
from modules.index.graph import expand
from tests.functional.graph import bundle, request


class GraphContract(unittest.TestCase):
    def rejects(self, data, query, code='invalid_request'):
        with self.assertRaises(Failure) as caught:
            expand(data, query, Budget())
        self.assertEqual(caught.exception.code, code)

    def test_request_whitelist(self):
        for patch in [{'depth': 2}, {'direction': 'sideways'}, {'seeds': []},
                      {'seeds': ['a', 'a']}, {'seeds': [True]}, {'seeds': ['a'] * 129},
                      {'source_field': 'absent'}, {'target_field': 'src'},
                      {'type': None}, {'type': ''}, {'type': 'x' * 4097}]:
            self.rejects(bundle(), request(**patch))
        for patch in [{'max_edges': 0}, {'max_edges': True}, {'max_fanout': 1001}]:
            self.rejects(bundle(), request(**patch), 'resource_limit')
        self.rejects(bundle(), {})
        self.rejects(bundle(), [])

    def test_numeric_contract(self):
        for seed in ['01', '-0', '+1', '9223372036854775808', 9223372036854775807, True, 1.0]:
            self.rejects(bundle('int8'), request(seeds=[seed]))
        self.rejects(bundle('int8'), request(seeds=['2', 2]))

    def test_invalid_facts_never_silently_skipped(self):
        for field, value in [('src', None), ('dst', 1), ('label', None)]:
            data = bundle()
            data['rows'][-1]['values'][field] = value
            self.rejects(data, request(), 'source_invalid')
        data = bundle()
        data['rows'].append(copy.deepcopy(data['rows'][0]))
        self.rejects(data, request(), 'source_invalid')
        data = bundle()
        data['manifest']['schema'][1]['data_type'] = 'int8'
        self.rejects(data, request())

    def test_empty_match_and_exact_limit(self):
        result = expand(bundle(), request(type='absent'), Budget())
        self.assertEqual(result['paths'], [])
        result = expand(bundle(), request(seeds=['a'], max_edges=2, max_fanout=2), Budget())
        self.assertEqual(len(result['paths']), 2)
        self.assertFalse(result['truncated'])
