"""Parent control/transport boundaries with no sockets or PG process."""
from dataclasses import FrozenInstanceError
import math
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from psycopg import pq
from modules.catalog import cf1a_pg
from modules.catalog.cf1a_control import CatalogReadControl, finite
from modules.catalog.cf1a_store import CatalogStore, CommitUnknown
from modules.common.cf1a_primitives import ContractFailure


class ControlTests(unittest.TestCase):
    def fail(self, code, callback):
        with self.assertRaises(ContractFailure) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_original_parent_and_child_limit_never_restart(self):
        now, child = [10.0], [11.0]
        control = CatalogReadControl(lambda: child[0], lambda: now[0])
        now[0] = 10.8
        self.assertAlmostEqual(control.limit(5), 11)
        self.assertAlmostEqual(control.remaining(20), .2)
        child[0] = 10.9
        self.assertAlmostEqual(control.remaining(11), .1)
        now[0] = 10.91
        self.fail('deadline', lambda: control.remaining(11))
        with self.assertRaises(FrozenInstanceError):
            control.checkpoint = lambda: 100

    def test_fresh_clock_after_parent_callback_and_cancel_unavailable(self):
        now = [0.0]
        def slow():
            now[0] = 2
            return 1
        control = CatalogReadControl(slow, lambda: now[0])
        self.fail('deadline', lambda: control.limit(5))
        self.fail('deadline', lambda: control.remaining(5))
        for callback, code in [(Mock(side_effect=OSError('private')), 'cancelled'),
                               (Mock(side_effect=ContractFailure('cancelled', 'stop')), 'cancelled'),
                               (lambda: True, 'invalid_contract')]:
            self.fail(code, lambda: CatalogReadControl(callback, lambda: 0).limit(1))
        self.fail('invalid_contract', lambda: CatalogReadControl(None, lambda: 0))
        self.fail('cancelled', lambda: CatalogReadControl(lambda: 1,
                  Mock(side_effect=OSError('private clock detail'))).limit(1))
        for value in (True, -1, math.inf, math.nan):
            self.fail('invalid_contract', lambda: finite(value))

    def test_invoice_is_bounded_and_no_native_or_object_zero_claim(self):
        control = CatalogReadControl(lambda: 1, lambda: 0)
        for _ in range(150):
            control.mark('wait', time.monotonic())
        invoice = control.invoice
        self.assertEqual(invoice['counts']['wait'], 150)
        self.assertEqual(len(invoice['events']), 128)
        self.assertEqual(invoice['events_dropped'], 22)
        self.assertGreaterEqual(invoice['seconds']['wait'], 0)
        self.assertIsNone(invoice['pg_native_memory_bytes'])
        self.assertIsNone(invoice['object_requests'])
        invoice['counts']['wait'] = 0
        self.assertEqual(control.invoice['counts']['wait'], 150)
        self.fail('invalid_contract', lambda: control.mark('unbounded-caller-text'))

    def test_selector_checks_parent_after_wait_and_caps_poll(self):
        now = [0.0]
        control = CatalogReadControl(lambda: .1, lambda: now[0])
        selector = Mock()
        selector.__enter__ = Mock(return_value=selector)
        selector.__exit__ = Mock(return_value=False)
        def wait(timeout):
            self.assertLessEqual(timeout, .01)
            now[0] = .101
            return []
        selector.select.side_effect = wait
        with patch.object(cf1a_pg.selectors, 'DefaultSelector', return_value=selector):
            self.fail('deadline', lambda: cf1a_pg._ready(3, 1, 10, control))
        self.assertEqual(control.invoice['counts']['wait'], 1)

    def test_connect_parent_cancel_closes_startup_without_success(self):
        cancelled = [False]
        def checkpoint():
            if cancelled[0]:
                raise ContractFailure('cancelled', 'stop')
            return 10
        pgconn = Mock()
        pgconn.connect_poll.side_effect = lambda: cancelled.__setitem__(0, True) or pq.PollingStatus.READING
        stub = SimpleNamespace(PGconn=Mock(connect_start=Mock(return_value=pgconn)), PollingStatus=pq.PollingStatus)
        control = CatalogReadControl(checkpoint, lambda: 0)
        with patch.object(cf1a_pg, 'pq', stub):
            self.fail('cancelled', lambda: cf1a_pg.connect('fixture', 10, control))
        pgconn.finish.assert_called_once()
        self.assertEqual(control.invoice['counts']['connect_attempt'], 1)
        self.assertEqual(control.invoice['counts']['connect_failure'], 1)
        self.assertNotIn('connect_success', control.invoice['counts'])

    def test_generator_not_advanced_when_parent_cancelled_and_tail_closes(self):
        cancelled, advanced = [True], []
        def checkpoint():
            if cancelled[0]:
                raise ContractFailure('cancelled', 'stop')
            return 10
        control = CatalogReadControl(checkpoint, lambda: 0)
        connection = cf1a_pg.DeadlineConnection(Mock(), 10, control)
        connection.close = Mock()
        def generator():
            advanced.append('sent')
            yield 1
        with patch.object(cf1a_pg.time, 'monotonic', return_value=0):
            self.fail('cancelled', lambda: connection.wait(generator()))
        self.assertEqual(advanced, [])
        self.assertTrue(connection.close.called)
        cancelled[0] = False
        def complete():
            cancelled[0] = True
            if False:
                yield
            return 'must not escape'
        with patch.object(cf1a_pg.time, 'monotonic', return_value=0):
            self.fail('cancelled', lambda: connection.wait(complete()))
        self.assertEqual(control.invoice['counts']['sql_failure'], 2)
        connection.pgconn.status = pq.ConnStatus.BAD

    def test_store_commit_cancel_stays_unknown_precommit_cancel_keeps_code(self):
        store = CatalogStore('host=127.0.0.1 port=5432 dbname=fixture user=fixture', Mock())
        cancelled = [False]
        def checkpoint():
            if cancelled[0]:
                raise ContractFailure('cancelled', 'stop')
            return 10
        control = CatalogReadControl(checkpoint, lambda: 0)
        connection = Mock()
        with patch('modules.catalog.cf1a_store.connect', return_value=connection):
            with self.assertRaises(ContractFailure) as caught:
                with store.transaction(10, control):
                    cancelled[0] = True
            self.assertEqual(caught.exception.code, 'cancelled')
            connection.commit.assert_not_called()
            cancelled[0] = False
            connection.commit.side_effect = lambda: cancelled.__setitem__(0, True)
            with self.assertRaises(CommitUnknown):
                with store.transaction(10, control):
                    pass
            self.assertEqual(connection.phase, 'commit')
            self.assertEqual(connection.commit.call_count, 1)
            self.assertEqual(connection.close.call_count, 2)


if __name__ == '__main__':
    unittest.main()
