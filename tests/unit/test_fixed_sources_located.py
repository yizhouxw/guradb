"""Private located data/accounting tests; mock I/O is not network evidence."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure, canonical, digest
from modules.common.cf1a_read import without
from modules.common.cf1a_wire import Contract
from modules.connectors import fixed_source_located as located_module
from modules.connectors import fixed_source_reader as reader_module
from modules.connectors.fixed_source_located import LocatedBatch, encode_located, validate_located_for
from modules.connectors.fixed_source_reader import FixedSourceReader
from tests.source_support.fixed_fixture import (encoded, envelope, facts, make_multisource_fixture,
    reseal_multisource, unit_objects)
from tests.source_support.fixed_located_acceptance import consume_located
from tests.unit.test_fixed_sources_reader import expected_rows


class LocatedSourceTests(unittest.TestCase):
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

    def fail(self, code, callback):
        with self.assertRaises(ContractFailure) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def poisoned(self, fixture, reader):
        self.assertTrue(reader._failed)
        self.assertIsNone(reader._state)
        before = reader.scope.usage()
        self.fail('expired_context', lambda: reader.read_located_batch(fixture['binding'], 0))
        self.assertEqual(reader.scope.usage()['output_bytes'], before['output_bytes'])

    @staticmethod
    def bounds(fixture):
        return {(item['source_version_id'], canonical(entry['object'])): entry['row_group_rows']
                for item in fixture['source_metadata'] for entry in item['files']}

    def test_full11_joint_parent_delta_one_final_delivery_and_actual_pyarrow_consumer(self):
        fixture = make_multisource_fixture(self.root)
        objects, reader, attempts = self.reader(fixture)
        with patch.object(objects.scope, 'delivered', wraps=objects.scope.delivered) as delivery:
            result = reader.read_located_batch(fixture['binding'], 0)
        p, witnesses = consume_located(fixture['binding'], result, fixture)
        self.assertEqual(result.batch.value['rows'], expected_rows(facts()))
        self.assertEqual([entry['record_id'] for entry in witnesses], sorted(row['record_id'] for row in facts()))
        self.assertEqual(sum(row['source_id'] == 'source-mirror' for row in witnesses), 1)
        self.assertEqual(p['batch_sha256'], result.batch.sha256)
        prefix = sum(len(raw) for raw in fixture['objects'].values())
        self.assertEqual(result.batch.value['usage']['output_bytes'], prefix + result.wire_bytes)
        self.assertEqual(objects.scope.output_bytes, prefix + result.wire_bytes)
        self.assertEqual([call.args[0] for call in delivery.call_args_list],
                         [entry['bytes'] for entry in attempts] + [result.wire_bytes])
        with self.assertRaises(FrozenInstanceError):
            result.provenance_encoded = b'changed'
        self.fail('invalid_contract', lambda: LocatedBatch(result.batch, bytearray(result.provenance_encoded)))

    def test_interleaved_dual130_keeps_global_original_pages_and_exact_locations(self):
        base = facts()
        rows = [{**deepcopy(base[i % 11]), 'record_id': f'l-{i:04d}'} for i in range(130)]
        fixture = make_multisource_fixture(self.root, source_rows=[
            ('source-main', 'p04-main-v2', rows[1::2]), ('source-mirror', 'p04-mirror-v2', rows[::2])],
            writer_options={'row_group_size': 16})
        objects, reader, attempts = self.reader(fixture)
        outputs = [reader.read_located_batch(fixture['binding'], ordinal) for ordinal in range(3)]
        self.assertEqual([len(result.batch.value['rows']) for result in outputs], [64, 64, 2])
        self.assertEqual([result.batch.value['last'] for result in outputs], [False, False, True])
        self.assertEqual([row for result in outputs for row in result.batch.value['rows']], expected_rows(rows))
        for ordinal, result in enumerate(outputs):
            p, actual = consume_located(fixture['binding'], result, fixture)
            self.assertEqual(p['batch_ordinal'], ordinal)
            self.assertEqual({row['source_id'] for row in actual}, {'source-main', 'source-mirror'})
        self.assertEqual(sum(result.batch.value['usage']['output_bytes'] for result in outputs), objects.scope.output_bytes)
        self.assertEqual(len(attempts), 4)

    def test_replay_and_mixed_ordinary_A_keep_rows_locations_and_charge_current_wire(self):
        fixture = make_multisource_fixture(self.root)
        wall = [fixture['binding'].value['context']['bound_at_unix_ms']]
        objects, reader, attempts = self.reader(fixture, wall_ms=lambda: wall[0], monotonic=lambda: 0.0)
        first = reader.read_located_batch(fixture['binding'], 0)
        start, deadline, charged = objects.scope.started, objects.scope.deadline, objects.scope.output_bytes
        replay = reader.read_located_batch(fixture['binding'], 0)
        self.assertEqual(validate_located_for(fixture['binding'], first)['rows'],
                         validate_located_for(fixture['binding'], replay)['rows'])
        self.assertNotEqual(first.batch.sha256, replay.batch.sha256)
        self.assertEqual(replay.batch.value['usage']['output_bytes'], replay.wire_bytes)
        self.assertEqual(objects.scope.output_bytes, charged + replay.wire_bytes)
        wall[0] += 1
        ordinary = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(ordinary.value['rows'], first.batch.value['rows'])
        self.assertEqual(ordinary.value['usage']['output_bytes'], len(ordinary.encoded))
        self.assertEqual((objects.scope.started, objects.scope.deadline), (start, deadline-.001))
        self.assertEqual(len(attempts), 4)

    def test_exact_joint_cap_and_one_byte_less_preserve_the_whole_page(self):
        fixture = make_multisource_fixture(self.root)
        _, reader, _ = self.reader(fixture)
        result = reader.read_located_batch(fixture['binding'], 0)
        with patch.object(located_module, 'MAX_JOINT', result.wire_bytes):
            self.assertEqual(len(validate_located_for(fixture['binding'], result)['rows']), 11)
        with patch.object(located_module, 'MAX_JOINT', result.wire_bytes-1):
            self.fail('resource_limit', lambda: validate_located_for(fixture['binding'], result))
        self.assertLess(len(result.batch.encoded), result.wire_bytes)

    def test_A_fits_real_768KiB_but_A_plus_provenance_rejects_the_complete_page(self):
        fixture = make_multisource_fixture(self.root)
        _, reader, _ = self.reader(fixture)
        actual = reader.read_located_batch(fixture['binding'], 0)
        value = actual.batch.value
        template = next(row for row in value['rows'] if row['cells'][2]['value'] is not None)
        value['rows'], locations = [], {}
        locator = validate_located_for(fixture['binding'], actual)['rows'][0]['locator']
        for i in range(64):
            row = deepcopy(template)
            row['record_id'] = row['cells'][0]['value'] = f'wire-{i:03d}'
            row['cells'][2]['value'] = '界' * 3900
            value['rows'].append(row)
            locations[row['record_id']] = locator
        value['usage'] = dict(object_requests=0, object_bytes=0, memory_bytes=1, output_bytes=0, elapsed_ms=0)
        value['content_sha256'] = digest(without(value, 'content_sha256'))
        plain = Contract(canonical(reader_module.envelope(value)))
        self.assertLess(len(plain.encoded), 768 << 10)
        # Pure codec cap test only; repeated locators are not a physical row proof.
        scope = SimpleNamespace(check=lambda: None, output=lambda _: None)
        self.fail('resource_limit', lambda: encode_located(fixture['binding'], value, locations,
            self.bounds(fixture), scope, 2 << 20))

    def test_fixedpoint_crosses_decimal_width_without_recharging_the_prefix(self):
        fixture = make_multisource_fixture(self.root)
        _, reader, _ = self.reader(fixture)
        result = reader.read_located_batch(fixture['binding'], 0)
        body = result.batch.value
        prefix, checks = 99999, []
        body['usage']['output_bytes'] = prefix
        scope = SimpleNamespace(check=lambda: None, output=lambda length: checks.append(length))
        # Pure codec test, not a measured scope: actual decoder facts are independent fixture values.
        locations = {key: {name: positions[0][name] for name in
                     ('source_version_id', 'object', 'row_group', 'row_offset')}
                     for key, positions in fixture['locations'].items()}
        encoded_result = encode_located(fixture['binding'], body, locations, self.bounds(fixture),
                                        scope, 768 << 10)
        u = encoded_result.batch.value['usage']['output_bytes']
        self.assertEqual(u, prefix + encoded_result.wire_bytes)
        self.assertGreater(len(str(u)), len(str(prefix)))
        self.assertGreaterEqual(len(checks), 2)
        self.assertEqual(checks[-1], encoded_result.wire_bytes)
        for unsafe in ((1 << 53)-1, 1 << 53):
            too_large = deepcopy(body)
            too_large['usage']['output_bytes'] = unsafe
            self.fail('resource_limit', lambda: encode_located(fixture['binding'], too_large,
                locations, self.bounds(fixture), scope, 768 << 10))

    def test_sidecar_hash_identity_cells_shape_and_locator_mutations_are_rejected(self):
        fixture = make_multisource_fixture(self.root)
        _, reader, _ = self.reader(fixture)
        result = reader.read_located_batch(fixture['binding'], 0)
        original = validate_located_for(fixture['binding'], result)
        mutations = [lambda p: p.update(batch_sha256='0'*64),
            lambda p: p.update(context_sha256='0'*64), lambda p: p.update(extra=True),
            lambda p: p['rows'][0].update(cells_sha256='0'*64),
            lambda p: p['rows'][0].update(record_version='wrong-version'),
            lambda p: p['rows'].reverse(), lambda p: p['rows'].pop(),
            lambda p: p['rows'][0]['locator'].update(source_version_id='foreign-source'),
            lambda p: p['rows'][0]['locator']['object'].update(version='wrong-fixed-version'),
            lambda p: p['rows'][0]['locator'].update(row_group=99),
            lambda p: p['rows'][0]['locator'].update(row_offset=1000)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = deepcopy(original); mutate(value)
                bad = LocatedBatch(result.batch, encoded(value))
                self.fail('invalid_contract', lambda: validate_located_for(
                    fixture['binding'], bad, bounds=self.bounds(fixture)))
        for raw in (b' '+result.provenance_encoded, result.provenance_encoded[:-1],
                    result.provenance_encoded.replace(b'{', b'{"version":"p04-located/1",', 1)):
            self.fail('invalid_contract', lambda: validate_located_for(
                fixture['binding'], LocatedBatch(result.batch, raw)))

    def test_budget_only_sufficient_for_A_rejects_joint_without_partial_delivery(self):
        fixture = make_multisource_fixture(self.root)
        wall = fixture['binding'].value['context']['bound_at_unix_ms']
        clocks = dict(wall_ms=lambda: wall, monotonic=lambda: 0.0)
        _, plain_reader, _ = self.reader(fixture, **clocks)
        plain = plain_reader.port.read_batch(fixture['binding'], 0)
        prefix = sum(len(raw) for raw in fixture['objects'].values())
        value = fixture['binding'].value
        # A small digit-width allowance preserves A success after rebinding the
        # tighter budget. The sidecar is larger and must still be rejected.
        value['context']['budget']['output_bytes'] = prefix + len(plain.encoded) + 64
        fixture['binding'] = envelope(value)
        _, control, _ = self.reader(fixture, **clocks)
        self.assertLessEqual(control.port.read_batch(fixture['binding'], 0).value['usage']['output_bytes'],
                             value['context']['budget']['output_bytes'])
        objects, reader, attempts = self.reader(fixture, **clocks)
        self.fail('resource_limit', lambda: reader.read_located_batch(fixture['binding'], 0))
        self.assertEqual(len(attempts), 4)
        self.assertEqual(objects.scope.output_bytes, prefix)
        self.poisoned(fixture, reader)

    def test_joint_reservation_failure_preserves_prior_parent_costs(self):
        fixture = make_multisource_fixture(self.root)
        objects, reader, attempts = self.reader(fixture)
        reader.port.read_batch(fixture['binding'], 0)
        charged = objects.scope.output_bytes
        objects.scope.budget['memory_bytes'] = objects.scope.memory_current + 1
        self.fail('resource_limit', lambda: reader.read_located_batch(fixture['binding'], 0))
        self.assertEqual(objects.scope.output_bytes, charged)
        self.assertEqual(len(attempts), 4)
        self.poisoned(fixture, reader)

    def test_final_revoke_cancel_deadline_reject_before_joint_delivery(self):
        for name, code in [('revoke', 'revoked'), ('cancel', 'cancelled'), ('deadline', 'deadline')]:
            with self.subTest(name=name):
                fixture = make_multisource_fixture(self.root/name)
                now, cancelled = [0.0], [False]
                bound = fixture['binding'].value['context']['bound_at_unix_ms']
                objects, reader, _ = self.reader(fixture, wall_ms=lambda: bound,
                    monotonic=lambda: now[0], cancelled=lambda: cancelled[0])
                original, calls = reader_module.encode_located, []
                def final(*args):
                    result = original(*args); calls.append(result.wire_bytes)
                    if len(calls) == 2:
                        if name == 'revoke': objects.reauthorize = lambda _: 2
                        elif name == 'cancel': cancelled[0] = True
                        else: now[0] = 1.01
                    return result
                with patch.object(reader_module, 'encode_located', side_effect=final):
                    self.fail(code, lambda: reader.read_located_batch(fixture['binding'], 0))
                self.assertEqual(len(calls), 2)
                self.assertEqual(objects.scope.output_bytes, sum(len(raw) for raw in fixture['objects'].values()))
                self.poisoned(fixture, reader)

    def test_second_source_damage_and_cross_binding_never_return_a_located_pair(self):
        fixture = make_multisource_fixture(self.root)
        reseal_multisource(fixture, 1, data_change=lambda raw, _: b'FAIL'+raw[4:])
        objects, reader, attempts = self.reader(fixture)
        self.fail('corrupt_object', lambda: reader.read_located_batch(fixture['binding'], 0))
        self.assertEqual(len(attempts), 4)
        self.assertGreater(objects.scope.output_bytes, 0)
        self.poisoned(fixture, reader)
        other = make_multisource_fixture(self.root/'other')
        _, reader, attempts = self.reader(other)
        self.fail('invalid_contract', lambda: reader.read_located_batch(fixture['binding'], 0))
        self.assertEqual(attempts, [])
        self.poisoned(other, reader)

    def test_empty_sources_return_one_matching_empty_located_terminal_page(self):
        fixture = make_multisource_fixture(self.root, source_rows=[
            ('source-main', 'p04-main-v2', []), ('source-mirror', 'p04-mirror-v2', [])])
        _, reader, attempts = self.reader(fixture)
        result = reader.read_located_batch(fixture['binding'], 0)
        sidecar, actual = consume_located(fixture['binding'], result, fixture)
        self.assertEqual(result.batch.value['rows'], [])
        self.assertEqual(sidecar['rows'], [])
        self.assertEqual(actual, [])
        self.assertTrue(sidecar['last'])
        self.assertEqual(sidecar['batch_ordinal'], 0)
        self.assertEqual(len(attempts), 2)

    def test_bad_generated_provenance_clears_state_without_a_joint_delivery(self):
        for name in ('cells', 'locator'):
            with self.subTest(name=name):
                fixture = make_multisource_fixture(self.root/name)
                objects, reader, _ = self.reader(fixture)
                original = located_module._sidecar
                def damaged(*args):
                    value = deepcopy(original(*args))
                    if name == 'cells': value['rows'][0]['cells_sha256'] = '0'*64
                    else: value['rows'][0]['locator']['row_group'] = 99
                    return value
                with patch.object(located_module, '_sidecar', side_effect=damaged):
                    self.fail('invalid_contract', lambda: reader.read_located_batch(fixture['binding'], 0))
                self.assertEqual(objects.scope.output_bytes, sum(len(raw) for raw in fixture['objects'].values()))
                self.poisoned(fixture, reader)

    def test_nonowner_located_call_does_not_poison_the_active_owner(self):
        fixture = make_multisource_fixture(self.root)
        wall = fixture['binding'].value['context']['bound_at_unix_ms']
        _, reader, _ = self.reader(fixture, wall_ms=lambda: wall, monotonic=lambda: 0.0)
        entered, resume, results, errors = threading.Event(), threading.Event(), [], []
        original = reader_module.encode_located
        def paused(*args):
            entered.set()
            if not resume.wait(2): raise AssertionError('unit owner was not resumed')
            return original(*args)
        def owner():
            try: results.append(reader.read_located_batch(fixture['binding'], 0))
            except BaseException as error: errors.append(error)
        with patch.object(reader_module, 'encode_located', side_effect=paused):
            worker = threading.Thread(target=owner)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.fail('resource_limit', lambda: reader.read_located_batch(fixture['binding'], 0))
                self.assertFalse(reader._failed)
            finally:
                resume.set(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].batch.value['rows'], expected_rows(facts()))


if __name__ == '__main__':
    unittest.main()
