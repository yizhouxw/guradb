"""Independent relation oracle for the bounded one-hop Graph operator."""
import unittest

from modules.common.contracts import Budget, Failure
from modules.index.graph import expand


def bundle(kind='text'):
    facts = [('z', 'a', 'b', 'knows'), ('b', 'b', 'c', 'knows'),
             ('a', 'a', 'a', 'knows'), ('x', 'a', 'c', 'likes')]
    if kind == 'int8':
        mapping = {'a': 9223372036854775807, 'b': -4, 'c': 2}
        facts = [(key, mapping[left], mapping[right], label) for key, left, right, label in facts]
    return {'manifest': {'schema': [{'name': 'src', 'data_type': kind},
                                    {'name': 'dst', 'data_type': kind},
                                    {'name': 'label', 'data_type': 'text'}]},
            'rows': [{'logical_key': key, 'values': {'src': left, 'dst': right, 'label': label}}
                     for key, left, right, label in facts], 'revision': 'rev-fixed',
            'context': {'view_id': 'view-fixed'}}


def request(**kwargs):
    return {'source_field': 'src', 'target_field': 'dst', 'type_field': 'label',
            'seeds': ['a', 'b'], 'type': 'knows', **kwargs}


class GraphTruth(unittest.TestCase):
    def test_relational_truth_and_stable_order(self):
        data = bundle()
        for direction in ('out', 'in', 'both'):
            query = request(direction=direction)
            # Independent SELECT/UNION interpretation with self-loop deduplication.
            expected = set()
            for edge in data['rows']:
                value = edge['values']
                for seed in query['seeds']:
                    if value['label'] != 'knows':
                        continue
                    if direction != 'in' and value['src'] == seed:
                        expected.add((edge['logical_key'], seed, value['dst'], 'out'))
                    if direction != 'out' and value['dst'] == seed:
                        if direction != 'both' or value['src'] != seed:
                            expected.add((edge['logical_key'], seed, value['src'], 'in'))
            result = expand(data, query, Budget())
            self.assertEqual({(p['logical_key'], p['seed'], p['neighbor'], p['direction'])
                              for p in result['paths']}, expected)
            self.assertTrue(all(p['record_version'] == 'rev-fixed' for p in result['paths']))
            self.assertEqual(result['read_context'], data['context'])
            data['rows'].reverse()
            self.assertEqual(result, expand(data, query, Budget()))

    def test_int8_strings(self):
        result = expand(bundle('int8'), request(seeds=['9223372036854775807']), Budget())
        self.assertEqual([p['logical_key'] for p in result['paths']], ['a', 'z'])
        self.assertEqual(result['paths'][1]['target'], '-4')

    def test_limits_cancel_timeout(self):
        cases = [(request(max_edges=1), Budget(), 'resource_limit'),
                 (request(max_fanout=1), Budget(), 'resource_limit'),
                 (request(), Budget(cancelled=lambda: True), 'cancelled'),
                 (request(), Budget(seconds=-1), 'timeout')]
        for query, budget, code in cases:
            with self.assertRaises(Failure) as caught:
                expand(bundle(), query, budget)
            self.assertEqual(caught.exception.code, code)

    def test_cancellation_during_scan(self):
        checks = 0
        def cancelled():
            nonlocal checks
            checks += 1
            return checks > 6
        with self.assertRaises(Failure) as caught:
            expand(bundle(), request(), Budget(cancelled=cancelled))
        self.assertEqual(caught.exception.code, 'cancelled')

    def test_high_fanout_fails_closed(self):
        data = bundle()
        data['rows'] = [{'logical_key': str(i), 'values': {'src': 'a', 'dst': str(i), 'label': 'knows'}}
                        for i in range(1001)]
        with self.assertRaises(Failure) as caught:
            expand(data, request(max_edges=1000, max_fanout=1000), Budget())
        self.assertEqual(caught.exception.code, 'resource_limit')


if __name__ == '__main__':
    unittest.main()
