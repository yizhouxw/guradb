"""Independent wire vectors and hostile length/count bounds for narrow Parquet."""
import struct
import unittest

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_compact import Compact
from modules.connectors.fixed_parquet_pages import plain


class CompactTests(unittest.TestCase):
    def assert_code(self, expected, operation):
        with self.assertRaises(ContractFailure) as caught:
            operation()
        self.assertEqual(caught.exception.code, expected)

    def test_standard_typed_fields_and_signed_extremes(self):
        # Field1 i32=-1, field2 bool=true, field3 bool=false, field4 binary="x".
        parser = Compact(bytes.fromhex('1501111218017800'), lambda: None)
        value = parser.struct()
        self.assertEqual(value[1], (5, -1))
        self.assertEqual(value[2], (1, True))
        self.assertEqual(value[3], (2, False))
        self.assertEqual(value[4][0], 8)
        self.assertEqual(bytes(value[4][1]), b'x')
        self.assertEqual(parser.position, 8)
        for encoded, expected in ((b'\xff' * 9 + b'\x01', -(1 << 63)),
                                  (b'\xfe' + b'\xff' * 8 + b'\x01', (1 << 63) - 1)):
            self.assertEqual(Compact(encoded, lambda: None).integer(64), expected)

    def test_overflow_noncanonical_truncation_and_unknown_types_fail_closed(self):
        for raw in (b'\x80' * 10 + b'\x00', b'\xff' * 9 + b'\x02', b'\x80\x00', b'\x80'):
            with self.subTest(raw=raw.hex()):
                self.assert_code('corrupt_object', lambda: Compact(raw, lambda: None).varint())
        self.assert_code('unsupported_capability', lambda: Compact(b'\x17', lambda: None).struct())
        self.assert_code('corrupt_object', lambda: Compact(b'\x15\x00\x05\x02\x00\x00', lambda: None).struct())
        self.assert_code('corrupt_object', lambda: Compact(b'\x05\x00', lambda: None).struct())

    def test_container_bounds_before_allocation_and_finite_nesting(self):
        # Field1 list with explicit1025 count, and binary with65537-byte length.
        for raw in (bytes.fromhex('19f58108'), bytes.fromhex('18818004')):
            self.assert_code('resource_limit', lambda: Compact(raw, lambda: None).struct())
        self.assert_code('resource_limit', lambda: Compact(b'\x1c' * 13 + b'\x00' * 14,
                                                          lambda: None).struct())
        self.assert_code('resource_limit', lambda: Compact(bytes.fromhex('150000'), lambda: None,
                                                          max_nodes=1).struct())

    def test_check_is_called_during_each_finite_step(self):
        calls = []
        def check():
            calls.append(True)
            if len(calls) == 3:
                raise ContractFailure('cancelled', 'unit cancellation at parser boundary')
        self.assert_code('cancelled', lambda: Compact(bytes.fromhex('150000'), check).struct())
        self.assertEqual(len(calls), 3)


class PlainPageTests(unittest.TestCase):
    def assert_code(self, code, body, field, count):
        with self.assertRaises(ContractFailure) as caught:
            plain(body, field, count, lambda: None)
        self.assertEqual(caught.exception.code, code)

    def test_plain_int64_and_null_bitmap_keep_exact_values(self):
        raw = struct.pack('<qq', -(1 << 63), (1 << 63) - 1)
        self.assertEqual(plain(raw, {'type': 'int8', 'nullable': False}, 2, lambda: None),
                         [-(1 << 63), (1 << 63) - 1])
        # One eight-bit group, only3 valid flags: true,false,true; five padding bits.
        raw = struct.pack('<I', 2) + b'\x03\x05' + struct.pack('<I', 1) + b'A' + struct.pack('<I', 1) + b'B'
        self.assertEqual(plain(raw, {'type': 'text', 'nullable': True}, 3, lambda: None), ['A', None, 'B'])
        # Four repeated non-NULL definitions, then four PLAIN Boolean bits.
        raw = struct.pack('<I', 2) + b'\x08\x01\x0a'
        self.assertEqual(plain(raw, {'type': 'bool', 'nullable': True}, 4, lambda: None),
                         [False, True, False, True])

    def test_definition_run_must_not_expand_past_declared_rows(self):
        field = {'type': 'bool', 'nullable': True}
        for stream in (b'\x00', b'\x04\x01', b'\x02\x02', b'\x05\x00\x00',
                       b'\x02\x01\x02\x01', b'\x03'):
            with self.subTest(stream=stream.hex()):
                self.assert_code('corrupt_object', struct.pack('<I', len(stream)) + stream, field, 1)

    def test_text_and_plain_body_limits_are_not_silent_truncation(self):
        field = {'type': 'text', 'nullable': False}
        self.assert_code('corrupt_object', struct.pack('<I', 1) + b'\xff', field, 1)
        self.assert_code('corrupt_object', struct.pack('<I', 2) + b'a', field, 1)
        self.assert_code('resource_limit', struct.pack('<I', 16385), field, 1)
        raw = struct.pack('<I', 4097) + b'a' * 4097
        self.assert_code('resource_limit', raw, field, 1)
        self.assert_code('corrupt_object', struct.pack('<I', 1) + b'a!', field, 1)


