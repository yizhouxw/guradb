"""Controlled read SQL semantics via SQLite; not real PG wait/lock evidence."""
from contextlib import contextmanager
import time
import unittest
from unittest.mock import patch

from modules.catalog.cf1a_admin import AdminOperations
from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_binding import Bindings
from modules.catalog.cf1a_codec import contract
from modules.catalog.cf1a_control import CatalogReadControl
from modules.catalog.cf1a_mutation import Mutations
from modules.catalog.cf1a_pg import remaining
from modules.catalog.cf1a_store import CatalogStore
from modules.common.cf1a_primitives import ContractFailure
from tests.catalog_support.fixed_fixture import authorization, configure, intents, new_catalog, request, target
from tests.catalog_support.sqlite_unit import Cursor, install


class UnitPg:
    def __init__(self, source, deadline, control):
        self.source, self.deadline, self.control = source, deadline, control

    def execute(self, sql, parameters=()):
        remaining(self.deadline, self.control)
        if isinstance(sql, str) and sql.startswith('SELECT set_config'):
            self.source.db.execute('BEGIN')
            return Cursor([])
        result = self.source.execute(sql, parameters)
        remaining(self.deadline, self.control)
        return result

    def commit(self):
        self.source.commit()

    def close(self):
        if self.source.db.in_transaction:
            self.source.db.rollback()


