"""Actual sealed-file reopening, complete ledger and independent score comparisons."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules.common.cf1a_primitives import ContractFailure, canonical, digest
from modules.index import fixed_bm25, fixed_vectors
from modules.index.fixed_artifacts import (body_for, build_artifact, read_manifest, seal,
                                          validate_body, validate_source_batches)
from modules.index.fixed_candidates import FixedArtifactReader
from modules.index.fixed_layout import (closed, count, envelope, f64_hex, from_hex, mapping,
    object_ref, strict_json, tokens, validate_manifest, validate_tokens, verified_bytes)
from modules.index.fixed_scope import delta_usage
from tests.index_support.fixed_fixture import (build_pair, new_scope, prepare, query_for,
    reader_for, reference, rehash_binding, source_batches)


class PhysicalIndexes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = prepare(Path(self.temp.name))
        self.binding, self.indexes = build_pair(self.fixture)

    def rejected(self, callback, code=None):
        with self.assertRaises(ContractFailure) as caught:
            callback()
        if code:
            self.assertEqual(caught.exception.code, code)

    def test_actual_reopen_full_ledgers_and_independent_scores(self):
        reader, scope = reader_for(self.binding, self.fixture['objects'])
        for artifact in self.indexes:
            with self.subTest(kind=artifact['kind']):
                query = query_for(self.binding, artifact)
                result = reader.port().candidates(self.binding, query)
                body = json.loads(reader.port().read_artifact(self.binding, artifact['artifact_id']))
                self.assertEqual(body['ledger'], self.fixture['manifest']['rows'])
                self.assertEqual(len(body['ledger']), 11)
                self.assertEqual(artifact['logical_mapping_sha256'], digest(mapping(body['ledger'])))
                truth = (self.fixture['oracle'].bm25(['权限', '缓存']) if artifact['kind'] == 'bm25'
                         else self.fixture['oracle'].exact_l2([0, 0, 0]))
                self.assertEqual([(r['record_id'], r['record_version']) for r in result.value['rows']],
                                 [(r['record_id'], r['record_version']) for r in truth])
                for actual, expected in zip(result.value['rows'], truth):
                    self.assertAlmostEqual(from_hex(actual['score_f64_hex']),
                                           expected.get('score', expected.get('distance')), delta=1e-12)
                    self.assertEqual(actual['locator'], self.fixture['physical'][
                        (actual['record_id'], actual['record_version'])]['locator'])
                self.assertEqual(result.value['usage']['output_bytes'], len(result.encoded))
        self.assertEqual(scope.usage['object_requests'], 8)
        self.assertGreater(scope.metrics['checksum_bytes'], 0)
        self.assertGreater(scope.metrics['scanned_rows'], 0)
        self.assertEqual(self.fixture['physical'][('r-a1', '2')]['locator']['row_group'], 2)

    def test_filters_route_window_duplicate_terms_and_empty_results(self):
        for artifact in self.indexes:
            reader, _ = reader_for(self.binding, self.fixture['objects'])
            for ids in ([], ['unknown-record'], ['r-a1-copy', 'r-a2']):
                result = reader.candidates(self.binding, query_for(self.binding, artifact, ids=ids, top_k=1))
                self.assertLessEqual(len(result.value['rows']), 1)
                self.assertTrue(all(row['record_id'] in ids for row in result.value['rows']))
            reader, _ = reader_for(self.binding, self.fixture['objects'])
            one = reader.candidates(self.binding, query_for(self.binding, artifact, top_k=1))
            self.assertEqual(one.value['rows'][0]['record_id'], 'r-a1')
        reader, _ = reader_for(self.binding, self.fixture['objects'])
        missing = reader.candidates(self.binding, query_for(self.binding, self.indexes[0], text='无匹配'))
        self.assertEqual(missing.value['rows'], [])
        duplicated = reader.candidates(self.binding, query_for(self.binding, self.indexes[0], text='权限 权限'))
        expected = self.fixture['oracle'].bm25(['权限', '权限'])
        for actual, truth in zip(duplicated.value['rows'], expected):
            self.assertAlmostEqual(from_hex(actual['score_f64_hex']), truth['score'], delta=1e-12)
        self.rejected(lambda: reader.candidates(self.binding,
            query_for(self.binding, self.indexes[0], text=' \t\u3000')), 'invalid_contract')

    def test_inputs_missing_mask_versions_cells_and_locators_fail(self):
        f = self.fixture
        for change in (
            lambda m: m['rows'].pop(),
            lambda m: m['rows'][0].update(record_version='wrong'),
            lambda m: m['rows'][0].update(source_cells_sha256='f'*64),
            lambda m: m['rows'][0].update(tokens=['wrong']),
        ):
            manifest = deepcopy(f['manifest']); change(manifest)
            self.rejected(lambda: validate_source_batches(f['binding'],
                source_batches(f['binding'], f['objects'], f['source_ref']), manifest))
        changes = [lambda m: m.update(extra=1), lambda m: m.update(manifest_version='wrong'),
            lambda m: m.update(dataset_id='wrong'), lambda m: m.update(source_objects=[]),
            lambda m: m.update(source_objects=m['source_objects']*2),
            lambda m: m['rows'][0]['locator'].update(source_version_id='wrong'),
            lambda m: m['rows'][0].update(vector_state='null', vector_f64_hex=[], vector_reason=''),
            lambda m: m['rows'][0].update(vector_f64_hex=['7ff0000000000000']*3),
            lambda m: m['rows'].reverse(), lambda m: m['rows'].append(deepcopy(m['rows'][0])),
            lambda m: m['rows'][0].update(text_state='empty')]
        for change in changes:
            manifest = deepcopy(f['manifest']); change(manifest)
            self.rejected(lambda: validate_manifest(manifest, f['binding'], f['processing_ref']))
        self.rejected(lambda: validate_source_batches(f['binding'], [], f['manifest']))
        batches = source_batches(f['binding'], f['objects'], f['source_ref'])
        self.rejected(lambda: validate_source_batches(f['binding'], batches[::-1], f['manifest']))
        manifest = deepcopy(f['manifest']); manifest['configurations']['bm25']['text_field_id'] = 1
        self.rejected(lambda: validate_source_batches(f['binding'], batches, manifest))

    def test_materialized_content_and_descriptor_tampering(self):
        f = self.fixture
        for artifact in self.indexes:
            body = strict_json((f['root'] / (artifact['kind'] + '.index')).read_bytes())
            validate_body(body, artifact, f['manifest'], f['processing_ref'])
            for change in (lambda b: b.update(coverage_sha256='f'*64),
                           lambda b: b['statistics'].update(extra=1),
                           lambda b: b['header'].update(build_id='wrong'),
                           lambda b: b['rows'].pop(),
                           lambda b: b['ledger'][0]['locator'].update(row_offset=99)):
                changed = deepcopy(body); change(changed)
                self.rejected(lambda: validate_body(changed, artifact, f['manifest'], f['processing_ref']),
                              'corrupt_object')
            changed = deepcopy(artifact); changed['logical_mapping_sha256'] = 'f'*64
            self.rejected(lambda: validate_body(body, changed, f['manifest'], f['processing_ref']), 'corrupt_object')
            changed['format_version'] = 2
            self.rejected(lambda: validate_body(body, changed, f['manifest'], f['processing_ref']), 'unsupported_version')

    def test_seal_conflicts_errors_and_failures_keep_staging(self):
        path = self.fixture['root'] / 'sealed-test'
        seal(b'abc', path)
        self.assertEqual(path.read_bytes(), b'abc')
        self.rejected(lambda: seal(b'abc', path), 'conflict')
        self.rejected(lambda: seal(b'x' * ((1 << 20) + 1), path), 'resource_limit')
        self.rejected(lambda: seal(b'abc', path / 'missing'))
        failed = self.fixture['root'] / 'failed'
        with patch('modules.index.fixed_artifacts.os.fsync', side_effect=OSError('injected fsync')):
            self.rejected(lambda: seal(b'abc', failed), 'backend_unavailable')
        self.assertTrue(failed.exists())
        self.assertEqual(failed.read_bytes(), b'abc')

    def test_reader_unknown_context_query_capability_and_parent_limits(self):
        reader, scope = reader_for(self.binding, self.fixture['objects'])
        self.rejected(lambda: reader.read_artifact(self.binding, 'missing'))
        self.rejected(lambda: reader.candidates(self.binding, self.binding))
        q = query_for(self.binding, self.indexes[0]).value
        q['context_sha256'] = 'f'*64
        self.rejected(lambda: reader.candidates(self.binding, envelope('index_query', q)))
        value = self.binding.value; value['context']['budget']['top_k'] = 1
        limited = rehash_binding(value)
        limited_reader, _ = reader_for(limited, self.fixture['objects'])
        self.rejected(lambda: limited_reader.candidates(limited, query_for(limited, self.indexes[0])), 'resource_limit')
        self.rejected(lambda: scope.matches(limited))
        value = self.binding.value
        value['indexes'][0]['format_version'] = 2
        value['view']['index_requirements'][0]['format_version'] = 2
        changed = rehash_binding(value)
        unsupported, _ = reader_for(changed, self.fixture['objects'])
        self.rejected(lambda: unsupported.read_artifact(changed, self.indexes[0]['artifact_id']), 'unsupported_version')
        value = self.binding.value; value['context']['budget']['object_requests'] = 1
        limited = rehash_binding(value)
        limited_reader, _ = reader_for(limited, self.fixture['objects'])
        self.rejected(lambda: limited_reader.candidates(limited, query_for(limited, self.indexes[0])), 'resource_limit')

    def test_derived_record_versions_and_output_reauthorization(self):
        f = self.fixture
        value = f['binding'].value
        value['revision']['sources'][0]['field_mapping'][1].update(
            source_field_id=0, source_type='none', transform='revision_version')
        derived = rehash_binding(value)
        batches = source_batches(derived, f['objects'], f['source_ref'])
        self.rejected(lambda: validate_source_batches(derived, batches, f['manifest']))
        calls = {'number': 0}
        def epoch(_):
            calls['number'] += 1
            # Revoke after actual IO and scans, immediately before output.
            return 2 if calls['number'] >= 17 else 1
        reader, scope = reader_for(self.binding, f['objects'], reauthorize=epoch)
        self.rejected(lambda: reader.candidates(self.binding, query_for(self.binding, self.indexes[0])), 'revoked')
        self.assertEqual(scope.usage['object_requests'], 2)
        self.assertGreater(scope.metrics['scanned_rows'], 0)

    def test_raw_hash_short_missing_bad_json_and_semantic_corruption(self):
        f = self.fixture
        path = f['root'] / 'bm25.index'
        original = path.read_bytes()
        reader, _ = reader_for(self.binding, f['objects'])
        path.write_bytes(original[:-1])
        self.rejected(lambda: reader.candidates(self.binding, query_for(self.binding, self.indexes[0])), 'corrupt_object')
        path.unlink()
        self.rejected(lambda: reader.read_artifact(self.binding, 'p06-bm25'), 'missing_object')
        for raw in (b'{}', b'{not json', original.replace(b'"document_count":11', b'"document_count":10')):
            path.write_bytes(raw)
            changed = self.binding.value
            ref = reference(path)
            changed['indexes'][0]['shards'] = [ref]
            altered = rehash_binding(changed)
            f['objects'].register(ref, path)
            reader, _ = reader_for(altered, f['objects'])
            self.rejected(lambda: reader.read_artifact(altered, 'p06-bm25'), 'corrupt_object')

    def test_cancellation_epoch_deadline_and_cumulative_io(self):
        for callbacks, code in (({'cancelled': lambda: True}, 'cancelled'),
                                ({'reauthorize': lambda _: 2}, 'revoked'),
                                ({'now_unix_ms': lambda: 31000}, 'deadline'),
                                ({'reauthorize': lambda _: True}, 'invalid_contract')):
            self.rejected(lambda: new_scope(self.binding, **callbacks), code)
        state = {'epoch': 1, 'cancelled': False}
        reader, scope = reader_for(self.binding, self.fixture['objects'],
                                  reauthorize=lambda _: state['epoch'], cancelled=lambda: state['cancelled'])
        reader.candidates(self.binding, query_for(self.binding, self.indexes[1]))
        state['epoch'] = 2
        self.rejected(lambda: reader.candidates(self.binding, query_for(self.binding, self.indexes[1])), 'revoked')
        state.update(epoch=1, cancelled=True)
        self.rejected(lambda: scope.checkpoint(), 'cancelled')
        self.rejected(lambda: scope.charge('object_requests', 101), 'resource_limit')
        self.rejected(lambda: scope.charge('memory_bytes', 513 << 20), 'resource_limit')
        self.rejected(lambda: scope.charge('wrong', 1))
        self.rejected(lambda: scope.charge('object_requests', True))
        self.assertGreater(scope.usage['object_requests'], 0)
        self.assertEqual(delta_usage({'memory_bytes': 2, 'elapsed_ms': 1},
                                     {'memory_bytes': 3, 'elapsed_ms': 2}), {'memory_bytes': 3, 'elapsed_ms': 1})

    def test_monotonic_deadline_cannot_be_extended_by_frozen_or_rolled_back_wall(self):
        state = {'mono': 0.0, 'wall': 1001}
        scope = new_scope(self.binding, monotonic=lambda: state['mono'], now_unix_ms=lambda: state['wall'])
        initial = scope.deadline
        state.update(mono=10, wall=1000)
        scope.checkpoint()
        self.assertEqual(scope.deadline, initial)
        state['mono'] = 31
        self.rejected(scope.checkpoint, 'deadline')
        state.update(mono=0, wall=1001)
        scope = new_scope(self.binding, monotonic=lambda: state['mono'], now_unix_ms=lambda: state['wall'])
        state.update(mono=1, wall=30000)
        scope.checkpoint()
        self.assertEqual(scope.deadline, 2)
        state.update(mono=3, wall=1001)
        self.rejected(scope.checkpoint, 'deadline')

    def test_authority_callback_consumes_time_and_cancellation_rechecked_after_return(self):
        for change, code in ((lambda s: s.update(mono=31), 'deadline'),
                             (lambda s: s.update(wall=31000), 'deadline'),
                             (lambda s: s.update(cancelled=True), 'cancelled')):
            state = {'mono': 0.0, 'wall': 1001, 'cancelled': False, 'active': False}
            def authority(_):
                if state['active']:
                    change(state)
                return 1
            scope = new_scope(self.binding, monotonic=lambda: state['mono'], now_unix_ms=lambda: state['wall'],
                              cancelled=lambda: state['cancelled'], reauthorize=authority)
            state['active'] = True
            self.rejected(scope.checkpoint, code)

    def test_final_cancellation_callback_returns_false_after_consuming_deadline(self):
        state = {'mono': 0.0, 'calls': 0, 'active': False}
        def cancelled():
            state['calls'] += 1
            if state['active'] and state['calls'] == 2:
                state['mono'] = 31
            return False
        scope = new_scope(self.binding, monotonic=lambda: state['mono'], now_unix_ms=lambda: 1001,
                          cancelled=cancelled)
        state.update(calls=0, active=True)
        self.rejected(scope.checkpoint, 'deadline')
        self.assertEqual(state['calls'], 2)
        state.update(mono=0.0, calls=0, active=False)
        def cancel_before_output():
            if state['active'] and scope.metrics['scanned_rows'] == 11:
                state['calls'] += 1
                if state['calls'] == 2:
                    state['mono'] = 31
            return False
        reader, scope = reader_for(self.binding, self.fixture['objects'], cancelled=cancel_before_output,
                                  monotonic=lambda: state['mono'], now_unix_ms=lambda: 1001)
        state['active'] = True
        self.rejected(lambda: reader.candidates(self.binding, query_for(self.binding, self.indexes[0])), 'deadline')
        self.assertEqual(scope.metrics['scanned_rows'], 11)
        self.assertEqual(state['calls'], 2)

    def test_real_physical_schema_field_ids_are_distinct_from_resource_roles(self):
        import pyarrow.parquet as pq
        from tests.index_support.fixed_fixture import SOURCE_FIELDS, source_schema
        from tests.index_support.fixed_audit import all_row_audit
        file = pq.ParquetFile(self.fixture['root'] / 'source.parquet')
        physical = source_schema(file)
        self.assertEqual(physical, SOURCE_FIELDS)
        self.assertFalse(file.schema_arrow.field('record_id').nullable)
        source = self.binding.value['revision']['sources'][0]
        self.assertEqual(source['source_schema_sha256'], digest(physical))
        self.assertNotEqual(source['source_schema_sha256'], source['resource_schema_sha256'])
        self.assertEqual(all_row_audit(self.fixture, self.binding, self.indexes)['all_source_rows'], 11)


class LayoutAndAlgorithms(unittest.TestCase):
    def rejected(self, callback):
        with self.assertRaises(ContractFailure): callback()

    def test_private_json_canonical_and_number_boundaries(self):
        self.assertEqual(strict_json(canonical({'中文': [1, True, None]})), {'中文': [1, True, None]})
        for raw in (b'{"a":1,"a":1}', b'{"a":-0}', b'{"a":1.0}', b'{"a":NaN}',
                    b'{"a":9007199254740992}', b'{"a":-1}', b'{} ', b'\xff', b'',
                    b'['*34 + b'0' + b']'*34):
            self.rejected(lambda: strict_json(raw))
        self.rejected(lambda: strict_json(b'['*1100 + b'0' + b']'*1100))
        self.rejected(lambda: count(True))
        self.rejected(lambda: closed({}, ['missing']))
        self.assertEqual(tokens(' 权限\t缓存\u3000权限 '), ['权限', '缓存', '权限'])
        self.rejected(lambda: validate_tokens(['two words']))
        self.rejected(lambda: tokens('x'*129))
        self.rejected(lambda: f64_hex(True))
        self.rejected(lambda: from_hex('7fefffffffffffff', True))
        self.assertEqual(from_hex(f64_hex(1.5)), 1.5)

    def test_full_bm25_statistics_empty_domains_and_strict_configuration(self):
        rows = [{'record_id': 'r1', 'record_version': 'v1', 'tokens': ['a', 'a']},
                {'record_id': 'r2', 'record_version': 'v1', 'tokens': []}]
        values, stats = fixed_bm25.materialize(rows)
        fixed_bm25.validate_materialized(values, stats, rows)
        self.rejected(lambda: fixed_bm25.validate_materialized([], stats, rows))
        self.assertEqual(stats, {'document_count': 2, 'total_tokens': 2, 'document_frequencies': [['a', 1]]})
        self.assertEqual(list(fixed_bm25.score([], {'document_count': 0, 'total_tokens': 0,
                                             'document_frequencies': []}, 'a', lambda: None)), [])
        self.rejected(lambda: fixed_bm25.configuration(0))
        self.rejected(lambda: fixed_bm25.validate_configuration({}))
        config = fixed_bm25.configuration(6); config['dimension'] = True
        self.rejected(lambda: fixed_bm25.validate_configuration(config))
        self.rejected(lambda: fixed_bm25.materialize([{'record_id': 'x', 'record_version': 'v',
                                                      'tokens': [str(i) for i in range(4097)]}]))

    def test_vector_values_null_mask_and_finite_distance(self):
        rows = [{'record_id': 'r1', 'record_version': 'v1', 'vector_state': 'present',
                 'vector_f64_hex': [f64_hex(1), f64_hex(0), f64_hex(0)]},
                {'record_id': 'r2', 'record_version': 'v1', 'vector_state': 'null', 'vector_f64_hex': []}]
        values, stats = fixed_vectors.materialize(rows)
        fixed_vectors.validate_materialized(values, stats, rows)
        self.assertEqual(stats['null_count'], 1)
        self.assertEqual(list(fixed_vectors.score(values, [f64_hex(0)]*3, lambda: None)), [('r1', 1.0)])
        self.rejected(lambda: fixed_vectors.validate_materialized([], stats, rows))
        self.rejected(lambda: fixed_vectors.validate_configuration({}))
        self.rejected(lambda: list(fixed_vectors.score(values, [], lambda: None)))
        config = fixed_vectors.configuration(); config['dimension'] = True
        self.rejected(lambda: fixed_vectors.validate_configuration(config))
