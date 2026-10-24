"""Independent all-row Parquet/processing/flat-file checks, not production validation."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import pyarrow.parquet as pq
from tests.index_support.fixed_fixture import PROCESSING_MASK


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def decode_hex(value):
    return struct.unpack('>d', bytes.fromhex(value))[0]


def assert_ref(ref, path):
    raw = Path(path).read_bytes()
    assert len(raw) == ref['size_bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256']
    return raw


def all_row_audit(fixture, binding, indexes):
    """Enumerate physical groups independently; compare every identity/cell/feature/tf."""
    root, oracle = fixture['root'], fixture['oracle']
    source_ref = fixture['source_ref']
    assert_ref(source_ref, root / 'source.parquet')
    file = pq.ParquetFile(root / 'source.parquet')
    assert file.num_row_groups == 3
    assert b'ARROW:schema' not in (file.metadata.metadata or {})
    expected_schema = [(101, 'record_id', 'string', False, 'BYTE_ARRAY'),
                       (102, 'record_version', 'string', False, 'BYTE_ARRAY'),
                       (103, 'title', 'string', True, 'BYTE_ARRAY'), (104, 'active', 'bool', True, 'BOOLEAN'),
                       (105, 'priority', 'int64', True, 'INT64'), (106, 'tokens_text', 'string', True, 'BYTE_ARRAY')]
    actual_schema = []
    physical_schema = []
    kinds = {'string': 'text', 'int64': 'int8', 'bool': 'bool'}
    for index, field in enumerate(file.schema_arrow):
        field_id = int(field.metadata[b'PARQUET:field_id'])
        column = file.schema.column(index)
        actual_schema.append((field_id, field.name, str(field.type), field.nullable, column.physical_type))
        assert column.max_definition_level == int(field.nullable) and column.max_repetition_level == 0
        physical_schema.append({'source_field_id': field_id, 'name': field.name,
                                'type': kinds[str(field.type)], 'nullable': field.nullable})
    assert actual_schema == expected_schema
    source = binding.value['revision']['sources'][0]
    assert source['source_schema_sha256'] == sha(physical_schema)
    assert source['source_schema_sha256'] != binding.value['resource']['schema_sha256']
    assert [(item['source_field_id'], item['resource_field_id']) for item in source['field_mapping']] == [
        (101, 1), (102, 2), (103, 3), (104, 4), (105, 5), (106, 6)]
    physical, order = {}, []
    for group in range(file.num_row_groups):
        for offset, row in enumerate(file.read_row_group(group).to_pylist()):
            key = (row['record_id'], row['record_version'])
            assert key not in physical
            physical[key] = (row, group, offset)
            order.append(key)
    assert set(physical) == set(oracle.rows) == set(PROCESSING_MASK)
    assert order != sorted(order)
    for key, (row, _, _) in physical.items():
        truth = oracle.rows[key]
        for name in ('record_id', 'record_version', 'title', 'active', 'priority'):
            assert row[name] == truth[name] and type(row[name]) is type(truth[name])
        assert row['tokens_text'] == (' '.join(truth['tokens']) if truth['title'] is not None else None)
    raw_manifest = assert_ref(fixture['processing_ref'], root / 'processing.json')
    manifest = json.loads(raw_manifest)
    assert fixture['processing_ref'] in binding.value['revision']['objects']
    assert len(manifest['rows']) == len(physical) == 11
    manifest_by_id = {}
    ledger = []
    for row in manifest['rows']:
        key = (row['record_id'], row['record_version'])
        facts, group, offset = physical[key]
        location = row['locator']
        assert location == {'source_version_id': 'p06-source-v2', 'object': source_ref,
                            'row_group': group, 'row_offset': offset}
        cells = []
        for field in binding.value['resource']['fields']:
            value = facts[field['name']]
            cells.append({'type': 'null', 'value': None} if value is None else
                         {'type': field['type'], 'value': str(value) if field['type'] == 'int8' else value})
        assert row['source_cells_sha256'] == sha(cells)
        assert row['tokens'] == oracle.rows[key]['tokens']
        assert row['vector_state'] == PROCESSING_MASK[key]
        feature = oracle.features.get(key)
        if PROCESSING_MASK[key] == 'present':
            assert feature is not None
            assert [decode_hex(value) for value in row['vector_f64_hex']] == feature['vector']
            expected = {name: feature[name] for name in ('feature_id', 'feature_version', 'model_version',
                                                        'dimension', 'metric')}
            expected.update(record_id=key[0], record_version=key[1], model_id=feature['space_id'],
                            normalization='none', processing_version='zh-CN-hand-segmented-v1')
            assert row['feature_input'] == expected and row['vector_reason'] == ''
        else:
            assert feature is None and row['feature_input'] is None and row['vector_f64_hex'] == []
            assert row['vector_reason'] == 'fixture-explicit-missing-modality'
        manifest_by_id[key] = row
        ledger.append({'record_id': key[0], 'record_version': key[1], 'source_cells_sha256': sha(cells),
                       'row_group': group, 'row_offset': offset, 'vector_state': PROCESSING_MASK[key]})
    artifacts = []
    for artifact in indexes:
        raw = assert_ref(artifact['shards'][0], root / (artifact['kind'] + '.index'))
        body = json.loads(raw)
        assert canonical(body) == raw
        assert body['ledger'] == manifest['rows']
        assert body['coverage_sha256'] == sha(manifest['rows'])
        projected_mapping = [{name: row[name] for name in ('record_id', 'record_version', 'locator')}
                             for row in manifest['rows']]
        assert body['logical_mapping_sha256'] == artifact['logical_mapping_sha256'] == sha(projected_mapping)
        assert body['configuration_sha256'] == artifact['configuration_sha256'] == sha(body['configuration'])
        assert body['header']['processing_manifest'] == fixture['processing_ref']
        if artifact['kind'] == 'bm25':
            expected_rows, frequencies = [], Counter()
            for key, facts in sorted(oracle.rows.items()):
                counts = Counter(facts['tokens'])
                frequencies.update(counts.keys())
                expected_rows.append({'record_id': key[0], 'record_version': key[1], 'length': len(facts['tokens']),
                                      'terms': [[term, counts[term]] for term in sorted(counts)]})
            assert body['rows'] == expected_rows
            assert body['statistics'] == {'document_count': 11, 'total_tokens': 22,
                'document_frequencies': [[term, frequencies[term]] for term in sorted(frequencies)]}
            assert frequencies['权限'] == frequencies['缓存'] == 3
        else:
            expected_rows = [{'record_id': key[0], 'record_version': key[1],
                'vector_f64_hex': [struct.pack('>d', value).hex() for value in feature['vector']]}
                for key, feature in sorted(oracle.features.items())]
            assert body['rows'] == expected_rows
            assert body['statistics'] == {'source_count': 11, 'vector_count': 10, 'null_count': 1}
        artifacts.append({'artifact_id': artifact['artifact_id'], 'row_count': len(body['rows']),
                          'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw),
                          'statistics': body['statistics']})
    return {'all_source_rows': len(physical), 'all_processing_rows': len(manifest_by_id),
            'present_vectors': sum(value == 'present' for value in PROCESSING_MASK.values()),
            'explicit_null_vectors': sum(value == 'null' for value in PROCESSING_MASK.values()),
            'source_row_groups': file.num_row_groups, 'complete_ledger': ledger, 'artifacts': artifacts}


def compare_candidates(batch, expected, fixture):
    rows = batch['payload']['candidate_batch']['rows']
    assert [(row['record_id'], row['record_version']) for row in rows] == [
        (row['record_id'], row['record_version']) for row in expected]
    scores = []
    for actual, truth in zip(rows, expected):
        score = decode_hex(actual['score_f64_hex'])
        expected_score = truth.get('score', truth.get('distance'))
        assert math.isclose(score, expected_score, rel_tol=1e-12, abs_tol=1e-12)
        key = (actual['record_id'], actual['record_version'])
        assert actual['locator'] == fixture['physical'][key]['locator']
        scores.append({'record_id': key[0], 'actual': score, 'expected': expected_score,
                       'absolute_error': abs(score - expected_score)})
    return scores
