"""Pure local grant ownership negatives; no cross-process authority claim."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_producer_credits import PreparedPermit, ProducerGrant


class ProducerCreditTests(unittest.TestCase):
    def grant(self, amount=8192):
        grant = ProducerGrant(PreparedPermit('session', 'a' * 64, 1), amount)
        grant.claim('a' * 64, 8 << 20)
        return grant

    def test_temporary_shrink_release_and_double_release(self):
        grant = self.grant()
        lease = grant.reserve(1000)
        self.assertEqual(grant.current, 1128)
        lease.shrink(200)
        self.assertEqual(grant.current, 328)
        self.assertTrue(lease.release())
        self.assertFalse(lease.release())
        self.assertEqual(grant.current, 0)
        self.assertEqual(grant.peak, 1128)

    def test_failed_reserve_never_increments_or_mints(self):
        grant = self.grant(1024)
        with self.assertRaises(ContractFailure):
            grant.reserve(1024)
        self.assertEqual(grant.snapshot()['live_leases'], 0)
        self.assertEqual(grant.current, 0)
        for invalid in (-1, True, 1.5):
            with self.assertRaises(ContractFailure):
                grant.reserve(invalid)

    def test_close_keeps_consumer_output_independently_live(self):
        grant = self.grant()
        resident = grant.reserve(400)
        output = grant.reserve(600, kind='output')
        grant.close_resident()
        self.assertTrue(resident.released)
        self.assertFalse(output.released)
        self.assertEqual(grant.current, 728)
        output.release()
        self.assertEqual(grant.current, 0)
        with self.assertRaises(ContractFailure):
            grant.reserve(1)

    def test_claim_wrong_identity_consumed_and_budget_strict(self):
        grant = ProducerGrant(PreparedPermit('session', 'a' * 64, 1), 1024)
        with self.assertRaises(ContractFailure):
            grant.claim('b' * 64, 8192)
        with self.assertRaises(ContractFailure):
            grant.claim('a' * 64, 8192)
        other = ProducerGrant(PreparedPermit('session', 'a' * 64, 1), 1024)
        with self.assertRaises(ContractFailure):
            other.claim('a' * 64, 1000)
        for invalid in (0, True, (8 << 20) + 1):
            with self.assertRaises(ContractFailure):
                ProducerGrant(PreparedPermit('session', 'a' * 64, 1), invalid)

    def test_foreign_lease_and_fixed_table_capacity(self):
        grant, other = self.grant(1 << 20), self.grant()
        lease = other.reserve(1)
        with self.assertRaises(ContractFailure):
            grant._release(lease)
        leases = [grant.reserve(0) for _ in range(1024)]
        with self.assertRaises(ContractFailure):
            grant.reserve(0)
        for item in leases:
            item.release()
        self.assertEqual(grant.current, 0)

    def test_two_release_callers_are_idempotent_under_the_grant_lock(self):
        grant = self.grant()
        lease = grant.reserve(1000)
        barrier = threading.Barrier(2)
        original = grant._release

        def simultaneous_release(item):
            # Both callers enter the same release transition before either can
            # acquire the grant lock. No scheduler timing or sleep assumption.
            barrier.wait(timeout=5)
            return original(item)

        with patch.object(grant, '_release', side_effect=simultaneous_release):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(lease.release)
                second = executor.submit(lease.release)
                results = [first.result(timeout=5), second.result(timeout=5)]
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(grant.current, 0)
        self.assertEqual(grant.snapshot()['live_leases'], 0)
        foreign = self.grant()
        with self.assertRaises(ContractFailure):
            foreign._release(lease)  # Released foreign identity still rejects.

    def test_generation_requires_safe_positive_integer(self):
        valid = ProducerGrant(PreparedPermit('session', 'a' * 64, (1 << 53) - 1), 1024)
        valid.claim('a' * 64, 1024)
        self.assertEqual(valid.snapshot()['live_bytes'], 0)
        for generation in (0, -1, True, 1 << 53, (1 << 53) + 1, 1 << 80):
            with self.assertRaises(ContractFailure):
                ProducerGrant(PreparedPermit('session', 'a' * 64, generation), 1024)