class PageKindTests(unittest.TestCase):
    def test_legal_v2_without_summary_is_explicitly_unsupported(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from modules.connectors.fixed_parquet_pages import decode_column
        # PageHeader(type=3, uncompressed=1, compressed=1, data_page_header_v2).
        # V2 has1 value,0 NULLs,1 row,PLAIN,0 definition/repetition bytes,false.
        header = bytes.fromhex('1506150215025c150215001502150015001500120000')
        scope = SimpleNamespace(check=lambda: None, reserve=lambda _: nullcontext())
        plan = {'offset': 0, 'size': len(header) + 1, 'pages': None,
                'field': {'type': 'bool', 'nullable': False}}
        with self.assertRaises(ContractFailure) as caught:
            decode_column(header + b'\x01', plan, 1, scope)
        self.assertEqual(caught.exception.code, 'unsupported_capability')
        # type=V1 with its required V1 header absent remains a corrupt object.
        malformed = bytes.fromhex('15001502150200') + b'\x01'
        with self.assertRaises(ContractFailure) as caught:
            decode_column(malformed, {**plan, 'size': len(malformed)}, 1, scope)
        self.assertEqual(caught.exception.code, 'corrupt_object')

    def test_legal_v2_encoding_summary_is_explicitly_unsupported(self):
        from modules.connectors.fixed_parquet_plan import column
        value = {1: (5, 0), 2: (9, (5, [0, 3])), 3: (9, (8, [memoryview(b'active')])),
                 4: (5, 0), 5: (6, 1), 6: (6, 1), 7: (6, 1), 9: (6, 4),
                 13: (9, (12, [{1: (5, 3), 2: (5, 0), 3: (5, 1)}]))}
        with self.assertRaises(ContractFailure) as caught:
            column({2: (6, 0), 3: (12, value)}, {'type': 'bool', 'name': 'active'}, 1, 5)
        self.assertEqual(caught.exception.code, 'unsupported_capability')


class SizeStatisticsTests(unittest.TestCase):
    def test_only_empty_optional_page_statistics_are_supported(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from modules.connectors.fixed_parquet_pages import decode_column
        # V1 PLAIN Boolean page; field5 is the optional Statistics structure.
        prefix = bytes.fromhex('1500150215022c1502150015061506')
        scope = SimpleNamespace(check=lambda: None, reserve=lambda _: nullcontext())
        for suffix, code in ((bytes.fromhex('1c000000'), None),
                             (bytes.fromhex('1c3600000000'), 'unsupported_capability'),
                             (bytes.fromhex('15000000'), 'corrupt_object')):
            wire = prefix + suffix + b'\x01'
            plan = {'offset': 0, 'size': len(wire), 'pages': 1,
                    'field': {'type': 'bool', 'nullable': False}}
            with self.subTest(suffix=suffix.hex()):
                if code is None:
                    self.assertEqual(decode_column(wire, plan, 1, scope), [True])
                else:
                    with self.assertRaises(ContractFailure) as caught:
                        decode_column(wire, plan, 1, scope)
                    self.assertEqual(caught.exception.code, code)

    def test_flat_histograms_and_utf8_estimate_are_bounded(self):
        from modules.connectors.fixed_parquet_plan import size_statistics
        field = {'type': 'text', 'nullable': True}
        value = {1: (6, 3), 2: (9, (6, [])), 3: (9, (6, [1, 2]))}
        self.assertEqual(size_statistics(value, field, 3), {'text_bytes': 3, 'null_count': 1})
        self.assertEqual(size_statistics({}, field, 3), {})
        required = {'type': 'bool', 'nullable': False}
        self.assertEqual(size_statistics({2: (9, (6, [3])), 3: (9, (6, [3]))},
                                         required, 3), {'null_count': 0})

    def test_invalid_count_type_shape_and_unknown_semantics_are_rejected(self):
        from modules.connectors.fixed_parquet_plan import size_statistics
        field = {'type': 'text', 'nullable': True}
        cases = [({1: (6, -1)}, 'corrupt_object'),
                 ({1: (6, (1 << 20) + 1)}, 'corrupt_object'),
                 ({1: (5, 1)}, 'corrupt_object'),
                 ({2: (9, (6, [1, 2]))}, 'corrupt_object'),
                 ({3: (9, (6, [1, 1]))}, 'corrupt_object'),
                 ({3: (9, (6, [-1, 4]))}, 'corrupt_object'),
                 ({3: (9, (5, [1, 2]))}, 'corrupt_object'),
                 ({4: (6, 0)}, 'unsupported_capability')]
        for value, code in cases:
            with self.subTest(value=value), self.assertRaises(ContractFailure) as caught:
                size_statistics(value, field, 3)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ContractFailure) as caught:
            size_statistics({1: (6, 0)}, {'type': 'bool', 'nullable': False}, 3)
        self.assertEqual(caught.exception.code, 'corrupt_object')

    def test_decoded_values_must_match_declared_nulls_and_utf8_bytes(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from modules.connectors.fixed_parquet_pages import decode_column
        # Required flat text: two PLAIN strings, "a" and U+00E9 (three UTF8 bytes).
        body = struct.pack('<I', 1) + b'a' + struct.pack('<I', 2) + b'\xc3\xa9'
        header = bytes.fromhex('150015') + bytes([2 * len(body)])
        header += b'\x15' + bytes([2 * len(body)]) + bytes.fromhex('2c15041500150615060000')
        plan = {'offset': 0, 'size': len(header) + len(body), 'pages': 1,
                'field': {'type': 'text', 'nullable': False},
                'size_statistics': {'text_bytes': 3, 'null_count': 0}}
        scope = SimpleNamespace(check=lambda: None, reserve=lambda _: nullcontext())
        self.assertEqual(decode_column(header + body, plan, 2, scope), ['a', '\u00e9'])
        for statistics in ({'text_bytes': 4}, {'null_count': 1}):
            with self.subTest(statistics=statistics), self.assertRaises(ContractFailure) as caught:
                decode_column(header + body, {**plan, 'size_statistics': statistics}, 2, scope)
            self.assertEqual(caught.exception.code, 'corrupt_object')