class ControlledReadTests(unittest.TestCase):
    def setUp(self):
        self.wall = {'ms': time.time_ns() // 1_000_000}
        self.catalog, self.authority, self.principal, _ = new_catalog(
            'host=127.0.0.1 port=5432 dbname=fixture user=fixture', self.wall['ms'])
        sqlite = install(self.catalog, self.wall)
        self.connection = sqlite.connection
        self.addCleanup(self.connection.close)
        self.catalog.store = CatalogStore('host=127.0.0.1 port=5432 dbname=fixture user=fixture', self.authority)
        self.catalog.admin = AdminOperations(self.catalog.store)
        self.catalog.mutations = Mutations(self.catalog.store)
        self.catalog.bindings = Bindings(self.catalog.store)
        patcher = patch('modules.catalog.cf1a_store.connect', side_effect=lambda dsn, deadline, control=None:
                        UnitPg(self.connection, deadline, control))
        patcher.start()
        self.addCleanup(patcher.stop)
        configure(self.catalog, self.principal, self.wall['ms'])
        self.target = target(self.wall['ms'])
        self.authority.allow(self.target)
        reg, pub = intents(self.target)
        port = self.catalog.port(self.principal)
        port.register(reg, authorization(self.principal, self.wall['ms']), self.target)
        port.publish(pub, authorization(self.principal, self.wall['ms']), self.target)

    def control(self, seconds=1):
        end = time.monotonic() + seconds
        return CatalogReadControl(lambda: end, time.monotonic)

    def reader(self):
        end = time.monotonic() + 1
        return self.catalog.controlled_reads(self.principal, CatalogReadControl(lambda: end, time.monotonic))

    def query(self, text='SELECT * FROM gura_cf1a.queries', parameters=()):
        return self.connection.execute(text, parameters).fetchall()

    def state(self):
        return self.query('SELECT generation,policy_epoch,metadata_bytes FROM gura_cf1a.datasets'), self.query()

    def fail(self, code, callback):
        with self.assertRaises(ContractFailure) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_parent_prebind_elapsed_wire_ttl_and_same_binding_reauth(self):
        now, end = [0.75], 1.0
        control = CatalogReadControl(lambda: end, lambda: now[0])
        reads = self.catalog.controlled_reads(self.principal, control)
        binding = reads.bind(request(self.principal, timeout_ms=1000))
        context = binding.value['context']
        self.assertEqual(context['remaining_ttl_ms'], 250)
        self.assertEqual(context['deadline_unix_ms'] - context['bound_at_unix_ms'], 250)
        self.assertEqual(reads.reauthorize(binding), 2)
        self.fail('expired_context', lambda: reads.bind(request(self.principal)))
        self.assertEqual(len(self.query()), 1)
        reads.release_pin(binding, self.control())
        self.assertTrue(self.query()[0]['released'])
        self.fail('unauthorized', lambda: reads.reauthorize(binding))

    def test_unknown_bind_latches_and_found_cleanup_after_revoke(self):
        reads, req = self.reader(), request(self.principal)
        original = self.catalog.store.commit
        def lost(conn):
            original(conn)
            raise OSError('response lost')
        with patch.object(self.catalog.store, 'commit', side_effect=lost):
            self.fail('outcome_unknown', lambda: reads.bind(req))
        before = self.state()
        self.fail('outcome_unknown', lambda: reads.bind(req))
        self.assertEqual(self.state(), before)
        self.catalog.revoke(self.principal, 'revoke-c1', 'dataset-1',
                            self.principal.subject_id, self.principal.delegation_ref)
        before = self.state()
        result = reads.close_bind_request(req, self.control())
        self.assertEqual((result.state, result.request_sha256), ('released', req.sha256))
        self.assertEqual(self.query()[0]['binding_sha256'], result.binding_sha256)
        self.assertTrue(self.query()[0]['released'])
        self.assertEqual(self.state()[0], before[0])
        self.assertEqual(reads.close_bind_request(req, self.control()), result)

    def test_found_cleanup_after_expiry_and_unknown_cleanup_commit(self):
        reads, req = self.reader(), request(self.principal, timeout_ms=100)
        binding = reads.bind(req)
        self.wall['ms'] = binding.value['context']['deadline_unix_ms'] + 1
        original = self.catalog.store.commit
        def lost(conn):
            original(conn)
            raise KeyboardInterrupt()
        with patch.object(self.catalog.store, 'commit', side_effect=lost):
            result = reads.close_bind_request(req, self.control())
        self.assertEqual(result.state, 'outcome_unknown')
        self.assertTrue(self.query()[0]['released'])
        self.assertEqual(reads.close_bind_request(req, self.control()).state, 'released')

    def test_absent_is_unconfirmed_and_does_not_exclude_legacy_delayed_bind(self):
        reads, req = self.reader(), request(self.principal)
        before = self.state()
        self.assertEqual(reads.close_bind_request(req, self.control()).state, 'cleanup_unconfirmed')
        self.assertEqual(self.state(), before)
        self.fail('expired_context', lambda: reads.bind(req))
        # This is the explicit C2 gap, not a newly certified retry policy.
        late = self.catalog.port(self.principal).bind(req)
        self.assertEqual(late.value['context']['query_id'], req.value['query_id'])
        self.assertEqual(reads.close_bind_request(req, self.control()).state, 'released')

    def test_cleanup_wrong_request_principal_and_control_cannot_touch_query(self):
        reads, req = self.reader(), request(self.principal)
        bound = reads.bind(req)
        before = self.state()
        changed = req.value
        changed['trace_id'] = 'other-trace'
        self.fail('conflict', lambda: reads.close_bind_request(contract('bind_request', changed), self.control()))
        stranger = TrustedPrincipal(self.principal.tenant_id, 'other', 'other-delegation')
        other = self.catalog.controlled_reads(stranger, self.control())
        self.fail('unauthorized', lambda: other.close_bind_request(req, self.control()))
        self.fail('invalid_contract', lambda: reads.release_pin(bound, reads.control))
        self.assertEqual(self.state(), before)
        self.assertTrue(reads._lock.acquire(False))
        try:
            self.fail('resource_limit', lambda: reads.close_bind_request(req, self.control()))
        finally:
            reads._lock.release()

    def test_late_authority_parent_cancel_no_epoch_and_cleanup_remains_available(self):
        cancelled, deadline = [False], time.monotonic() + 1
        def checkpoint():
            if cancelled[0]:
                raise ContractFailure('cancelled', 'stop')
            return deadline
        reads = self.catalog.controlled_reads(self.principal, CatalogReadControl(checkpoint, time.monotonic))
        req = request(self.principal)
        bound = reads.bind(req)
        original = self.authority.verify
        def late(*args):
            original(*args)
            cancelled[0] = True
        with patch.object(self.authority, 'verify', side_effect=late):
            self.fail('cancelled', lambda: reads.reauthorize(bound))
        self.assertFalse(self.query()[0]['released'])
        reads.release_pin(bound, self.control())
        self.assertTrue(self.query()[0]['released'])


if __name__ == '__main__':
    unittest.main()
