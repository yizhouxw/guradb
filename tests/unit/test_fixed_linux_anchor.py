"""Anchor ownership/minimum tests; patched clocks do not prove Rust/Python IPC."""
from dataclasses import FrozenInstanceError
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

from modules.catalog.cf1a_control import CatalogReadControl
from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_source_scope import SourceScope
from modules.storage import fixed_anchor as anchor
from modules.storage.fixed_parent import ReadParent
from modules.storage.fixed_scope import ReadScope
from tests.storage_support.fixtures import binding, object_ref


class LinuxAnchorTests(unittest.TestCase):
    def setUp(self):
        self.boot, self.session, self.nonce = b'b' * 16, b's' * 16, b'n' * 16
        self.now = 100_000_000_000
        self.started, self.cutoff = self.now, self.now + 10_000_000_000
        self.stopped = False
        self.binding = binding(object_ref(), timeout_ms=10000)
        self.budget = self.binding.value['context']['budget']
        for name, replacement in [('current_boot', lambda: self.boot), ('current_ns', lambda: self.now)]:
            hook = patch.object(anchor, name, side_effect=replacement)
            hook.start()
            self.addCleanup(hook.stop)

    def raw(self, **changes):
        value = dict(magic=b'GLNA', version=2, clock=1, unit=2, boot=self.boot,
                     session=self.session, nonce=self.nonce, generation=1,
                     started=self.started, cutoff=self.cutoff)
        value.update(changes)
        return struct.pack('>4sHBB16s16s16sQQQ', *value.values())

    def token(self, **changes):
        return anchor.TrustedLinuxAnchor(self.raw(**changes), session=self.session,
                                         nonce=self.nonce, generation=1)

    def parent(self, token=None, budget=None):
        return ReadParent.from_linux_anchor(token or self.token(),
                                            self.budget if budget is None else budget,
                                            lambda: self.stopped)

    def refuse(self, code, call):
        with self.assertRaises(ContractFailure) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_original_t0_delay_consumed_once_and_readonly_origin(self):
        token = self.token()
        self.now += 2_000_000_000
        parent = self.parent(token)
        self.assertEqual(parent.started, 100.0)
        self.assertEqual(parent.invoice['elapsed_ms'], 2000)
        self.assertEqual(parent.linux_origin.original_t0_ns, self.started)
        with self.assertRaises(FrozenInstanceError):
            parent.linux_origin.original_t0_ns = self.now
        self.refuse('expired_context', lambda: self.parent(token))
        scope = ReadScope(self.binding, parent=parent)
        self.assertEqual(scope.started, parent.started)
        self.assertLessEqual(scope.deadline, 110.0)
        self.refuse('expired_context', lambda: ReadScope(self.binding, parent=parent))

    def test_bad_header_identity_and_boot_consume_before_failure(self):
        cases = [dict(magic=b'FAIL'), dict(version=1), dict(clock=0), dict(unit=1),
                 dict(session=b'x' * 16), dict(nonce=b'x' * 16), dict(generation=2),
                 dict(boot=b'x' * 16)]
        for change in cases:
            with self.subTest(change=change):
                token = self.token(**change)
                self.refuse('invalid_contract', lambda: self.parent(token))
                self.refuse('expired_context', lambda: self.parent(token))

    def test_exact_length_and_generation_safe_domain(self):
        for raw in [self.raw()[:-1], self.raw() + b'x', bytearray(self.raw())]:
            self.refuse('invalid_contract', lambda: anchor.TrustedLinuxAnchor(
                raw, session=self.session, nonce=self.nonce, generation=1))
        for generation in [0, True, 1 << 53]:
            self.refuse('invalid_contract', lambda: anchor.TrustedLinuxAnchor(
                self.raw(), session=self.session, nonce=self.nonce, generation=generation))
        maximum = (1 << 53) - 1
        token = anchor.TrustedLinuxAnchor(self.raw(generation=maximum), session=self.session,
                                          nonce=self.nonce, generation=maximum)
        self.assertEqual(self.parent(token).linux_origin.generation, maximum)
        self.refuse('invalid_contract', lambda: ReadParent.from_linux_anchor({}, self.budget, lambda: False))

    def test_future_expired_and_cancelled_cannot_reset_import(self):
        for change, code in [(dict(started=self.now + 1), 'invalid_contract'),
                             (dict(cutoff=self.now), 'invalid_contract'),
                             (dict(started=self.now - 10, cutoff=self.now), 'deadline')]:
            token = self.token(**change)
            self.refuse(code, lambda: self.parent(token))
            self.refuse('expired_context', lambda: self.parent(token))
        token = self.token()
        self.stopped = True
        self.refuse('cancelled', lambda: self.parent(token))
        self.stopped = False
        self.refuse('expired_context', lambda: self.parent(token))

    def test_bad_budget_also_consumes_and_good_budget_is_minimum(self):
        token = self.token()
        self.refuse('invalid_contract', lambda: self.parent(token, {**self.budget, 'concurrency': 0}))
        self.refuse('expired_context', lambda: self.parent(token))
        budget = {**self.budget, 'object_requests': 1, 'top_k': 1, 'candidates': 1}
        scope = ReadScope(self.binding, parent=self.parent(budget=budget))
        self.assertEqual(scope.budget['object_requests'], 1)
        self.assertEqual(scope.budget['top_k'], 1)

    def test_u64_ns_above_safeint_and_seconds_projection_never_extends(self):
        self.started = (1 << 53) + 999_999
        self.now = self.started + 1_000_000
        self.cutoff = self.started + 2_000_000_000
        parent = self.parent()
        self.assertEqual(parent.linux_origin.original_t0_ns, self.started)
        self.assertEqual(parent.invoice['elapsed_ms'], 1)
        for ns in [1, 999_999_999, (1 << 53) + 1, (1 << 64) - 1]:
            value = anchor.seconds_floor(ns)
            numerator, denominator = value.as_integer_ratio()
            self.assertLessEqual(numerator * 1_000_000_000, ns * denominator)
        self.now = self.cutoff
        self.refuse('deadline', parent.checkpoint)

    def test_fresh_boot_rollback_and_cancel_after_admission(self):
        parent = self.parent()
        self.now += 1
        parent.checkpoint()
        self.now -= 2
        self.refuse('invalid_contract', parent.checkpoint)
        self.now += 3
        self.boot = b'c' * 16
        self.refuse('invalid_contract', parent.checkpoint)
        self.boot = b'b' * 16
        self.stopped = True
        self.refuse('cancelled', parent.checkpoint)

    def test_attach_ttl_uses_fresh_now_not_old_t0_and_never_extends(self):
        parent = self.parent()
        self.now += 2_000_000_000
        # Trusted binding fixture has an unchanged absolute wall deadline;
        # shorten its remaining duration using the trusted wall observation only.
        parent.wall_ms = lambda: self.binding.value['context']['deadline_unix_ms'] - 1000
        scope = ReadScope(self.binding, parent=parent)
        self.assertLessEqual(parent.deadline, 103.0)
        self.assertGreater(parent.deadline, 102.0)
        self.assertLessEqual(scope.effective_deadline(), parent.deadline)
        self.assertEqual(parent.linux_origin.absolute_cutoff_ns, 110_000_000_000)
        self.now = 103_000_000_000
        self.refuse('deadline', scope.check)

    def test_short_operation_controls_scope_pg_and_both_io_slacks(self):
        parent = self.parent()
        scope = SourceScope(self.binding, parent=parent)
        original = parent.deadline
        with parent.active_operation(1, 4, self.now + 400_000_000):
            with scope.batch():
                self.assertLessEqual(scope.effective_deadline(), 100.4)
                self.now += 151_000_000
                self.refuse('deadline', lambda: scope.request(1))
                self.now += 50_000_000
                self.refuse('deadline', lambda: scope.check(slack=.2))
        self.assertEqual(parent.deadline, original)
        self.assertGreater(parent.checkpoint(), 109)
        self.refuse('invalid_contract', lambda: self.enter_operation(parent, 1, 5))
        self.refuse('invalid_contract', lambda: self.enter_operation(parent, 2, 4))

    def enter_operation(self, parent, sequence, pg_sequence):
        with parent.active_operation(sequence, pg_sequence, self.cutoff):
            pass

    def test_operation_cannot_extend_query_and_failed_slot_is_released(self):
        parent = self.parent()
        with parent.active_operation(1, 1, self.cutoff + 10_000_000_000):
            self.assertLessEqual(parent.checkpoint(), parent.deadline)
            self.refuse('resource_limit', lambda: self.enter_operation(parent, 2, 2))
        with self.assertRaises(ContractFailure):
            with parent.active_operation(2, 2, self.now):
                self.fail('expired operation entered')
        self.enter_operation(parent, 3, 3)
        self.now = self.cutoff
        self.refuse('deadline', parent.checkpoint)

    def test_parent_pg_observation_survives_failed_scope_admission(self):
        parent = self.parent()
        control = CatalogReadControl(parent.checkpoint, parent.monotonic)
        parent.catalog(control)
        control.mark('connect_attempt')
        self.stopped = True
        self.refuse('cancelled', lambda: ReadScope(self.binding, parent=parent))
        self.stopped = False
        self.assertEqual(parent.invoice['admission'], 'rejected_before_object_execution')
        self.assertIsNone(parent.invoice['execution'])
        self.assertEqual(parent.invoice['catalog']['counts'], {'connect_attempt': 1})

    def test_concurrent_import_has_exactly_one_parent(self):
        token, barrier, outcomes = self.token(), threading.Barrier(2), []
        def consume():
            barrier.wait()
            try:
                outcomes.append(self.parent(token))
            except ContractFailure as failure:
                outcomes.append(failure.code)
        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sum(type(value) is ReadParent for value in outcomes), 1)
        self.assertEqual(outcomes.count('expired_context'), 1)


