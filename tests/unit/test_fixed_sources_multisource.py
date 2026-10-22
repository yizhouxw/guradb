"""Real independent Parquet truth with mocked transport; not network/latency evidence."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors import fixed_source_reader as module
from modules.connectors.fixed_source_reader import FixedSourceReader
from tests.source_support.fixed_fixture import (encoded, envelope, facts, make_multisource_fixture,
    reseal_multisource, sha, unit_objects)
from tests.unit.test_fixed_sources_reader import expected_rows


class FixedMultisourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def reader(self, fixture, **clocks):
        objects, fetched, attempts = unit_objects(fixture, **clocks)
        patcher = patch('modules.storage.fixed_objects.fetch', side_effect=fetched)
        patcher.start()
        self.addCleanup(patcher.stop)
        return objects, FixedSourceReader(objects), attempts

    def rejected(self, code, fixture, reader):
        with self.assertRaises(ContractFailure) as caught:
            reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(caught.exception.code, code)
        self.assertIsNone(reader._state)
        self.assertTrue(reader._failed)
        before = reader.scope.usage()
        with self.assertRaises(ContractFailure) as repeat:
            reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(repeat.exception.code, 'expired_context')
        self.assertEqual(reader.scope.object_requests, before['object_requests'])
        self.assertEqual(reader.scope.output_bytes, before['output_bytes'])

    def test_two_real_manifests_full11_origins_fields_and_single_ledger(self):
        fixture = make_multisource_fixture(self.root)
        self.assertEqual([len(m['files']) for m in fixture['source_metadata']], [1, 1])
        self.assertEqual([m['source_schema'][0]['source_field_id'] for m in fixture['source_metadata']], [101, 201])
        wall = [fixture['binding'].value['context']['bound_at_unix_ms']]
        objects, reader, attempts = self.reader(fixture, wall_ms=lambda: wall[0], monotonic=lambda: 0.0)
        started, deadline = objects.scope.started, objects.scope.deadline
        result = reader.port.read_batch(fixture['binding'], 0)
        self.assertIs(reader.scope, objects.scope)
        self.assertIs(reader._binding, objects.scope.binding)
        self.assertEqual(result.value['rows'], expected_rows(facts()))
        self.assertEqual(len(result.value['rows']), 11)
        self.assertTrue(result.value['last'])
        self.assertFalse(result.value['truncated'])
        self.assertEqual(result.value['context_sha256'], fixture['binding'].sha256)
        self.assertEqual([entry['key'] for entry in attempts[:2]],
                         ['source-main/metadata.json', 'source-mirror/metadata.json'])
        self.assertEqual(len(attempts), 4)
        self.assertEqual(result.value['usage']['object_requests'], 4)
        self.assertEqual(result.value['usage']['output_bytes'], objects.scope.output_bytes)
        self.assertEqual(objects.scope.output_bytes, objects.scope.object_bytes + len(result.encoded))
        origins = fixture['source_origins']
        self.assertEqual(sum(row['source_id'] == 'source-main' for row in origins.values()), 10)
        self.assertEqual(sum(row['source_id'] == 'source-mirror' for row in origins.values()), 1)
        for identifier, expected in fixture['locations'].items():
            self.assertEqual(len(expected), 1)
            actual = reader._state['locations'][identifier]
            self.assertEqual(actual, {key: expected[0][key] for key in
                ('source_version_id', 'object', 'row_group', 'row_offset')})
            self.assertEqual(actual['source_version_id'], origins[identifier]['source_version_id'])
        repeated = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(repeated.value['rows'], result.value['rows'])
        self.assertEqual(repeated.value['usage']['object_requests'], 0)
        self.assertEqual(repeated.value['usage']['output_bytes'], len(repeated.encoded))
        self.assertEqual((objects.scope.started, objects.scope.deadline), (started, deadline))
        charged = objects.scope.output_bytes
        wall[0] += 1
        tightened = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(tightened.value['rows'], result.value['rows'])
        self.assertEqual((objects.scope.started, objects.scope.deadline), (started, deadline - .001))
        self.assertIs(reader.scope, objects.scope)
        self.assertEqual(tightened.value['usage']['object_requests'], 0)
        self.assertEqual(tightened.value['usage']['output_bytes'], len(tightened.encoded))
        self.assertEqual(objects.scope.output_bytes, charged + len(tightened.encoded))
        self.assertEqual((objects.scope.object_requests, len(attempts)), (4, 4))

    def test_source_declaration_order_does_not_drop_or_relabel_mirror(self):
        fixture = make_multisource_fixture(self.root)
        value = fixture['binding'].value
        value['revision']['sources'].reverse()
        value['context']['source_version_ids'].reverse()
        fixture['binding'] = envelope(value)
        _, reader, _ = self.reader(fixture)
        result = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(result.value['rows'], expected_rows(facts()))
        self.assertEqual(reader._state['locations']['r-a1-copy']['source_version_id'], 'p04-mirror-v2')

    def test_empty_sources_keep_schema_and_one_global_terminal_page(self):
        fixture = make_multisource_fixture(self.root, source_rows=[
            ('source-main', 'p04-main-v2', []), ('source-mirror', 'p04-mirror-v2', [])])
        _, reader, attempts = self.reader(fixture)
        result = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(result.value['rows'], [])
        self.assertEqual(result.value['fields'], fixture['binding'].value['resource']['fields'])
        self.assertTrue(result.value['last'])
        self.assertFalse(result.value['truncated'])
        self.assertEqual(len(attempts), 2)

    def test_empty_main_does_not_skip_the_nonempty_mirror(self):
        row = next(row for row in facts() if row['source_id'] == 'source-mirror')
        fixture = make_multisource_fixture(self.root, source_rows=[
            ('source-main', 'p04-main-v2', []), ('source-mirror', 'p04-mirror-v2', [row])])
        _, reader, attempts = self.reader(fixture)
        result = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(result.value['rows'], expected_rows([row]))
        self.assertEqual(reader._state['locations'][row['record_id']]['source_version_id'], 'p04-mirror-v2')
        self.assertTrue(result.value['last'])
        self.assertEqual(len(attempts), 3)

    def test_global_130_rows_have_one_page_order_and_no_binding_changes(self):
        base = facts()
        rows = [{**deepcopy(base[i % 11]), 'record_id': f'm-{i:04d}'} for i in range(130)]
        fixture = make_multisource_fixture(self.root, source_rows=[
            ('source-main', 'p04-main-v2', rows[1::2]),
            ('source-mirror', 'p04-mirror-v2', rows[::2])], writer_options={'row_group_size': 16})
        objects, reader, attempts = self.reader(fixture)
        results = [reader.port.read_batch(fixture['binding'], i) for i in range(3)]
        self.assertEqual([len(batch.value['rows']) for batch in results], [64, 64, 2])
        self.assertEqual([batch.value['last'] for batch in results], [False, False, True])
        self.assertEqual([row for batch in results for row in batch.value['rows']], expected_rows(rows))
        self.assertEqual({batch.value['context_sha256'] for batch in results}, {fixture['binding'].sha256})
        self.assertEqual(sum(batch.value['usage']['object_requests'] for batch in results), 4)
        self.assertEqual(sum(batch.value['usage']['output_bytes'] for batch in results), objects.scope.output_bytes)
        self.assertEqual(len(attempts), 4)

    def test_second_metadata_mismatch_fails_before_any_data(self):
        fixture = make_multisource_fixture(self.root)
        reseal_multisource(fixture, 1, metadata_change=lambda m: m.update(snapshot_id='wrong-fixed-snapshot'))
        objects, reader, attempts = self.reader(fixture)
        self.rejected('corrupt_object', fixture, reader)
        self.assertEqual(len(attempts), 2)
        self.assertGreater(objects.scope.output_bytes, 0)

    def test_second_data_damage_never_returns_a_first_source_page(self):
        fixture = make_multisource_fixture(self.root)
        reseal_multisource(fixture, 1, data_change=lambda raw, _: b'FAIL' + raw[4:])
        objects, reader, attempts = self.reader(fixture)
        self.rejected('corrupt_object', fixture, reader)
        self.assertEqual(len(attempts), 4)
        self.assertGreater(objects.scope.object_bytes, 0)

    def test_missing_second_metadata_keeps_the_actual_failed_attempt_and_first_prefix(self):
        fixture = make_multisource_fixture(self.root)
        objects, fetched, attempts = unit_objects(fixture)
        reader = FixedSourceReader(objects)
        missing = fixture['binding'].value['revision']['sources'][1]['metadata']
        def fetch(scope, backend, ref, offset, length):
            if ref == missing:
                scope.request(length)
                raise ContractFailure('missing_object', 'unit fixed object is missing')
            return fetched(scope, backend, ref, offset, length)
        with patch('modules.storage.fixed_objects.fetch', side_effect=fetch):
            self.rejected('missing_object', fixture, reader)
        self.assertEqual(objects.scope.object_requests, 2)
        self.assertEqual(len(attempts), 1)
        self.assertGreater(objects.scope.object_bytes, 0)
        self.assertEqual(objects.scope.output_bytes, objects.scope.object_bytes)

    def test_duplicate_identity_across_sources_is_rejected_not_deduplicated(self):
        row = facts()[0]
        fixture = make_multisource_fixture(self.root, source_rows=[
            ('source-main', 'p04-main-v2', [row]),
            ('source-mirror', 'p04-mirror-v2', [{**deepcopy(row), 'record_version': 'other-version'}])])
        _, reader, attempts = self.reader(fixture)
        self.rejected('corrupt_object', fixture, reader)
        self.assertEqual(len(attempts), 4)

    def test_second_mapping_and_complete_schema_digest_are_independently_verified(self):
        for case in ('mapping', 'schema'):
            with self.subTest(case=case):
                fixture = make_multisource_fixture(self.root/case)
                if case == 'mapping':
                    value = fixture['binding'].value
                    value['revision']['sources'][1]['field_mapping'][0]['source_field_id'] = 999
                    fixture['binding'] = envelope(value)
                else:
                    reseal_multisource(fixture, 1,
                        metadata_change=lambda m: m['source_schema'][0].update(name='wrong-complete-name'))
                _, reader, attempts = self.reader(fixture)
                self.rejected('corrupt_object', fixture, reader)
                self.assertEqual(len(attempts), 2)

    def test_more_than_two_sources_are_rejected_before_io(self):
        rows = facts()
        fixture = make_multisource_fixture(self.root, source_rows=[
            (f'source-{i}', f'fixed-version-{i}', [rows[i]]) for i in range(3)])
        _, reader, attempts = self.reader(fixture)
        self.rejected('unsupported_capability', fixture, reader)
        self.assertEqual(attempts, [])

    def test_metadata_byte_bound_is_joint_and_checked_before_fetch(self):
        fixture = make_multisource_fixture(self.root)
        value = fixture['binding'].value
        for source in value['revision']['sources']:
            old = source['metadata']
            source['metadata'] = {**old, 'size_bytes': 40000}
            value['revision']['objects'] = [source['metadata'] if ref == old else ref
                                            for ref in value['revision']['objects']]
        fixture['binding'] = envelope(value)
        _, reader, attempts = self.reader(fixture)
        self.rejected('resource_limit', fixture, reader)
        self.assertEqual(attempts, [])

    def test_row_and_group_limits_apply_to_the_union_before_data(self):
        base = facts()
        for name, counts, group_size in [('rows', (501, 500), 128), ('groups', (65, 65), 8)]:
            with self.subTest(name=name):
                all_rows = [{**deepcopy(base[i % 11]), 'record_id': f'u-{i:04d}'}
                            for i in range(sum(counts))]
                fixture = make_multisource_fixture(self.root/name, source_rows=[
                    ('source-main', 'p04-main-v2', all_rows[:counts[0]]),
                    ('source-mirror', 'p04-mirror-v2', all_rows[counts[0]:])],
                    writer_options={'row_group_size': group_size})
                _, reader, attempts = self.reader(fixture)
                self.rejected('resource_limit', fixture, reader)
                self.assertEqual(len(attempts), 2)

    def test_five_actual_files_are_rejected_before_data_even_if_each_source_has_at_most_four(self):
        base = facts()
        rows = [{**deepcopy(base[i % 11]), 'record_id': f'f-{i:04d}'} for i in range(12)]
        fixture = make_multisource_fixture(self.root, source_rows=[
            ('source-main', 'p04-main-v2', rows[:6]), ('source-mirror', 'p04-mirror-v2', rows[6:])],
            source_splits=[[rows[:2], rows[2:4], rows[4:6]], [rows[6:9], rows[9:]]])
        self.assertEqual([len(metadata['files']) for metadata in fixture['source_metadata']], [3, 2])
        _, reader, attempts = self.reader(fixture)
        self.rejected('resource_limit', fixture, reader)
        self.assertEqual(len(attempts), 2)

    def test_resource_width_thirty_three_is_rejected_before_fetch(self):
        fixture = make_multisource_fixture(self.root)
        value = fixture['binding'].value
        for identifier in range(7, 34):
            value['resource']['fields'].append({'field_id': identifier, 'name': f'extra_{identifier}',
                'type': 'text', 'nullable': True, 'role': 'value'})
            for source in value['revision']['sources']:
                first = source['field_mapping'][0]
                source['field_mapping'].append({**first, 'resource_field_id': identifier})
        digest = sha(encoded(value['resource']['fields']))
        value['resource']['schema_sha256'] = digest
        for source in value['revision']['sources']:
            source['resource_schema_sha256'] = digest
        fixture['binding'] = envelope(value)
        _, reader, attempts = self.reader(fixture)
        self.rejected('resource_limit', fixture, reader)
        self.assertEqual(attempts, [])

    def test_joint_field_limit_is_not_thirty_two_per_source(self):
        fixture = make_multisource_fixture(self.root)
        for i in range(2):
            def extend(metadata, index=i):
                metadata['source_schema'] += [
                    {'source_field_id': 1000 + 100 * index + j, 'name': f'unmapped_{j}',
                     'type': 'text', 'nullable': True} for j in range(11)]
            reseal_multisource(fixture, i, metadata_change=extend)
        value = fixture['binding'].value
        for source, metadata in zip(value['revision']['sources'], fixture['source_metadata']):
            source['source_schema_sha256'] = sha(encoded(metadata['source_schema']))
        fixture['binding'] = envelope(value)
        _, reader, attempts = self.reader(fixture)
        self.rejected('resource_limit', fixture, reader)
        self.assertEqual(len(attempts), 2)

    def test_joint_live_reservation_is_not_eight_mebibytes_per_source(self):
        base = facts()
        rows = [{**deepcopy(base[i % 11]), 'record_id': f'large-{i:04d}', 'title': '界' * 4096}
                for i in range(160)]
        fixture = make_multisource_fixture(self.root, source_rows=[
            ('source-main', 'p04-main-v2', rows[:80]),
            ('source-mirror', 'p04-mirror-v2', rows[80:])], writer_options={'row_group_size': 128})
        refs = [entry['object'] for metadata in fixture['source_metadata'] for entry in metadata['files']]
        self.assertTrue(all(ref['size_bytes'] <= 1 << 20 for ref in refs))
        self.assertLessEqual(sum(ref['size_bytes'] for ref in refs), 4 << 20)
        objects, reader, attempts = self.reader(fixture)
        self.rejected('resource_limit', fixture, reader)
        self.assertEqual(len(attempts), 2, 'the joint workset must be reserved before either data fetch')
        self.assertLessEqual(objects.scope.memory_peak, 8 << 20)

    def test_extra_or_cross_shared_objects_do_not_relax_the_exact_union(self):
        for name in ('extra', 'cross'):
            with self.subTest(name=name):
                fixture = make_multisource_fixture(self.root/name)
                if name == 'extra':
                    value = fixture['binding'].value
                    value['revision']['objects'].append({**value['revision']['objects'][1], 'key': 'foreign-extra'})
                    fixture['binding'] = envelope(value)
                    code = 'unsupported_capability'
                else:
                    ref = fixture['source_metadata'][0]['files'][0]['object']
                    reseal_multisource(fixture, 1,
                        metadata_change=lambda m: m['files'][0].update(object=deepcopy(ref)))
                    # DataRevision contains each immutable ref once; cross-source
                    # membership must still be rejected before either data read.
                    code = 'invalid_contract'
                _, reader, attempts = self.reader(fixture)
                self.rejected(code, fixture, reader)
                self.assertEqual(len(attempts), 2)

    def test_request_budget_stops_after_both_metadata_without_reset(self):
        fixture = make_multisource_fixture(self.root)
        value = fixture['binding'].value
        value['context']['budget']['object_requests'] = 2
        fixture['binding'] = envelope(value)
        objects, reader, attempts = self.reader(fixture)
        self.rejected('resource_limit', fixture, reader)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(objects.scope.object_requests, 2)
        self.assertGreater(objects.scope.output_bytes, 0)

    def test_revoke_cancel_and_page_deadline_after_first_source_keep_one_parent(self):
        for name, code in [('revoke', 'revoked'), ('cancel', 'cancelled'), ('deadline', 'deadline')]:
            with self.subTest(name=name):
                fixture = make_multisource_fixture(self.root/name)
                bound_at = fixture['binding'].value['context']['bound_at_unix_ms']
                now, cancelled = [0.0], [False]
                objects, reader, attempts = self.reader(fixture,
                    wall_ms=lambda: bound_at, monotonic=lambda: now[0], cancelled=lambda: cancelled[0])
                original, calls = module.record, []
                deadline = objects.scope.deadline
                def late(values, source, fields, revision):
                    row = original(values, source, fields, revision)
                    calls.append(source['source_id'])
                    if len(calls) == 10:
                        if name == 'revoke':
                            objects.reauthorize = lambda _: 2
                        elif name == 'cancel':
                            cancelled[0] = True
                        else:
                            now[0] = 1.01
                    return row
                with patch.object(module, 'record', side_effect=late):
                    self.rejected(code, fixture, reader)
                self.assertEqual(calls, ['source-main'] * 10)
                self.assertEqual(len(attempts), 3)
                self.assertEqual(objects.scope.deadline, deadline)
                self.assertGreater(objects.scope.object_requests, 0)
                self.assertGreater(objects.scope.object_bytes, 0)

    def test_derived_revision_strategy_remains_global_across_all_sources(self):
        fixture = make_multisource_fixture(self.root)
        value = fixture['binding'].value
        for source in value['revision']['sources']:
            source['field_mapping'][1].update(transform='revision_version', source_field_id=0, source_type='none')
        fixture['binding'] = envelope(value)
        _, reader, _ = self.reader(fixture)
        rows = reader.port.read_batch(fixture['binding'], 0).value['rows']
        revision = value['revision']['data_revision_id']
        self.assertEqual({row['record_version'] for row in rows}, {revision})
        self.assertTrue(all(row['cells'][1]['value'] == revision for row in rows))
        value['revision']['sources'][1]['field_mapping'][1].update(
            transform='identity', source_field_id=202, source_type='text')
        with self.assertRaises(ContractFailure):
            envelope(value)


if __name__ == '__main__':
    unittest.main()
