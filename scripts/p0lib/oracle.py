"""Standard-library truth from source inputs, never from serving bundle rows.

This is the synthetic component contract for bm25-global-v2, exact squared L2,
RRF k=60 and training split v1. It is deliberately not a production evaluator.
View/revision metadata must be fixed by the driver before observing responses.
ANN is compared with exhaustive truth; this does not certify partial probes.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import re


def canonical(value):
    """Canonical JSON is part of the published split/values contract."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def logical_key(value, kind='long'):
    """Independent implementation of the v1 single-field identity encoding."""
    if kind == 'long' and type(value) is int and -(2**63) <= value < 2**63:
        tag, raw = b'\x02', value.to_bytes(8, 'big', signed=True)
    elif kind == 'string' and type(value) is str:
        tag, raw = b'\x01', value.encode('utf-8')
    else:
        raise ValueError('source key must be a non-NULL supported stable key')
    if len(raw) > 4096:
        raise ValueError('source key exceeds the existing 4096-byte boundary')
    return (b'\x01\x00\x00\x00\x01' + tag + len(raw).to_bytes(4, 'big') + raw).hex()


def public_values(values):
    return {name: str(value) if type(value) is int else value for name, value in values.items()}


def split_bucket(seed, dataset_id, logical):
    payload = canonical([seed, [dataset_id, 'record', logical]]).encode('utf-8')
    # Hex conversion is independent of the production digest-byte conversion.
    return int(hashlib.sha256(payload).hexdigest()[:16], 16) % 10000


def assert_accepted_context(handle, result):
    """A correct response for another known view is still a fixed-view failure."""
    assert result['read_context'] == handle['read_context'], 'accepted job view changed during execution'


