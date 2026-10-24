"""Local boundary tests; actual C1/pin cleanup requires the real-chain run."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'scripts/m0lib/fixed-chain-fd-cleanup.py'
SPEC = importlib.util.spec_from_file_location('gura_fixed_fd_cleanup_boundary', SOURCE)
LEAF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEAF)


class Output:
    def __init__(self):
        self.buffer = io.BytesIO()


class CleanupBoundaryTests(unittest.TestCase):
    def test_invoice_integer_projection_rounds_actual_tiny_seconds_up(self):
        invoice = {'counts': {'wait': 2, 'sql_attempt': 1},
                   'seconds': {'wait': 1e-5, 'sql_success': 1e-10},
                   'events': [('wait', 1e-5)], 'pg_native_memory_bytes': None}
        projected = LEAF.project_invoice(invoice)
        self.assertEqual(set(projected), {'version', 'counts', 'phase_us', 'native_memory_bytes'})
        self.assertEqual(projected['version'], 1)
        self.assertEqual(projected['counts'][3:5], [2, 1])
        numerator, denominator = (1e-5).as_integer_ratio()
        self.assertEqual(projected['phase_us'][3], (numerator * 1_000_000 + denominator - 1) // denominator)
        self.assertEqual(projected['phase_us'][3], 11)  # Exact float is slightly above ten microseconds.
        self.assertEqual(projected['phase_us'][5], 1)
        self.assertIsNone(projected['native_memory_bytes'])
        self.assertEqual(len(projected['counts']), 11)
        self.assertEqual(len(projected['phase_us']), 11)
        self.assertNotIn(b'1e-', LEAF.canonical(projected))
        self.assertNotIn('events', projected)

    def test_unobserved_is_unknown_and_partial_counts_remain_actual(self):
        self.assertIsNone(LEAF.project_invoice(None))
        projected = LEAF.project_invoice({'counts': {'connect_attempt': 1}})
        self.assertEqual(projected['counts'], [1] + [0] * 10)
        self.assertIsNone(projected['native_memory_bytes'])

    def test_invalid_invoice_counters_times_and_native_claim_are_refused(self):
        samples = [{'counts': {'sql_attempt': value}} for value in (True, -1, 1.5, 1 << 53)]
        samples += [{'counts': {}, 'seconds': {'wait': value}}
                    for value in (True, -1, float('nan'), float('inf'), 1e20)]
        samples += [{'counts': {'invented': 1}}, {'counts': {}, 'seconds': {'invented': 0}},
                    {'counts': {}, 'pg_native_memory_bytes': 0}]
        for invoice in samples:
            with self.subTest(invoice=invoice), self.assertRaises((ValueError, OverflowError)):
                LEAF.project_invoice(invoice)

    def test_missing_or_invalid_invoice_cannot_publish_successful_release(self):
        def released(request, config, cutoff, expected, observed):
            observed.update(pg={'counts': {'sql_attempt': True}}, complete=True)
            return {'version': 1, 'state': 'released', 'scope': 'pin-cleanup-only'}
        output = Output()
        with patch.object(LEAF, 'cleanup', side_effect=released), patch.object(LEAF.sys, 'stdout', output):
            code = LEAF.main(['--request', '/evidence/private/request', '--config', '/evidence/private/config',
                              '--cutoff-ns', '123'])
        value = json.loads(output.buffer.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(value['state'], 'cleanup_unconfirmed')
        self.assertIsNone(value['cleanup_pg'])
        self.assertFalse(value['cleanup_pg_complete'])

    def test_readback_requires_exact_original_binding_pin_and_lease(self):
        request = SimpleNamespace(encoded=b'original-request', sha256='a' * 64)
        binding = SimpleNamespace(sha256='b' * 64,
            value={'context': {'pin': {'pin_id': 'original-pin', 'lease_id': 'original-lease'}}})
        row = {'binding_sha256': 'b' * 64, 'released': True,
               'pin_id': 'original-pin', 'lease_id': 'original-lease'}
        self.assertEqual(LEAF.readback_identity(row, request, binding, request, 'b' * 64),
                         ('original-pin', 'original-lease'))
        for key, replacement in (('pin_id', 'different-valid-pin'), ('lease_id', 'different-valid-lease')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                LEAF.readback_identity({**row, key: replacement}, request, binding, request, 'b' * 64)

    def test_readback_rejects_wrong_request_binding_or_unreleased_row(self):
        request = SimpleNamespace(encoded=b'original-request', sha256='a' * 64)
        binding = SimpleNamespace(sha256='b' * 64,
            value={'context': {'pin': {'pin_id': 'original-pin', 'lease_id': 'original-lease'}}})
        row = {'binding_sha256': 'b' * 64, 'released': True,
               'pin_id': 'original-pin', 'lease_id': 'original-lease'}
        wrong = SimpleNamespace(encoded=b'other-request', sha256='c' * 64)
        for changed, stored, expected in ((row, wrong, 'b' * 64),
                ({**row, 'released': False}, request, 'b' * 64),
                ({**row, 'binding_sha256': 'd' * 64}, request, 'b' * 64),
                (row, request, 'd' * 64)):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                LEAF.readback_identity(changed, stored, binding, request, expected)

    def test_original_absolute_cutoff_consumes_elapsed_time_without_reset(self):
        with patch.object(LEAF.time, 'clock_gettime_ns', side_effect=[100, 101, 199, 200]):
            cutoff = LEAF.Cutoff(200)
            self.assertEqual(cutoff.checkpoint(), 200 / 1_000_000_000)
            self.assertEqual(cutoff.checkpoint(), 200 / 1_000_000_000)
            with self.assertRaises(TimeoutError):
                cutoff.checkpoint()
        self.assertEqual(cutoff.ns, 200)

    def test_expired_extended_invalid_or_reset_duration_refused_and_raw_ns_retained(self):
        now = (1 << 63) + 101
        with patch.object(LEAF.time, 'clock_gettime_ns', return_value=now):
            for raw in (True, 0, now, now + 5_000_000_001, 1 << 64, '5000'):
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    LEAF.Cutoff(raw)
            self.assertEqual(LEAF.Cutoff(now + 1).ns, now + 1)

    def test_private_file_exact_bytes_and_outside_symlink_directory_or_oversize_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'private'
            root.mkdir()
            inside, outside = root / 'input', Path(directory) / 'outside'
            inside.write_bytes(b'canonical-private')
            outside.write_bytes(b'not-allowed')
            link = root / 'link'
            link.symlink_to(inside)
            with patch.object(LEAF, 'PRIVATE', root), patch.object(LEAF.time, 'clock_gettime_ns', return_value=100):
                cutoff = LEAF.Cutoff(200)
                self.assertEqual(LEAF.bounded_private(inside, 32, cutoff), b'canonical-private')
                for path, cap in ((outside, 32), (link, 32), (root, 32), (inside, 1)):
                    with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                        LEAF.bounded_private(path, cap, cutoff)

    def test_fifo_input_refused_without_open_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / 'fifo'
            os.mkfifo(fifo)
            with patch.object(LEAF, 'PRIVATE', root), patch.object(LEAF.time, 'clock_gettime_ns', return_value=100):
                with self.assertRaises(ValueError):
                    LEAF.bounded_private(fifo, 65536, LEAF.Cutoff(200))

    def test_unknown_cli_arguments_never_echo_sensitive_input(self):
        output, errors = Output(), io.StringIO()
        secret = 'password-do-not-export'
        with patch.object(LEAF.sys, 'stdout', output), patch.object(LEAF.sys, 'stderr', errors):
            code = LEAF.main(['--unexpected', secret])
        raw = output.buffer.getvalue()
        self.assertEqual(code, 1)
        self.assertNotIn(secret.encode(), raw)
        self.assertEqual(errors.getvalue(), '')
        self.assertEqual(json.loads(raw)['state'], 'cleanup_unconfirmed')

    def test_cleanup_failure_keeps_partial_pg_invoice_without_exception_text(self):
        class BackendFailure(Exception):
            code = 'backend_unavailable'
        def failed(request, config, cutoff, expected, observed):
            observed.update(pg={'counts': {'connect_attempt': 1, 'sql_attempt': 2}}, complete=False)
            raise BackendFailure('secret-endpoint-and-password')
        output, errors = Output(), io.StringIO()
        with patch.object(LEAF, 'cleanup', side_effect=failed), patch.object(LEAF.sys, 'stdout', output), \
                patch.object(LEAF.sys, 'stderr', errors):
            code = LEAF.main(['--request', '/evidence/private/request', '--config', '/evidence/private/config',
                              '--cutoff-ns', '123'])
        raw = output.buffer.getvalue()
        result = json.loads(raw)
        self.assertEqual(code, 1)
        self.assertEqual(result['cleanup_pg']['counts'][4], 2)
        self.assertEqual(result['cleanup_pg']['version'], 1)
        self.assertFalse(result['cleanup_pg_complete'])
        self.assertNotIn(b'secret', raw)
        self.assertEqual(errors.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
