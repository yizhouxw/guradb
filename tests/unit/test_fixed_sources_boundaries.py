"""Independent malformed wire, writer metadata and failed-delivery boundaries.

Mocked fetch and encoder/authority failures prove unit behavior only. They do
not certify the backend, network deadlines, or actual component memory costs.
"""
from contextlib import nullcontext
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_compact import Compact, text
from modules.connectors.fixed_parquet_pages import decode_column
from modules.connectors.fixed_parquet_plan import auxiliary, footer
from modules.connectors.fixed_source_manifest import bounded_json
from modules.connectors.fixed_source_reader import FixedSourceReader
from tests.source_support.fixed_fixture import make_fixture, unit_objects


class FixedSourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = temporary.name

    def reader(self, **writer_options):
        fixture = make_fixture(self.root, writer_options=writer_options)
        objects, fetched, attempts = unit_objects(fixture)
        patcher = patch('modules.storage.fixed_objects.fetch', side_effect=fetched)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fixture, objects, FixedSourceReader(objects), attempts

    def assert_code(self, expected, operation):
        with self.assertRaises(ContractFailure) as caught:
            operation()
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def test_compact_signed_octets_and_invalid_utf8_are_distinct(self):
        # Compact BYTE is signed; these are literal protocol vectors.
        for raw, expected in ((b'\x00', 0), (b'\x7f', 127), (b'\x80', -128), (b'\xff', -1)):
            self.assertEqual(Compact(raw, lambda: None).value(3, 0), expected)
        self.assertEqual(text(memoryview('中😀'.encode())), '中😀')
        for raw in (b'\xff', b'\xc0\x80', b'\xed\xa0\x80'):
            with self.subTest(raw=raw.hex()):
                self.assert_code('corrupt_object', lambda: text(memoryview(raw)))

    def test_json_quoted_structure_and_numeric_encoding_fail_closed(self):
        value = {'quoted': '\\"[,]{}', 'rows': [0, 1, 9007199254740991]}
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        checks = []
        self.assertEqual(bounded_json(raw, lambda: checks.append(True)), value)
        self.assertGreaterEqual(len(checks), 2)
        for raw, code in ((b'{"n":1.5}', 'invalid_contract'), (b'{"n":NaN}', 'invalid_contract'),
                          (b'{"n":-0}', 'invalid_contract'), (b'\xff', 'corrupt_object'),
                          (b'{"a":}', 'corrupt_object')):
            with self.subTest(raw=raw):
                self.assert_code(code, lambda: bounded_json(raw, lambda: None))

    def test_arrow_auxiliary_schema_is_opaque_and_cannot_add_semantics(self):
        fixture, _, reader, _ = self.reader(store_schema=True)
        result = reader.port.read_batch(fixture['binding'], 0)
        self.assertEqual(len(result.value['rows']), 11)
        self.assertEqual(result.value['rows'][0]['record_id'], 'r-a1')
        pair = {1: (8, memoryview(b'ARROW:schema')), 2: (8, memoryview(b'opaque'))}
        auxiliary({5: (9, (12, [pair]))}, 1)
        for pairs in ([pair, pair], [{1: (8, memoryview(b'ARROW:schema'))}],
                      [{1: (8, memoryview(b'other')), 2: (8, memoryview(b'x'))}]):
            self.assert_code('unsupported_capability', lambda: auxiliary({5: (9, (12, pairs))}, 1))

    def test_real_writer_page_crc_rejects_corruption_before_value_delivery(self):
        fixture = make_fixture(self.root, writer_options={'write_page_checksum': True})
        raw = (fixture['directory'] / 'source-0.parquet').read_bytes()
        scope = SimpleNamespace(check=lambda: None, reserve=lambda _: nullcontext())
        plans = footer(raw, fixture['metadata']['source_schema'], [4, 4, 3], scope)
        plan = next(column for column in plans[0] if column['field']['type'] == 'bool')
        self.assertEqual(len(decode_column(raw, plan, 4, scope)), 4)
        parser = Compact(memoryview(raw)[plan['offset']:], lambda: None)
        self.assertIn(4, parser.struct(), 'independent writer did not emit a page checksum')
        damaged = bytearray(raw)
        damaged[plan['offset'] + parser.position] ^= 1
        error = self.assert_code('corrupt_object', lambda: decode_column(bytes(damaged), plan, 4, scope))
        self.assertIn('checksum', str(error))

    def test_authority_errors_clear_reader_without_fetch_or_fabricated_output(self):
        for injected, code in ((ContractFailure('revoked', 'unit revoked authority'), 'revoked'),
                               (OSError('unit authority unavailable'), 'unauthorized')):
            fixture, objects, reader, attempts = self.reader()
            objects.reauthorize = lambda _, error=injected: (_ for _ in ()).throw(error)
            self.assert_code(code, lambda: reader.port.read_batch(fixture['binding'], 0))
            self.assertEqual(attempts, [])
            self.assertIsNone(reader._state)
            self.assertTrue(reader._failed)
            self.assertEqual(objects.scope.output_bytes, 0)

    def test_unstable_encoder_cannot_commit_an_unaccounted_envelope(self):
        # Fault injection violates the deterministic canonical encoder's
        # contract. The bounded fixed-point guard must fail before delivery.
        from modules.connectors import fixed_source_reader as module
        fixture, objects, reader, _ = self.reader()
        original_encode, original_canonical = reader._encode, module.canonical
        calls = []

        def unstable(value):
            calls.append(True)
            return original_canonical(value) + b' ' * (100 * len(calls))

        def encode_with_fault(*arguments):
            with patch.object(module, 'canonical', side_effect=unstable):
                return original_encode(*arguments)

        with patch.object(reader, '_encode', side_effect=encode_with_fault):
            error = self.assert_code('resource_limit', lambda: reader.port.read_batch(fixture['binding'], 0))
        self.assertIn('converge', str(error))
        self.assertIsNone(reader._state)
        self.assertTrue(reader._failed)
        self.assertEqual(objects.scope.output_bytes, sum(len(raw) for raw in fixture['objects'].values()))
