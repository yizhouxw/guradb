"""Cooperative parent unit checks; no PG/S3 or remote cancellation claims."""
import time
import unittest
from unittest.mock import patch

from modules.catalog.cf1a_control import CatalogReadControl
from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_source_scope import SourceScope
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_parent import ControlledAuthority, ReadParent
from modules.storage.fixed_scope import ReadScope
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
from tests.storage_support.fixtures import binding, object_ref


class FixedParentTests(unittest.TestCase):
    def setUp(self):
        self.binding = binding(object_ref(), timeout_ms=10000)
        self.now = [100.0]
        self.wall = [time.time_ns() // 1_000_000]
        self.stopped = [False]
        self.budget = self.binding.value['context']['budget']

    def parent(self, timeout=5000):
        return ReadParent(timeout, self.budget, lambda: self.stopped[0],
            monotonic=lambda: self.now[0], wall_ms=lambda: self.wall[0])

    def refuse(self, code, callback):
        with self.assertRaises(ContractFailure) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_prebind_time_attach_once_and_host_budget_min(self):
        parent = self.parent()
        parent._budget['object_requests'] = 1
        self.now[0] += 2
        scope = ReadScope(self.binding, parent=parent)
        self.assertEqual((scope.started, scope.deadline), (100, 105))
        self.assertEqual(scope.budget['object_requests'], 1)
        scope.request(1)
        self.refuse('resource_limit', lambda: scope.request(1))
        self.refuse('expired_context', lambda: ReadScope(self.binding, parent=parent))
        self.assertEqual(parent.invoice['execution']['object_requests'], 1)
        self.now[0] = 105
        self.refuse('deadline', scope.check)

    def test_failed_attach_consumed_cancel_and_bad_clock(self):
        parent = self.parent()
        self.stopped[0] = True
        self.refuse('cancelled', lambda: ReadScope(self.binding, parent=parent))
        self.stopped[0] = False
        self.refuse('expired_context', lambda: ReadScope(self.binding, parent=parent))
        self.now[0] = float('nan')
        self.refuse('invalid_contract', lambda: self.parent())

    def test_failed_admission_invoice_preserves_pg_and_no_object_execution(self):
        for reason in ('cancel', 'deadline', 'budget'):
            self.now[0], self.stopped[0] = 100, False
            parent = self.parent()
            control = CatalogReadControl(parent.checkpoint, parent.monotonic)
            parent.catalog(control)
            control.mark('connect_attempt')
            if reason == 'cancel':
                self.stopped[0] = True
            elif reason == 'deadline':
                self.now[0] = 105
            else:
                parent._budget.pop('concurrency')
            self.refuse({'cancel': 'cancelled', 'deadline': 'deadline',
                         'budget': 'invalid_contract'}[reason],
                        lambda: ReadScope(self.binding, parent=parent))
            invoice = parent.invoice
            self.assertEqual(invoice['admission'], 'rejected_before_object_execution')
            self.assertIsNone(invoice['execution'])
            self.assertEqual(invoice['catalog']['counts'], {'connect_attempt': 1})
            self.refuse('expired_context', lambda: ReadScope(self.binding, parent=parent))
        self.budget['concurrency'] = 0
        self.refuse('invalid_contract', self.parent)

    def test_host_budget_closed_positive_safe_and_cross_min(self):
        for key, value in [('concurrency', 0), ('memory_bytes', True),
                           ('object_requests', 1 << 53), ('top_k', self.budget['candidates'] + 1)]:
            budget = {**self.budget, key: value}
            self.refuse('invalid_contract', lambda: ReadParent(1000, budget))
        for budget in ({key: value for key, value in self.budget.items() if key != 'concurrency'},
                       {**self.budget, 'other': 1}):
            self.refuse('invalid_contract', lambda: ReadParent(1000, budget))
        parent = self.parent()
        parent._budget.update(top_k=1, candidates=1)
        scope = ReadScope(self.binding, parent=parent)
        self.assertLessEqual(scope.budget['top_k'], scope.budget['candidates'])
        self.assertEqual(scope.budget['candidates'], 1)

    def test_page_child_does_not_replace_query_or_cohort(self):
        parent = self.parent(9000)
        scope = SourceScope(self.binding, parent=parent)
        with scope.batch():
            self.assertEqual(scope.effective_deadline(), 101)
        self.now[0] = 100.5
        with scope.batch():
            self.assertEqual(scope.effective_deadline(), 101.5)
        self.assertEqual((scope.deadline, scope._cohort_deadline), (109, 105))
        self.now[0] = 104.5
        with scope.batch():
            self.assertEqual(scope.effective_deadline(), 105)
        self.now[0] = 105
        self.refuse('deadline', scope.effective_deadline)

    def test_explicit_authority_fresh_clock_and_single_catalog_invoice(self):
        parent = self.parent()
        control = CatalogReadControl(parent.checkpoint, parent.monotonic)
        parent.catalog(control)
        self.refuse('invalid_contract', lambda: parent.catalog(control))
        scope = SourceScope(self.binding, parent=parent)
        calls = []
        class Reads:
            def reauthorize(inner, issued, *, operation_deadline):
                calls.append((issued, operation_deadline))
                self.now[0] += 1.1
                control.mark('sql_attempt')
                return 1
        authority = ControlledAuthority(parent, Reads().reauthorize)
        with scope.batch():
            self.refuse('deadline', lambda: authority.authorize(scope))
        self.assertEqual(calls, [(self.binding, 101)])
        self.assertEqual(parent.invoice['catalog']['counts'], {'sql_attempt': 1})
        self.assertEqual(parent.invoice['execution']['object_requests'], 0)
        self.refuse('invalid_contract', lambda: ControlledAuthority(parent, lambda _: 1))

    def test_network_slot_is_explicit_and_exclusive(self):
        parent = self.parent()
        scope = ReadScope(self.binding, parent=parent)
        class Reads:
            def reauthorize(inner, issued, *, operation_deadline):
                return issued.value['context']['auth']['policy_epoch']
        authority = ControlledAuthority(parent, Reads().reauthorize)
        backend = FixedBackend('local_s3', 'm0-data', 'http://127.0.0.1:1',
                               CredentialSnapshot('key', 'secret'), True)
        config = {'local_s3': backend}
        objects = FixedObjects(scope, config, controlled=authority)
        objects.authorize()
        self.refuse('invalid_contract', lambda: FixedObjects(scope, config, lambda _: 1, controlled=authority))
        self.refuse('invalid_contract', lambda: FixedObjects(scope, config))
        self.stopped[0] = True
        self.refuse('cancelled', objects.authorize)


if __name__ == '__main__':
    unittest.main()
