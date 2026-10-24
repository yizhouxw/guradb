"""Independent Parquet/semantic truth and source accounting, with mocked I/O.

These unit tests cannot certify the real P03 transport or component deadlines.
"""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_source_reader import FixedSourceReader
from tests.source_support.fixed_fixture import FIELDS, envelope, facts, make_fixture, unit_objects


def expected_rows(rows):
    return [{'record_id': row['record_id'], 'record_version': row['record_version'],
             'cells': [{'type': 'null', 'value': None} if row[field['name']] is None else
                       {'type': field['type'], 'value': str(row[field['name']]) if field['type'] == 'int8'
                        else row[field['name']]} for field in FIELDS]}
            for row in sorted(rows, key=lambda row: row['record_id'])]


class FixedSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = temporary.name

    def reader(self, fixture=None, **scope_arguments):
        fixture = fixture or make_fixture(self.root)
        objects, fetched, attempts = unit_objects(fixture, **scope_arguments)
        patcher = patch('modules.storage.fixed_objects.fetch', side_effect=fetched)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fixture, objects, FixedSourceReader(objects), attempts

    def assert_code(self, code, operation):
        with self.assertRaises(ContractFailure) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def test_all11_facts_int8_null_schema_and_true_physical_locations(self):
        fixture, objects, reader, attempts = self.reader()
        batch = reader.port.read_batch(fixture['binding'], 0)
        value = batch.value
        self.assertEqual(value['rows'], expected_rows(facts()))
        self.assertEqual(value['fields'], FIELDS)
        self.assertEqual(len(value['rows']), 11)
        self.assertTrue(value['last'])
        self.assertFalse(value['truncated'])
        self.assertEqual(len(attempts), 2)
        incoming = sum(len(raw) for raw in fixture['objects'].values())
        self.assertEqual(value['usage']['object_requests'], 2)
        self.assertEqual(value['usage']['object_bytes'], incoming)
        self.assertEqual(value['usage']['output_bytes'], incoming + len(batch.encoded))
        self.assertEqual(objects.scope.output_bytes, value['usage']['output_bytes'])
        for identifier, entries in fixture['locations'].items():
            self.assertEqual(len(entries), 1)
            actual, expected = reader._state['locations'][identifier], entries[0]
            self.assertEqual({key: actual[key] for key in ('object', 'row_group', 'row_offset')},
                             {key: expected[key] for key in ('object', 'row_group', 'row_offset')})
        before = objects.scope.memory_current
        repeated = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(repeated.value['rows'], value['rows'])
        self.assertEqual(repeated.value['usage']['object_requests'], 0)
        self.assertEqual(repeated.value['usage']['object_bytes'], 0)
        self.assertEqual(repeated.value['usage']['output_bytes'], len(repeated.encoded))
        self.assertGreaterEqual(repeated.value['usage']['memory_bytes'], before)
        self.assertEqual(len(attempts), 2)

    def test_multiple_files_three_pages_replay_and_complete_set(self):
        base = facts()
        rows = [{**deepcopy(base[index % 11]), 'record_id': f'r-{index:04d}'} for index in range(130)]
        fixture = make_fixture(self.root, rows=rows, split=[rows[:65], rows[65:]],
                               writer_options={'row_group_size': 16})
        fixture, objects, reader, attempts = self.reader(fixture)
        batches = [reader.port.read_batch(fixture['binding'], ordinal) for ordinal in range(3)]
        self.assertEqual([len(batch.value['rows']) for batch in batches], [64, 64, 2])
        self.assertEqual([batch.value['last'] for batch in batches], [False, False, True])
        self.assertEqual([row for batch in batches for row in batch.value['rows']], expected_rows(rows))
        self.assertEqual(sum(batch.value['usage']['object_requests'] for batch in batches), 3)
        self.assertEqual(sum(batch.value['usage']['output_bytes'] for batch in batches), objects.scope.output_bytes)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(reader.port.read_batch(fixture['binding'], 1).value['rows'], batches[1].value['rows'])
        self.assert_code('invalid_contract', lambda: reader.port.read_batch(fixture['binding'], 3))

    def test_empty_source_has_complete_schema_and_one_terminal_page(self):
        fixture, objects, reader, attempts = self.reader(make_fixture(self.root, rows=[]))
        result = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(result.value['rows'], [])
        self.assertEqual(result.value['fields'], FIELDS)
        self.assertTrue(result.value['last'])
        self.assertEqual(len(attempts), 1)
        self.assertGreater(result.value['usage']['memory_bytes'], 0)

    def test_typed_key_and_derived_revision_preserve_declared_meaning(self):
        fixture = make_fixture(self.root)
        value = fixture['binding'].value
        maps = value['revision']['sources'][0]['field_mapping']
        maps[0]['transform'] = 'key_v1'
        maps[1].update(transform='revision_version', source_field_id=0, source_type='none')
        fixture['binding'] = envelope(value)
        fixture, _, reader, _ = self.reader(fixture)
        actual = reader.port.read_batch(fixture['binding'], 0).value['rows']
        expected = []
        for row in expected_rows(facts()):
            raw = row['record_id'].encode('utf-8')
            identifier = (b'\x01' + struct.pack('>I', 1) + b'\x01' + struct.pack('>I', len(raw)) + raw).hex()
            row.update(record_id=identifier, record_version='p04-revision-v2')
            row['cells'][0]['value'], row['cells'][1]['value'] = identifier, 'p04-revision-v2'
            expected.append(row)
        self.assertEqual(actual, sorted(expected, key=lambda row: row['record_id']))

    def test_unsupported_parquet_encodings_are_explicit_rejections(self):
        for number, options in enumerate(({'compression': 'SNAPPY'}, {'use_dictionary': True},
                                           {'data_page_version': '2.0'})):
            with self.subTest(options=options):
                fixture = make_fixture(self.root + f'/{number}', writer_options=options)
                fixture, _, reader, _ = self.reader(fixture)
                self.assert_code('unsupported_capability', lambda: reader.port.read_batch(fixture['binding'], 0))

    def test_later_duplicate_identity_never_returns_a_successful_page(self):
        rows = facts()
        fixture = make_fixture(self.root, rows=rows + [deepcopy(rows[0])],
                               split=[rows, [deepcopy(rows[0])]])
        fixture, _, reader, _ = self.reader(fixture)
        self.assert_code('corrupt_object', lambda: reader.port.read_batch(fixture['binding'], 0))
        self.assert_code('expired_context', lambda: reader.port.read_batch(fixture['binding'], 0))

    def test_memory_is_reserved_before_first_fetch_and_current_revoke_prevents_io(self):
        fixture = make_fixture(self.root)
        value = fixture['binding'].value
        value['context']['budget']['memory_bytes'] = 1
        fixture['binding'] = envelope(value)
        fixture, _, reader, attempts = self.reader(fixture)
        self.assert_code('resource_limit', lambda: reader.port.read_batch(fixture['binding'], 0))
        self.assertEqual(attempts, [])
        fixture2, objects, reader2, attempts2 = self.reader(make_fixture(self.root + '/revoked'))
        objects.reauthorize = lambda _: 2
        self.assert_code('revoked', lambda: reader2.port.read_batch(fixture2['binding'], 0))
        self.assertEqual(attempts2, [])

    def test_elapsed_observation_includes_first_validation_and_exposes_final_tail(self):
        fixture = make_fixture(self.root)
        clock = [0.0]
        bound_at = fixture['binding'].value['context']['bound_at_unix_ms']
        fixture, _, reader, _ = self.reader(fixture, monotonic=lambda: clock[0], wall_ms=lambda: bound_at)
        original, calls = reader._encode, []
        def observed(*arguments):
            result = original(*arguments)
            calls.append(True)
            clock[0] += .020 if len(calls) == 1 else .003
            return result
        with patch.object(reader, '_encode', side_effect=observed):
            result = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.value['usage']['elapsed_ms'], 20)
        self.assertAlmostEqual(reader.last_observation['observed_finalization_ms'], 3)
        self.assertAlmostEqual(reader.last_observation['observed_page_elapsed_ms'], 23)
        self.assertLess(result.value['usage']['elapsed_ms'], reader.last_observation['observed_page_elapsed_ms'])

    def test_final_authorization_failure_clears_decoded_cache_without_refund(self):
        fixture, objects, reader, _ = self.reader()
        original, calls = reader._encode, []
        def late_revoke(*arguments):
            result = original(*arguments)
            calls.append(True)
            if len(calls) == 2:
                objects.reauthorize = lambda _: 2
            return result
        with patch.object(reader, '_encode', side_effect=late_revoke):
            self.assert_code('revoked', lambda: reader.port.read_batch(fixture['binding'], 0))
        self.assertIsNone(reader._state)
        self.assertTrue(reader._failed)
        self.assertGreater(objects.scope.object_bytes, 0)
        self.assertGreater(objects.scope.memory_current, 0)
        self.assertEqual(objects.scope.output_bytes, sum(len(raw) for raw in fixture['objects'].values()))
        self.assert_code('expired_context', lambda: reader.port.read_batch(fixture['binding'], 0))

    def test_deadline_at_next_batch_admission_also_clears_prior_cache(self):
        fixture, objects, reader, _ = self.reader()
        reader.port.read_batch(fixture['binding'], 0)
        self.assertIsNotNone(reader._state)
        objects.scope._cohort_deadline = 0  # Explicit unit clock/deadline injection.
        self.assert_code('deadline', lambda: reader.port.read_batch(fixture['binding'], 0))
        self.assertIsNone(reader._state)

    def test_concurrent_nonowner_cannot_clear_or_poison_inflight_reader(self):
        fixture = make_fixture(self.root)
        bound_at = fixture['binding'].value['context']['bound_at_unix_ms']
        fixture, _, reader, _ = self.reader(fixture, monotonic=lambda: 0.0, wall_ms=lambda: bound_at)
        ready, resume = threading.Event(), threading.Event()
        original = reader._encode
        def pause_owner(*arguments):
            ready.set()
            self.assertTrue(resume.wait(10), 'unit owner release was not signalled')
            return original(*arguments)
        with patch.object(reader, '_encode', side_effect=pause_owner), ThreadPoolExecutor(max_workers=1) as pool:
            owner = pool.submit(reader.port.read_batch, fixture['binding'], 0)
            try:
                self.assertTrue(ready.wait(10), 'unit owner never reached output construction')
                self.assert_code('resource_limit', lambda: reader.port.read_batch(fixture['binding'], 0))
                self.assertIsNotNone(reader._state)
                self.assertFalse(reader._failed)
            finally:
                resume.set()
            result = owner.result(timeout=10)
        self.assertEqual(result.value['rows'], expected_rows(facts()))
        self.assertIsNotNone(reader._state)
        self.assertFalse(reader._failed)

    def test_cancel_before_final_delivery_does_not_charge_a_successful_envelope(self):
        cancelled = [False]
        fixture, objects, reader, _ = self.reader(cancelled=lambda: cancelled[0])
        original, calls = reader._encode, []
        def late_cancel(*arguments):
            result = original(*arguments)
            calls.append(True)
            if len(calls) == 2:
                cancelled[0] = True
            return result
        with patch.object(reader, '_encode', side_effect=late_cancel):
            self.assert_code('cancelled', lambda: reader.port.read_batch(fixture['binding'], 0))
        self.assertIsNone(reader._state)
        self.assertEqual(objects.scope.output_bytes, sum(len(raw) for raw in fixture['objects'].values()))

    def test_delivery_commit_is_not_followed_by_another_policy_rejection(self):
        fixture, objects, reader, _ = self.reader()
        incoming = sum(len(raw) for raw in fixture['objects'].values())
        objects.scope.cancelled = lambda: objects.scope.output_bytes > incoming
        result = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(result.value['rows'], expected_rows(facts()))
        self.assertEqual(objects.scope.output_bytes, incoming + len(result.encoded))
        self.assert_code('cancelled', lambda: reader.port.read_batch(fixture['binding'], 0))
        self.assertIsNone(reader._state)