class FdDomainTests(unittest.TestCase):
    """New FD cases reuse setup helpers without duplicating old test discovery."""
    setUp = LinuxAnchorTests.setUp
    raw = LinuxAnchorTests.raw
    token = LinuxAnchorTests.token
    parent = LinuxAnchorTests.parent
    refuse = LinuxAnchorTests.refuse
    def test_independent_pg_source_and_close_reference_zero(self):
        parent = self.parent()
        started = parent.linux_origin.original_t0_ns
        for kind, sequence, pg_sequence in ((1, 1, 1), (2, 2, 2), (3, 1, 3),
                                             (2, 4, 4), (4, 2, 5), (5, 3, 0), (6, 6, 6)):
            with parent.fd_operation(kind, sequence, pg_sequence, self.cutoff):
                self.assertEqual(parent.linux_origin.original_t0_ns, started)
        with self.assertRaises(ContractFailure):
            with parent.fd_operation(6, 6, 6, self.cutoff):
                pass

    def test_fd_cutoff_min_cancel_and_same_active_operation(self):
        parent = self.parent()
        cutoff = self.now + 100_000_000
        with parent.fd_operation(1, 1, 1, cutoff):
            self.assertLessEqual(parent.effective_deadline(), anchor.seconds_floor(cutoff))
            with self.assertRaises(ContractFailure):
                with parent.fd_operation(2, 2, 2, self.cutoff):
                    pass
            self.now = cutoff
            self.refuse('deadline', parent.checkpoint)
        self.now = self.started
        self.stopped = True
        self.refuse('cancelled', lambda: parent.fd_operation(2, 2, 2, self.cutoff).__enter__())

    def test_fd_and_legacy_cannot_mix_either_direction(self):
        for first in ('fd', 'legacy'):
            parent = self.parent()
            with (parent.fd_operation(1, 1, 1, self.cutoff) if first == 'fd'
                  else parent.active_operation(1, 1, self.cutoff)):
                pass
            with self.assertRaises(ContractFailure):
                with (parent.active_operation(2, 2, self.cutoff) if first == 'fd'
                      else parent.fd_operation(2, 2, 2, self.cutoff)):
                    pass

    def test_fd_invalid_pg_ticket_and_safe_sequence_are_rejected(self):
        for kind, sequence, pg in ((1, 1, 2), (3, 1, 0), (5, 1, 1), (2, True, 1),
                                   (4, 1 << 53, 2), (0, 1, 1)):
            parent = self.parent()
            with self.assertRaises(ContractFailure):
                with parent.fd_operation(kind, sequence, pg, self.cutoff):
                    pass


class ActualPythonLinuxClockTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux' and struct.calcsize('P') == 8, 'Linux64 only')
    def test_actual_python_boot_clock_import_is_not_cross_process_proof(self):
        boot, before = anchor.current_boot(), anchor.current_ns()
        raw = struct.pack('>4sHBB16s16s16sQQQ', b'GLNA', 2, 1, 2, boot,
                          b's' * 16, b'n' * 16, 1, before, before + 1_000_000_000)
        token = anchor.TrustedLinuxAnchor(raw, session=b's' * 16, nonce=b'n' * 16, generation=1)
        bound = binding(object_ref(), timeout_ms=10000)
        parent = ReadParent.from_linux_anchor(token, bound.value['context']['budget'], lambda: False)
        self.assertEqual(parent.linux_origin.original_t0_ns, before)
        self.assertLessEqual(before, anchor.current_ns())
        self.assertLessEqual(parent.checkpoint(), anchor.seconds_floor(before + 1_000_000_000))


if __name__ == '__main__':
    unittest.main()
