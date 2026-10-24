"""Private FD unit definitions; mocked OS only, not actual IPC/PG acceptance."""
import hashlib
import struct
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_fd_protocol import (Cancellation, Credit, FORMATS, Header,
                                                 SIZES, Transport, TYPES, WIRE_CAP, decode, encode)
from modules.connectors.fixed_fd_protocol import scan_request


class FdProtocolTests(unittest.TestCase):
    def test_exact_joint_body_sizes_and_header_roundtrip(self):
        for name, fmt in FORMATS.items():
            self.assertEqual(struct.calcsize(fmt), SIZES[name], name)
        header = Header(1, b's' * 16, 1, 0, 96, b'h' * 32)
        self.assertEqual(len(header.encoded()), 80)
        self.assertEqual(Header.parse(header.encoded(), b's' * 16), header)

    def test_session_type_zero_sequence_and_oversize_fail_before_body(self):
        raw = Header(1, b's' * 16, 1, 0, 96, b'h' * 32).encoded()
        for other in (b'n' * 16, b'\0' * 16):
            with self.assertRaises(ContractFailure):
                Header.parse(raw, other)
        for header in (Header(True, b's' * 16, 1, 0, 1, b'h' * 32),
                       Header(1, b's' * 16, 0, 0, 96, b'h' * 32),
                       Header(4, b's' * 16, 1, 0, 786433, b'h' * 32),
                       Header(1, b's' * 16, 1 << 53, 0, 96, b'h' * 32)):
            with self.assertRaises(ContractFailure):
                header.encoded()

    def test_layout_closed_values_and_lengths(self):
        self.assertEqual(decode('caps', encode('caps', 1, 2, 3, 4, 5, 6)), (1, 2, 3, 4, 5, 6))
        for callback in (lambda: encode('unknown'), lambda: encode('caps', -1, 2, 3, 4, 5, 6),
                         lambda: decode('call', b'x' * 95)):
            with self.assertRaises(ContractFailure):
                callback()

    def test_prepaid_credit_exhaustion_has_no_refund_on_failure(self):
        credit = Credit(100, b's' * 16, 1)
        credit.reserve(80)
        with self.assertRaises(ContractFailure):
            credit.reserve(21)
        self.assertEqual((credit.live, credit.peak), (80, 80))
        credit.release(80)
        with self.assertRaises(ContractFailure):
            credit.release(1)
        with self.assertRaises(ContractFailure):
            Credit(100, b's' * 16, 1 << 53)

    def transport(self):
        # Exercise real methods with fake nonblocking syscalls; no actual FD.
        io = object.__new__(Transport)
        io.session, io.control = b's' * 16, Credit(4096, b's' * 16, 1)
        io.wire_bytes = io.sent_bytes = io.received_bytes = io.messages = 0
        io.failed = io.partial = False
        io.checkpoint = lambda: 1
        io.fd, io.cancel_fd = 1, 2
        return io

    def test_data_requires_exact_preallocated_buffer_before_body_read(self):
        io = self.transport()
        raw = b'abc'
        header = Header(4, io.session, 1, 0, 3, hashlib.sha256(raw).digest()).encoded()
        reads = []
        def transfer(buffer, sending):
            reads.append(len(buffer))
            buffer[:] = header
        with patch.object(io, '_transfer', side_effect=transfer):
            with self.assertRaises(ContractFailure):
                io.receive(TYPES['DATA'], 1, 0)
        self.assertEqual(reads, [80])
        self.assertTrue(io.failed)

    def test_permit_digest_mismatch_never_reads_data_body(self):
        io = self.transport()
        header = Header(4, io.session, 1, 0, 3, b'h' * 32).encoded()
        with patch.object(io, '_transfer', side_effect=lambda buf, _: buf.__setitem__(slice(None), header)) as read:
            with self.assertRaises(ContractFailure):
                io.receive(4, 1, 0, data=bytearray(3), digest=b'z' * 32)
        self.assertEqual(read.call_count, 1)

    def test_short_io_and_hash_failure_poison_transport(self):
        io = self.transport()
        with patch('modules.connectors.fixed_fd_protocol.select.select', return_value=([1], [], [])), \
             patch('modules.connectors.fixed_fd_protocol.os.readv', return_value=0):
            with self.assertRaises(ContractFailure) as caught:
                io.receive(1, 1, 0)
        self.assertEqual(caught.exception.code, 'outcome_unknown')
        self.assertTrue(io.failed)
        io = self.transport()
        header = Header(1, io.session, 1, 0, 3, hashlib.sha256(b'yes').digest()).encoded()
        parts = iter((header, b'bad'))
        with patch.object(io, '_transfer', side_effect=lambda buf, _: buf.__setitem__(slice(None), next(parts))):
            with self.assertRaises(ContractFailure) as caught:
                io.receive(1, 1, 0)
        self.assertEqual(caught.exception.code, 'corrupt_object')
        self.assertTrue(io.failed)

    def test_message_cap_and_wire_are_not_reset_by_tighten(self):
        io = self.transport()
        io.messages = 31
        io._message(0)
        with self.assertRaises(ContractFailure):
            io._message(0)
        io.messages, io.wire_bytes = 0, WIRE_CAP - 80
        io._message(0)
        with self.assertRaises(ContractFailure):
            io._message(1)

    def test_cancel_eof_is_sticky_for_pg_and_transport(self):
        with patch('modules.connectors.fixed_fd_protocol.os.set_blocking'), \
             patch('modules.connectors.fixed_fd_protocol.select.select', return_value=([2], [], [])), \
             patch('modules.connectors.fixed_fd_protocol.os.read', return_value=b'') as read:
            cancel = Cancellation()
            self.assertTrue(cancel.cancelled())
            self.assertTrue(cancel.cancelled())
        self.assertEqual(read.call_count, 1)

    def test_preparse_counts_unicode_before_json_tree_and_preserves_raw(self):
        raw = bytearray('{"k":"😀"}'.encode())
        before = bytes(raw)
        self.assertEqual(scan_request(raw), (3, 2))
        self.assertEqual(raw, before)
        self.assertEqual(scan_request(b'{"k":"\\ud83d\\ude00"}'), (3, 2))

    def test_preparse_high_node_text_utf8_surrogate_and_raw_caps(self):
        cases = [b'[' + b','.join([b'0'] * 57) + b']',
                 b'{"k":"' + b'x' * 1629 + b'"}', b'{"k":"\\ud800"}',
                 b'{"k":"\xc0\x80"}', b'{"k":9007199254740992}', b' ' * 65537]
        for raw in cases:
            with self.assertRaises(ContractFailure):
                scan_request(raw)

    def test_other_credit_entrances_reject_unsafe_without_transmission(self):
        for bad in (1 << 53, (1 << 64) - 1):
            with self.assertRaises(ContractFailure):
                Credit(bad, b's' * 16, 1)
            for wire, extra in ((bad, 1024), (1024, bad)):
                io = self.transport()
                with patch.object(io, '_transfer') as transfer:
                    with self.assertRaises(ContractFailure):
                        io.send(1, 1, 0, b'control', wire, extra)
                transfer.assert_not_called()
        credit = Credit((1 << 53) - 1, b's' * 16, 1)
        self.assertEqual(credit.amount, (1 << 53) - 1)


if __name__ == '__main__':
    unittest.main()
