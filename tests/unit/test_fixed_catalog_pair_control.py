"""Child deadline SQL semantics with SQLite; no PG pause/remote stop evidence."""
from contextlib import contextmanager
import time
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from tests.unit import test_cf1a_catalog_controlled as fixture
from tests.catalog_support.fixed_fixture import request


class PairChildControlTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ControlledReadTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_child_reauthorize_uses_same_control_and_original_issued_binding(self):
        reads = self.case.reader()
        bound = reads.bind(request(self.case.principal))
        original = self.case.catalog.store.transaction
        seen = []
        @contextmanager
        def transaction(deadline, control):
            seen.append((deadline, control))
            with original(deadline, control) as connection:
                yield connection
        child = time.monotonic() + .2
        with patch.object(self.case.catalog.store, 'transaction', side_effect=transaction):
            self.assertEqual(reads.reauthorize(bound, operation_deadline=child), 2)
        self.assertEqual(seen, [(child, reads.control)])

    def test_expired_and_nonfinite_child_do_not_open_transaction(self):
        for child, expected in ((time.monotonic() - 1, 'deadline'), (float('nan'), 'invalid_contract')):
            reads = self.case.reader()
            bound = reads.bind(request(self.case.principal, query='child-' + expected))
            with patch.object(self.case.catalog.store, 'transaction') as transaction:
                with self.assertRaises(ContractFailure) as caught:
                    reads.reauthorize(bound, operation_deadline=child)
                self.assertEqual(caught.exception.code, expected)
                transaction.assert_not_called()
            with self.assertRaises(ContractFailure) as caught:
                reads.reauthorize(bound)
            self.assertEqual(caught.exception.code, 'unauthorized')

    def test_refusal_mismatch_retains_exact_expected_and_observed_codes(self):
        from tests.source_support.fixed_catalog_pair_faults import refused, RefusalMismatch
        def denied():
            raise ContractFailure('unauthorized', 'grant absent')
        with self.assertRaises(RefusalMismatch) as caught:
            refused(denied, 'revoked')
        self.assertEqual((caught.exception.expected, caught.exception.observed), ('revoked', 'unauthorized'))
        with self.assertRaises(RefusalMismatch) as caught:
            refused(lambda: None, 'deadline')
        self.assertEqual((caught.exception.expected, caught.exception.observed), ('deadline', 'success'))

    def test_child_cannot_extend_parent(self):
        reads = self.case.reader()
        bound = reads.bind(request(self.case.principal))
        original = self.case.catalog.store.transaction
        seen = []
        @contextmanager
        def transaction(deadline, control):
            seen.append(deadline)
            with original(deadline, control) as connection:
                yield connection
        before = reads.control.limit(5)
        with patch.object(self.case.catalog.store, 'transaction', side_effect=transaction):
            reads.reauthorize(bound, operation_deadline=time.monotonic() + 100)
        self.assertEqual(len(seen), 1)
        self.assertLessEqual(seen[0], before)
        self.assertGreater(seen[0], time.monotonic())


if __name__ == '__main__':
    unittest.main()
