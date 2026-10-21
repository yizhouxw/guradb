"""Independent source-level truth for P01, intentionally standard-library only."""
from collections import Counter, deque
from copy import deepcopy
import math

from .fixture import FixtureError, identity, load_fixture, ref, require, validate_fixture


def cf1_int8_or_null(value):
    """Expected CF1-A scalar encoding; source truth keeps arbitrary-precision ints."""
    if value is None:
        return {'type': 'null', 'value': None}
    require(type(value) is int and -(2**63) <= value < 2**63, 'invalid_int8', str(value))
    return {'type': 'int8', 'value': str(value)}


class OutlineOracle:
    """Private bounded truth methods, not a second public query API."""

    def __init__(self, documents=None, view_id='view-v2'):
        self.documents = deepcopy(load_fixture() if documents is None else validate_fixture(documents))
        corpus = self.documents['corpus']
        views = {v['read_view_id']: v for v in corpus['views']}
        require(view_id in views, 'invalid_view', view_id)
        self.view = deepcopy(views[view_id])
        self.context = {name: self.view[name] for name in
                        ('read_view_id', 'data_revision_id', 'source_version_id')}
        self.context['dataset_id'] = corpus['dataset_id']
        visible = {identity(r) for r in self.view['records']}
        self.rows = {identity(r): r for r in corpus['records'] if identity(r) in visible}
        self.features = {identity(f['parent']): f for f in self.documents['features']['features']
                         if identity(f['parent']) in visible}

    def selection(self, predicate=None):
        if predicate is None:
            return [ref(key) for key in sorted(self.rows)]
        require(isinstance(predicate, dict) and set(predicate) <= {'field', 'op', 'value'},
                'unsupported_predicate', str(predicate))
        field, operator = predicate.get('field'), predicate.get('op')
        require(field in ('active', 'title', 'priority') and operator in ('eq', 'ge', 'is_null'),
                'unsupported_predicate', str(predicate))
        if operator == 'is_null':
            require(set(predicate) == {'field', 'op'}, 'unsupported_predicate', 'IS NULL has no value')
        else:
            require(set(predicate) == {'field', 'op', 'value'}, 'unsupported_predicate', 'missing value')
            value = predicate['value']
            valid = value is None or (field == 'active' and type(value) is bool) or (
                field == 'title' and isinstance(value, str)) or (
                field == 'priority' and type(value) is int and -(2**63) <= value < 2**63)
            require(valid and (operator != 'ge' or field == 'priority'), 'unsupported_predicate', 'type/operator')
        selected = []
        for key, row in sorted(self.rows.items()):
            actual = row[field]
            if operator == 'is_null':
                match = actual is None
            elif actual is None or value is None:
                # SQL UNKNOWN does not survive WHERE, including NULL = NULL.
                match = False
            else:
                match = actual == value if operator == 'eq' else actual >= value
            if match:
                selected.append(ref(key))
        return selected

    def exact_l2(self, vector, predicate=None, space_id='outline-synthetic-zh-image3', model_version='1'):
        space = self.documents['features']
        require((space_id, model_version) == (space['space_id'], space['model_version']) and
                isinstance(vector, list) and len(vector) == space['dimension'] and
                all(type(v) in (int, float) and math.isfinite(v) for v in vector),
                'wrong_feature_space', 'query')
        eligible = {identity(r) for r in self.selection(predicate)}
        distances = []
        for key, feature in self.features.items():
            if key in eligible:
                distance = math.fsum((a - b) ** 2 for a, b in zip(vector, feature['vector']))
                distances.append((distance, key))
        return [dict(ref(key), distance=distance) for distance, key in sorted(distances)]

    def bm25(self, tokens, predicate=None):
        require(isinstance(tokens, list) and tokens and all(isinstance(t, str) and t for t in tokens),
                'invalid_tokens', 'query tokens')
        # All visible facts participate, including NULL/empty text; filters are applied last.
        term_counts = {key: Counter(row['tokens']) for key, row in self.rows.items()}
        lengths = {key: len(row['tokens']) for key, row in self.rows.items()}
        count = len(self.rows)
        average = sum(lengths.values()) / count if count else 0
        frequencies = {token: sum(token in words for words in term_counts.values()) for token in tokens}
        eligible = {identity(r) for r in self.selection(predicate)}
        scored = []
        for key, words in term_counts.items():
            if key not in eligible:
                continue
            score = 0.0
            for token in tokens:
                tf, df = words[token], frequencies[token]
                if tf:
                    idf = math.log1p((count - df + .5) / (df + .5))
                    norm = tf + 1.2 * (.25 + .75 * lengths[key] / average)
                    score += idf * tf * 2.2 / norm
            if score:
                scored.append((score, key))
        return [dict(ref(key), score=score) for score, key in sorted(scored, key=lambda item: (-item[0], item[1]))]

    def graph(self, root, relation='cites', max_depth=2):
        require(relation == 'cites' and type(max_depth) is int and 1 <= max_depth <= 3,
                'unsupported_graph', 'relation or depth')
        require(self.context['read_view_id'] == 'view-v2', 'index_view_mismatch', 'fixture edges view')
        start = identity(root)
        require(start in self.rows, 'unknown_record', str(start))
        adjacency = {}
        for edge in self.documents['edges']:
            source, target = identity(edge['source']), identity(edge['target'])
            require(source in self.rows and target in self.rows, 'index_view_mismatch', edge['edge_id'])
            if edge['relation'] == relation:
                adjacency.setdefault(source, set()).add(target)
        queue, visited, result = deque([(start, 0)]), {start}, []
        while queue:
            node, depth = queue.popleft()
            if depth == max_depth:
                continue
            for neighbor in sorted(adjacency.get(node, ())):
                if neighbor not in visited:
                    visited.add(neighbor)
                    result.append((depth + 1, neighbor))
                    queue.append((neighbor, depth + 1))
        return [dict(ref(key), depth=depth) for depth, key in sorted(result)]

    def samples(self):
        training = self.documents['training']
        require(training['view_id'] == self.context['read_view_id'], 'wrong_member_version', 'training view')
        rows = []
        fragments = {(f['fragment_id'], f['fragment_version']): f for f in self.documents['fragments']}
        for sample in sorted(training['samples'], key=lambda s: (s['sample_id'], s['sample_version'])):
            members = []
            for member in sample['members']:
                key = identity(member['record'])
                fragment = fragments[(member['fragment_id'], member['fragment_version'])]
                members.append(dict(deepcopy(member), values=deepcopy(self.rows[key]),
                                    fragment=deepcopy(fragment),
                                    vector=deepcopy(self.features[key]['vector'])))
            rows.append(dict(deepcopy(sample), members=members, recipe=deepcopy(training['recipe'])))
        return rows

    def assert_result(self, actual, expected):
        """Compare identity, version, values, ordering and accepted fixed context."""
        require(isinstance(actual, dict) and actual.get('context') == self.context,
                'result_view_mismatch', 'accepted context')
        require(self._same_value(actual.get('rows'), expected), 'result_mismatch', 'ordered full values')

    def _same_value(self, actual, expected):
        if isinstance(expected, dict):
            return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
                self._same_value(actual[key], value) for key, value in expected.items())
        if isinstance(expected, list):
            return isinstance(actual, list) and len(actual) == len(expected) and all(
                self._same_value(a, b) for a, b in zip(actual, expected))
        if type(expected) is float:
            tolerance = self.documents['budgets']['quality']['score_absolute_tolerance']
            return type(actual) in (int, float) and math.isfinite(actual) and math.isclose(
                actual, expected, rel_tol=0, abs_tol=tolerance)
        return type(actual) is type(expected) and actual == expected

    def summary(self):
        manifest = self.documents['manifest']
        working_sets = {}
        for category in ('facts', 'vectors', 'index', 'media'):
            inputs = [entry for entry in manifest['inputs'] if entry['category'] == category]
            byte_count = sum(entry['size_bytes'] for entry in inputs)
            limit = self.documents['budgets']['working_sets'][category]['max_fixture_bytes']
            require(byte_count <= limit, 'input_budget', category)
            working_sets[category] = {'fixture_bytes': byte_count, 'files': len(inputs),
                                      'max_fixture_bytes': limit, 'production': 'missing'}
        selections = {case['case_id']: {'selected': len(case['expected']), 'visible': len(self.rows),
                                      'selectivity': len(case['expected']) / len(self.rows)}
                      for case in self.documents['golden']['selection']}
        counts = Counter(sample['split'] for sample in self.samples())
        return {'evidence_class': 'module-only-synthetic', 'manifest_sha256': self.documents['manifest_sha256'],
                'context': deepcopy(self.context), 'record_versions': len(self.documents['corpus']['records']),
                'visible_records': len(self.rows), 'feature_values_bytes': len(self.features) * 3 * 8,
                'sample_counts': dict(sorted(counts.items())), 'groups': len(self.documents['groups']['groups']),
                'excluded_missing_modality': len(self.documents['training']['excluded']),
                'selection': selections, 'working_sets': working_sets,
                'missing': ['independent-business-human-relevance', 'real-embedding-and-reranker',
                            'ann-quality', 'real-framework-consumption', 'authorization-retention-cancellation',
                            'cold-warm-and-greater-than-cache', 'production-index-get-bytes-rss-cost']}

    def verify_golden(self):
        golden = self.documents['golden']
        for case in golden['selection']:
            require(self.selection(case['predicate']) == case['expected'], 'golden_mismatch', case['case_id'])
        require(self.exact_l2(golden['l2']['vector']) == golden['l2']['expected'], 'golden_mismatch', 'exact l2')
        require([{k: hit[k] for k in ('record_id', 'record_version')} for hit in self.bm25(golden['bm25']['tokens'])]
                == golden['bm25']['expected'], 'golden_mismatch', 'bm25 order')
        graph = golden['graph']
        require(self.graph(graph['root'], graph['relation'], graph['max_depth']) == graph['expected'],
                'golden_mismatch', 'graph')
        require([sample['sample_id'] for sample in self.samples()] == golden['samples'], 'golden_mismatch', 'samples')
        return self.summary()