class SourceOracle:
    """Freeze supplied source rows/features and preserve append-only versions."""

    def __init__(self, rows, feature_value, *, dataset_id, revision, read_context,
                 previous=None, key_field='id', key_type='long', text_field='title',
                 field_types=None):
        self.dataset_id, self.revision = dataset_id, revision
        self.read_context = deepcopy(read_context)
        self.key_field, self.key_type, self.text_field = key_field, key_type, text_field
        self.field_types = dict(field_types or {'id': 'int8', 'title': 'text', 'active': 'bool'})
        if not dataset_id or not revision or self.read_context.get('data_revision_id') != revision:
            raise ValueError('oracle needs an explicit matching data revision and read view')
        if not self.read_context.get('read_view_id'):
            raise ValueError('oracle needs a fixed read view')
        if not 0 < len(rows) <= 10000:
            raise ValueError('source must respect the existing 10000-row boundary')
        self.model = {name: feature_value[name] for name in
                      ('model', 'dimension', 'metric', 'preprocessing')}
        if (type(self.model['model']) is not str or not 0 < len(self.model['model']) <= 128
                or type(self.model['dimension']) is not int or not 1 <= self.model['dimension'] <= 256
                or self.model['metric'] != 'squared_l2'
                or self.model['preprocessing'] != 'identity-v1'):
            raise ValueError('features are outside the fixed supported model contract')
        features = {}
        for supplied in feature_value['records']:
            item = deepcopy(supplied)
            logical = item['logical_key']
            if logical in features or set(item) != {'logical_key', 'vector', 'media'}:
                raise ValueError('feature identities must be unique and explicit')
            vector = item['vector']
            if (len(vector) != self.model['dimension'] or any(type(v) not in (int, float)
                    or not math.isfinite(v) or abs(v) > 1e6 for v in vector)):
                raise ValueError('invalid source vector')
            if not isinstance(item['media'], list) or len(item['media']) > 4:
                raise ValueError('invalid source media list')
            for media in item['media']:
                if (set(media) != {'uri', 'sha256', 'size_bytes'}
                        or type(media['size_bytes']) is not int or media['size_bytes'] <= 0
                        or not re.fullmatch('[0-9a-f]{64}', media['sha256'])):
                    raise ValueError('media must be an unmaterialized source reference')
            features[logical] = item
        records = {}
        for supplied in rows:
            values = deepcopy(supplied)
            logical = logical_key(values[key_field], key_type)
            if logical in records:
                raise ValueError('duplicate source key; last-write-wins is forbidden')
            if logical not in features or set(values) != set(self.field_types):
                raise ValueError('source schema and exact feature identity coverage are required')
            for name, kind in self.field_types.items():
                if values[name] is not None and type(values[name]) is not {
                        'int8': int, 'bool': bool, 'text': str}[kind]:
                    raise ValueError('source value does not match the fixed field type')
            records[logical] = {'logical_key': logical, 'record_version': revision, 'values': values,
                                'vector': list(features[logical]['vector']),
                                'media': deepcopy(features[logical]['media'])}
        if set(records) != set(features):
            raise ValueError('features must exactly cover source records')
        if previous is not None:
            if (previous.dataset_id != dataset_id or previous.model != self.model
                    or previous.field_types != self.field_types
                    or (previous.key_field, previous.key_type, previous.text_field)
                    != (key_field, key_type, text_field)):
                raise ValueError('append cannot change dataset, identity, schema or model')
            if set(records) - set(previous._records) and revision in {
                    previous.revision, *(row['record_version'] for row in previous._records.values())}:
                raise ValueError('new source records require a new data revision')
            for logical, old in previous._records.items():
                current = records.get(logical)
                if current is None or any(current[name] != old[name] for name in ('values', 'vector', 'media')):
                    raise ValueError('append cannot delete or rewrite an old source record')
                current['record_version'] = old['record_version']
        self._records = records
        self.row_count = len(records)
        # The entire source corpus contributes statistics, including filtered/NULL rows.
        self._terms = {logical: Counter(re.findall('[a-z0-9]+', row['values'][text_field].lower()
                       if row['values'][text_field] is not None else ''))
                       for logical, row in records.items()}
        self._lengths = {logical: sum(counts.values()) for logical, counts in self._terms.items()}
        self._average_length = sum(self._lengths.values()) / self.row_count

    def _allowed(self, request):
        if 'filter' not in request:
            return set(self._records)
        selected = request['filter']
        if (not isinstance(selected, dict) or set(selected) != {'field', 'equals'}
                or selected['field'] not in self.field_types):
            raise ValueError('unsupported filter')
        field, value = selected['field'], selected['equals']
        kind = self.field_types[field]
        if value is not None and kind == 'int8':
            if type(value) is str:
                if not re.fullmatch('-?(0|[1-9][0-9]*)', value) or str(int(value)) != value:
                    raise ValueError('integer filter must be canonical decimal')
                value = int(value)
                if not -(2**63) <= value < 2**63:
                    raise ValueError('integer filter outside int64')
            elif type(value) is not int or abs(value) > 2**53 - 1:
                raise ValueError('integer filter must use safe JSON integer or canonical text')
        elif value is not None and type(value) is not {'text': str, 'bool': bool}[kind]:
            raise ValueError('filter type mismatch')
        return {logical for logical, row in self._records.items()
                if type(row['values'][field]) is type(value) and row['values'][field] == value}

    def _rankings(self, request):
        if not set(request) <= {'text', 'vector', 'model', 'top_k', 'candidate_limit', 'filter',
                                 'vector_index', 'nprobes'}:
            raise ValueError('unsupported search field')
        mode = request.get('vector_index', 'exact')
        if (mode not in ('exact', 'ann')
                or ('vector' not in request and {'model', 'vector_index', 'nprobes'} & set(request))
                or ('nprobes' in request and (mode != 'ann' or type(request['nprobes']) is not int
                                             or not 1 <= request['nprobes'] <= 64))):
            raise ValueError('unsupported vector route options')
        limit, top = request.get('candidate_limit', 100), request.get('top_k', 10)
        if type(top) is not int or type(limit) is not int or not 1 <= top <= limit <= 1000:
            raise ValueError('candidate window outside the current bounded contract')
        allowed, rankings = self._allowed(request), []
        if 'text' in request:
            text = request['text']
            if not isinstance(text, str) or len(text) > 512 or not re.fullmatch('[A-Za-z0-9 ]+', text):
                raise ValueError('unsupported ASCII query')
            query_terms = text.lower().split()
            if not 1 <= len(query_terms) <= 16 or any(len(word) > 40 for word in query_terms):
                raise ValueError('query token boundary exceeded')
            document_frequency = {word: sum(word in counts for counts in self._terms.values())
                                  for word in set(query_terms)}
            scores = {}
            for logical in allowed:
                counts, length = self._terms[logical], self._lengths[logical]
                contributions = []
                for word in query_terms:
                    frequency = counts[word]
                    if frequency:
                        # Algebraic BM25 formula uses independent source-derived N/df/dl.
                        inverse_frequency = math.log((self.row_count + 1) / (document_frequency[word] + .5))
                        norm = .3 + .9 * length / self._average_length
                        contributions.append(inverse_frequency * 2.2 / (1 + norm / frequency))
                if contributions:
                    scores[logical] = math.fsum(contributions)
            rankings.append(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit])
        if 'vector' in request:
            vector = request['vector']
            if request.get('model') != self.model['model']:
                raise ValueError('query model differs from fixed source model')
            if len(vector) != self.model['dimension'] or any(type(v) not in (int, float)
                    or not math.isfinite(v) or abs(v) > 1e6 for v in vector):
                raise ValueError('invalid query vector')
            distances = {logical: math.fsum(pow(self._records[logical]['vector'][axis] - value, 2)
                         for axis, value in enumerate(vector)) for logical in allowed}
            ordered = sorted(distances, key=lambda logical: (distances[logical], logical))[:limit]
            rankings.append([(logical, -distances[logical]) for logical in ordered])
        if not rankings:
            raise ValueError('text or vector is required')
        return rankings

    def expected_hits(self, request):
        rankings = self._rankings(request)
        if len(rankings) == 1:
            scores = dict(rankings[0])
        else:
            candidates = {logical for ranking in rankings for logical, _ in ranking}
            positions = [{logical: i + 1 for i, (logical, _) in enumerate(ranking)} for ranking in rankings]
            scores = {logical: sum(1 / (60 + ranks[logical]) for ranks in positions if logical in ranks)
                      for logical in candidates}
        ordered = sorted(scores, key=lambda logical: (-scores[logical], logical))[:request.get('top_k', 10)]
        return [dict(self._public_record(logical), score=scores[logical]) for logical in ordered]

    def _public_record(self, logical):
        row = self._records[logical]
        return {'logical_key': logical, 'record_version': row['record_version'],
                'values': public_values(row['values']), 'media': deepcopy(row['media'])}

    def expected_samples(self, request):
        seed, threshold = request.get('seed', '0'), request.get('train_basis_points', 8000)
        if (not set(request) <= {'seed', 'train_basis_points'} or type(seed) is not str
                or len(seed) > 128 or type(threshold) is not int or not 0 <= threshold <= 10000):
            raise ValueError('unsupported training request')
        return [{'dataset_id': self.dataset_id, 'entity_kind': 'record', 'logical_key': logical,
                 'record_version': row['record_version'],
                 'split': 'train' if split_bucket(seed, self.dataset_id, logical) < threshold else 'validation',
                 'values_json': canonical(public_values(row['values'])), 'vector': list(row['vector']),
                 'media_json': canonical(row['media'])}
                for logical, row in sorted(self._records.items())]

    def assert_materialized(self, rows):
        """Check an observed build against prior source inputs, including duplicates."""
        actual = deepcopy(rows)
        for row in actual:
            row['media'] = [{name: value for name, value in media.items() if name != 'copy'}
                            for media in row['media']]
        expected = [self._records[logical] for logical in sorted(self._records)]
        assert sorted(actual, key=lambda row: row['logical_key']) == expected, 'materialized source/feature/version mismatch'

    def assert_search(self, result, request):
        assert result['read_context'] == self.read_context, 'search returned a different view'
        expected = self.expected_hits(request)
        assert len(result['hits']) == len(expected), 'search hit count differs from independent truth'
        for actual, wanted in zip(result['hits'], expected):
            assert {k: v for k, v in actual.items() if k != 'score'} == {
                k: v for k, v in wanted.items() if k != 'score'}, 'search identity/order/version/payload mismatch'
            assert type(actual['score']) in (int, float) and math.isclose(
                actual['score'], wanted['score'], rel_tol=1e-12, abs_tol=1e-14), 'search score mismatch'
        mode = request.get('vector_index', 'exact')
        ranking = ('rrf-k60-ann' if mode == 'ann' else 'rrf-k60') if 'text' in request and 'vector' in request else (
            'bm25' if 'text' in request else mode + '-squared-l2')
        assert result['ranking'] == ranking, 'search ranking contract mismatch'

    def assert_scan(self, result, request=None):
        request = request or {'limit': 1000}
        expected = [self._public_record(logical) for logical in sorted(self._records)]
        assert result['read_context'] == self.read_context, 'scan returned a different view'
        assert result['rows'] == expected[:request.get('limit', 100)], 'scan source/order/version mismatch'
        assert result['truncated'] == (self.row_count > request.get('limit', 100)), 'scan truncation mismatch'

    def assert_training(self, result, request):
        assert result['read_context'] == self.read_context, 'training returned a different view'
        assert result['samples'] == self.expected_samples(request), 'training sample/split/order/version/feature mismatch'
        assert result['rows'] == self.row_count, 'training row count mismatch'
        assert result['model'] == self.model, 'training model mismatch'
        assert result['seed'] == request.get('seed', '0'), 'training seed mismatch'
        assert result['train_basis_points'] == request.get('train_basis_points', 8000), 'training split threshold mismatch'
        assert result['retention_mode'] == 'managed-copy', 'training retention mismatch'
