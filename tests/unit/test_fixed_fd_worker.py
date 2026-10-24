"""SQLite-C1 and local producer unit definitions, not PG/FD/S3 evidence."""
import hashlib
import sys
import weakref
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.catalog.cf1a_control import CatalogReadControl
from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_fd_protocol import Credit, Header, Transport, decode, encode
from modules.connectors.fixed_fd_worker import FixedFdWorker, ZERO_HANDLE, ZERO_HASH
from tests.catalog_support.fixed_fixture import request
from tests.unit import test_cf1a_catalog_controlled as catalog_fixture
from tests.unit import test_fixed_linux_anchor as anchor_fixture
from tests.unit import test_fixed_producer_lifecycle as producer_fixture


class FdWorkerTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_fixture.ControlledReadTests()
        self.catalog.setUp()
        self.addCleanup(self.catalog.doCleanups)
        self.clock = anchor_fixture.LinuxAnchorTests()
        self.clock.setUp()
        self.addCleanup(self.clock.doCleanups)
        self.parent = self.clock.parent()
        self.control = CatalogReadControl(self.parent.checkpoint, self.parent.monotonic)
        self.reads = self.catalog.catalog.controlled_reads(self.catalog.principal, self.control)
        self.io = object.__new__(Transport)
        self.io.parent = self.parent
        self.io.checkpoint = lambda: self.parent.checkpoint()
        self.io.send = lambda *args: self.sent.append(args)
        self.io.failed = False
        self.sent = []

    def worker(self):
        return FixedFdWorker(self.io, self.reads, {}, Credit(2 << 20, self.clock.session, 1),
                             request_decode_credit=1 << 20, producer_credit=8 << 20)

    def call(self, worker, kind, sequence, pgseq, *, handle=ZERO_HANDLE, fingerprint=ZERO_HASH):
        raw = encode('call', kind, 0, 0, pgseq, self.clock.cutoff, 1, handle, fingerprint, 8192, 8192)
        header = Header(1, self.clock.session, sequence, 0, len(raw), hashlib.sha256(raw).digest())
        worker._parse_call(header, raw)
        return raw

    def test_fake_authority_or_wrong_credit_identity_refused(self):
        with self.assertRaises(ContractFailure):
            FixedFdWorker(self.io, SimpleNamespace(control=self.control), {},
                          Credit(2 << 20, self.clock.session, 1),
                          request_decode_credit=1 << 20, producer_credit=8 << 20)
        with self.assertRaises(ContractFailure):
            FixedFdWorker(self.io, self.reads, {}, Credit(2 << 20, b'x' * 16, 1),
                          request_decode_credit=1 << 20, producer_credit=8 << 20)

    def test_call_reserved_shape_and_nonread_ordinal_rejected(self):
        worker = self.worker()
        raw = encode('call', 2, 1, 0, 1, self.clock.cutoff, 1, ZERO_HANDLE, ZERO_HASH, 8192, 8192)
        header = Header(1, self.clock.session, 1, 0, len(raw), hashlib.sha256(raw).digest())
        with self.assertRaises(ContractFailure):
            worker._parse_call(header, raw)
        raw = self.call(worker, 2, 1, 1)
        with self.assertRaises(ContractFailure):
            worker._parse_call(Header(1, self.clock.session, 1, 1, 96, hashlib.sha256(raw).digest()), raw)

    def test_same_actual_sqlite_c1_retire_and_expiry_preserve_control(self):
        worker = self.worker()
        worker.request = request(self.catalog.principal)
        worker.binding = self.reads.bind(worker.request)
        worker.state = 'prepared'
        self.call(worker, 6, 2, 2, fingerprint=bytes.fromhex(worker.binding.sha256))
        with self.parent.fd_operation(6, 2, 2, self.clock.cutoff):
            worker._authorize(True)
        self.assertEqual(worker.state, 'retiring')
        self.assertIs(worker.reads.control, self.control)
        self.assertIs(self.parent.invoice['catalog']['pg_native_memory_bytes'], None)
        with self.assertRaises(ContractFailure):
            worker._authorize(True)

    def test_retire_revocation_is_original_c1_error(self):
        worker = self.worker()
        worker.request = request(self.catalog.principal)
        worker.binding = self.reads.bind(worker.request)
        worker.state = 'prepared'
        self.call(worker, 6, 2, 2, fingerprint=bytes.fromhex(worker.binding.sha256))
        primary = ContractFailure('revoked', 'fixed private failure')
        with patch.object(self.reads, 'reauthorize', side_effect=primary):
            with self.assertRaises(ContractFailure) as caught:
                worker._authorize(True)
        self.assertIs(caught.exception, primary)
        self.assertEqual(worker.state, 'prepared')

    def test_auth_and_bind_finish_do_not_duplicate_source_execution(self):
        worker = self.worker()
        self.call(worker, 2, 1, 1)
        self.control.mark('connect_attempt')
        worker._finish()
        raw = self.sent[-1][3]
        finish = decode('finish', raw)
        self.assertEqual(finish[6:12], (0,) * 6)
        self.assertEqual(finish[13], 3)
        self.assertEqual(finish[14], 1)
        self.assertEqual(self.sent[-1][0], 5)

    def test_ack_finish_reconcile_cannot_reexecute_read_or_pg(self):
        worker = self.worker()
        self.call(worker, 2, 1, 1)
        worker._finish()
        digest = hashlib.sha256(worker._finish_raw).digest()
        reconcile = encode('reconcile', 2, 0, 2, 0, 0, 272, digest, b'\0' * 8)
        ack = encode('ack', 2, 0, 1, 0, 0, 272, digest, b'\0' * 8)
        values = iter([(Header(9, self.clock.session, 1, 0, 64, b'h' * 32), reconcile),
                       (Header(7, self.clock.session, 1, 0, 64, b'h' * 32), ack)])
        self.io.receive = lambda *a, **k: next(values)
        with patch.object(self.reads, 'reauthorize') as pg:
            worker._ack()
        pg.assert_not_called()
        self.assertTrue(worker._replayed)
        self.assertEqual([item[0] for item in self.sent], [5, 5])

    def test_shared_replay_budget_rejects_second_reconcile(self):
        worker = self.worker()
        self.call(worker, 2, 1, 1)
        worker._finish()
        digest = hashlib.sha256(worker._finish_raw).digest()
        raw = encode('reconcile', 2, 0, 2, 0, 0, 272, digest, b'\0' * 8)
        self.io.receive = lambda *a, **k: (Header(9, self.clock.session, 1, 0, 64, b'h' * 32), raw)
        with self.assertRaises(ContractFailure) as caught:
            worker._ack()
        self.assertEqual(caught.exception.code, 'resource_limit')

    def test_stop_only_prepare_retains_actual_producer_credit(self):
        local = producer_fixture.ProducerLifecycleTests()
        local.setUp()
        self.addCleanup(local.doCleanups)
        _, producer, grant, _ = local.producer()
        summary = producer.open(grant)
        local.ack(producer)
        before = grant.current
        observation = producer.prepare_close(summary.handle)
        self.assertEqual(observation.state, 'prepared')
        self.assertEqual(grant.current, before)
        self.assertGreater(before, 0)
        self.assertIsNone(observation.native_memory_bytes)
        self.assertEqual(producer.prepare_close(summary.handle).state, 'prepared')
        producer.close(summary.handle)  # Old local close still has its original semantics.
        self.assertEqual(grant.current, 0)

    def test_ack_destroys_contract_and_all_ack_payload_aliases_before_refund(self):
        local = producer_fixture.ProducerLifecycleTests()
        local.setUp()
        self.addCleanup(local.doCleanups)
        _, producer, grant, _ = local.producer()
        summary = producer.open(grant)
        local.ack(producer)
        page = producer.read(summary.handle, 0, 2)
        payload = page.contract.encoded  # One intentional test-owned reference.
        contract_ref = weakref.ref(page.contract)
        worker = self.worker()
        self.call(worker, 4, 2, 2)
        worker.producer, worker._page, worker._data = producer, page, payload
        worker._role, worker._lease_epoch = 3, 1
        raw = encode('ack', 4, 3, 1, 0, 1, len(payload), hashlib.sha256(payload).digest(), b'\0' * 8)
        self.io.receive = lambda *a, **k: (Header(7, self.clock.session, 2, 0, 64, b'h' * 32), raw)
        original = page._lease.release
        observed = []
        def release():
            self.assertIsNone(contract_ref())
            # Test closure is the only strong owner; getrefcount adds its one
            # temporary argument. A lingering _ack.target would make this3.
            self.assertEqual(sys.getrefcount(payload), 2)
            self.assertIsNone(worker._data)
            observed.append(grant.current)
            return original()
        with patch.object(page._lease, 'release', side_effect=release):
            worker._ack()
        self.assertEqual(len(observed), 1)
        self.assertLess(grant.current, observed[0])
        producer.close(summary.handle)

    def test_call_wire_extra_reject_u64_credit_but_cutoff_keeps_u64(self):
        worker = self.worker()
        values = [2, 0, 0, 1, (1 << 64) - 1, 1, ZERO_HANDLE, ZERO_HASH, 8192, 8192]
        for field in (8, 9):
            for bad in (0, 1 << 53, (1 << 64) - 1):
                changed = list(values)
                changed[field] = bad
                raw = encode('call', *changed)
                header = Header(1, self.clock.session, 1, 0, 96, hashlib.sha256(raw).digest())
                with self.assertRaises(ContractFailure):
                    worker._parse_call(header, raw)
        values[8] = values[9] = (1 << 53) - 1
        raw = encode('call', *values)
        self.assertEqual(worker._parse_call(Header(1, self.clock.session, 1, 0, 96,
                                                  hashlib.sha256(raw).digest()), raw)[2], (1 << 64) - 1)

    def test_permit_each_credit_rejects_unsafe_before_data_send(self):
        worker = self.worker()
        self.call(worker, 1, 1, 1)
        data = b'prepaid-data'
        for field in (8, 9, 10, 11):
            for bad in (1 << 53, (1 << 64) - 1):
                def receive(*args):
                    values = [1, 2, 0, 0, worker._lease_epoch, 1, len(data),
                              hashlib.sha256(data).digest(), len(data), 1024, 4096, 4096]
                    values[field] = bad
                    return encode('permit', *values)
                self.io.receive = receive
                with patch.object(worker, '_send_data') as send:
                    with self.assertRaises(ContractFailure):
                        worker._offer_data(data, 2)
                send.assert_not_called()
        # Safe maximum is still admitted; the raw-ns cutoff domain is unrelated.
        def receive_safe(*args):
            return encode('permit', 1, 2, 0, 0, worker._lease_epoch, 1, len(data),
                          hashlib.sha256(data).digest(), *((1 << 53) - 1,) * 4)
        self.io.receive = receive_safe
        with patch.object(worker, '_send_data') as send:
            worker._offer_data(data, 2)
        send.assert_called_once_with(False)


if __name__ == '__main__':
    unittest.main()
