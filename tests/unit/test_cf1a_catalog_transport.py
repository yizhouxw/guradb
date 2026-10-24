"""Pure public nonblocking PG boundary tests; no sockets/services are started here."""
from unittest.mock import MagicMock, Mock, patch
from types import SimpleNamespace
import unittest
import psycopg
from psycopg import pq
from modules.catalog import cf1a_pg
from modules.catalog.cf1a_store import CatalogStore, CommitUnknown
from modules.common.cf1a_primitives import ContractFailure


class CatalogTransportUnits(unittest.TestCase):
    def fail(self, callback, code=None):
        with self.assertRaises(ContractFailure) as caught:
            callback()
        if code:
            self.assertEqual(caught.exception.code, code)

    def test_dsn_and_single_monotonic_deadline(self):
        normalized = cf1a_pg.normalized_dsn('host=127.0.0.1 port=5432 dbname=fixture user=fixture')
        self.assertIn('sslmode=disable', normalized)
        for dsn in ('garbage conninfo', 'host=localhost port=5432 dbname=x user=x',
                    'host=127.0.0.1 port=0 dbname=x user=x',
                    'host=127.0.0.1 port=5432 dbname=x user=x sslmode=require',
                    'host=127.0.0.1 port=5432 dbname=x user=x connect_timeout=2'):
            self.fail(lambda: cf1a_pg.normalized_dsn(dsn))
        with patch.object(cf1a_pg.time, 'monotonic', return_value=10):
            self.assertEqual(cf1a_pg.remaining(11), 1)
            self.fail(lambda: cf1a_pg.remaining(10), 'deadline')

    def test_selector_empty_ready_and_invalid_state(self):
        selector = MagicMock()
        selector.__enter__.return_value = selector
        with patch.object(cf1a_pg.selectors, 'DefaultSelector', return_value=selector), \
                patch.object(cf1a_pg.time, 'monotonic', return_value=0):
            selector.select.return_value = []
            self.assertEqual(cf1a_pg._ready(3, 1, 1), 0)
            selector.select.return_value = [(None, 2)]
            self.assertEqual(cf1a_pg._ready(3, 2, 1), 2)
            self.fail(lambda: cf1a_pg._ready(3, 0, 1))

    def test_connect_poll_states_success_error_and_cleanup(self):
        pgconn = Mock()
        pgconn.socket = 3
        pgconn.connect_poll.side_effect = [pq.PollingStatus.READING, pq.PollingStatus.WRITING, pq.PollingStatus.OK]
        pq_stub = SimpleNamespace(PGconn=Mock(connect_start=Mock(return_value=pgconn)), PollingStatus=pq.PollingStatus)
        with patch.object(cf1a_pg, 'pq', pq_stub), \
                patch.object(cf1a_pg, '_ready') as ready, patch.object(cf1a_pg, 'remaining', return_value=1), \
                patch.object(cf1a_pg, 'DeadlineConnection', return_value='connection'):
            self.assertEqual(cf1a_pg.connect('dsn', 1), 'connection')
            self.assertEqual(ready.call_count, 2)
            self.assertEqual(pgconn.nonblocking, 1)
        pgconn.connect_poll.side_effect = [pq.PollingStatus.FAILED]
        with patch.object(cf1a_pg, 'pq', pq_stub), \
                patch.object(cf1a_pg, 'remaining', return_value=1):
            self.fail(lambda: cf1a_pg.connect('dsn', 1), 'backend_unavailable')
            pgconn.finish.assert_called()

    def test_connection_wait_generator_success_error_and_expired_cleanup(self):
        pgconn = Mock()
        connection = cf1a_pg.DeadlineConnection(pgconn, 10)
        connection.close = Mock()
        def generator():
            result = yield 1
            self.assertEqual(result, 1)
            return 'complete'
        with patch.object(cf1a_pg, '_ready', return_value=1), patch.object(cf1a_pg, 'remaining', return_value=1), \
                patch.object(cf1a_pg.time, 'monotonic', return_value=0):
            self.assertEqual(connection.wait(generator()), 'complete')
        def invalid():
            yield 1
            raise ValueError('fault generator')
        with patch.object(cf1a_pg, '_ready', return_value=1), patch.object(cf1a_pg.time, 'monotonic', return_value=11):
            with self.assertRaises(ValueError): connection.wait(invalid())
        self.assertTrue(connection.close.called)
        connection.pgconn.status = pq.ConnStatus.BAD

    def test_store_commit_boundaries_never_retry_unknown(self):
        store = CatalogStore('host=127.0.0.1 port=5432 dbname=fixture user=fixture', Mock())
        conn = Mock()
        with patch('modules.catalog.cf1a_store.connect', return_value=conn), \
                patch('modules.catalog.cf1a_store.remaining', return_value=1):
            with store.transaction(1): pass
            conn.commit.assert_called_once()
            conn.close.assert_called_once()
            conn.reset_mock()
            conn.commit.side_effect = OSError('commit response lost')
            with self.assertRaises(CommitUnknown):
                with store.transaction(1): pass
            conn.commit.assert_called_once()
            conn.close.assert_called_once()
        for exception, code in ((psycopg.errors.QueryCanceled(), 'deadline'),
                                (psycopg.errors.LockNotAvailable(), 'deadline'),
                                (OSError('connection'), 'backend_unavailable'),
                                (ContractFailure('unauthorized', 'denied'), 'unauthorized')):
            with patch('modules.catalog.cf1a_store.connect', side_effect=exception):
                def operation():
                    with store.transaction(1): pass
                self.fail(operation, code)
        with patch.object(store, 'transaction', side_effect=CommitUnknown()):
            self.fail(store.initialize, 'outcome_unknown')

    def test_commit_interrupt_and_cleanup_failure_preserve_unknown(self):
        store = CatalogStore('host=127.0.0.1 port=5432 dbname=fixture user=fixture', Mock())
        for interruption in (KeyboardInterrupt, SystemExit):
            for after_effect in (False, True):
                conn = Mock()
                effects = []
                def commit():
                    if after_effect:
                        effects.append('committed')
                    raise interruption()
                conn.commit.side_effect = commit
                with patch('modules.catalog.cf1a_store.connect', return_value=conn), \
                        patch('modules.catalog.cf1a_store.remaining', return_value=1):
                    with self.assertRaises(CommitUnknown):
                        with store.transaction(1):
                            pass
                self.assertEqual(effects, ['committed'] if after_effect else [])
                conn.commit.assert_called_once()
                conn.close.assert_called_once()
        for failure in (KeyboardInterrupt(), OSError('cleanup failed')):
            conn = Mock()
            conn.close.side_effect = failure
            with patch('modules.catalog.cf1a_store.connect', return_value=conn), \
                    patch('modules.catalog.cf1a_store.remaining', return_value=1):
                with self.assertRaises(CommitUnknown):
                    with store.transaction(1):
                        pass
                conn.commit.assert_called_once()
                with self.assertRaises(KeyboardInterrupt):
                    with store.transaction(1):
                        raise KeyboardInterrupt()
                conn.commit.assert_called_once()
