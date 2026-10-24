"""SQL unit semantics and independent state assertions; real PG driver owns locks/IO."""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch
from dataclasses import FrozenInstanceError
from modules.catalog.cf1a_admin import admin_intent
from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_codec import AdminResult, MAX_COUNTER, contract, counter, private_value, sha
from modules.common.cf1a_primitives import ContractFailure, canonical
from tests.catalog_support.fixed_fixture import authorization, configure, intents, new_catalog, request, target
from tests.catalog_support.sqlite_unit import install


class FixedCatalogUnits(unittest.TestCase):
    def setUp(self):
        self.clock = {'ms': int(time.time() * 1000)}
        self.catalog, self.authority, self.principal, _ = new_catalog(
            'host=127.0.0.1 port=5555 dbname=fixture user=fixture sslmode=disable', self.clock['ms'])
        self.store = install(self.catalog, self.clock)
        self.addCleanup(self.store.connection.close)
        self.conn = self.store.connection
        configure(self.catalog, self.principal, self.clock['ms'])
        self.auth = authorization(self.principal, self.clock['ms'])
        self.port = self.catalog.port(self.principal)
        self.target = target(self.clock['ms'])
        self.authority.allow(self.target)
        self.register, self.publish = intents(self.target)

    def fail(self, callback, code=None):
        with self.assertRaises(ContractFailure) as caught:
            callback()
        if code:
            self.assertEqual(caught.exception.code, code)

    def row(self):
        return self.conn.execute('SELECT * FROM gura_cf1a.datasets WHERE dataset=%s', ('dataset-1',)).fetchone()

    def published(self):
        first = self.port.register(self.register, self.auth, self.target)
        second = self.port.publish(self.publish, self.auth, self.target)
        self.assertEqual((first.value['generation'], second.value['generation']), (1, 2))
        return second

    def test_complete_target_two_generation_and_old_view_retention(self):
        self.port.register(self.register, self.auth, self.target)
        self.fail(lambda: self.port.bind(request(self.principal)), 'conflict')
        self.port.publish(self.publish, self.auth, self.target)
        bound = self.port.bind(request(self.principal))
        self.assertEqual(bound.value['context']['read_view_id'], 'view-a')
        self.assertEqual(self.port.reauthorize(bound), 2)
        rebuilt = target(self.clock['ms'], view='view-b', generation=4, sequence=2)
        self.authority.allow(rebuilt)
        reg, pub = intents(rebuilt, 'register-b', 'publish-b', 2, prior_view='view-a')
        self.assertEqual(self.port.register(reg, self.auth, rebuilt).value['state'], 'applied')
        self.assertEqual(self.port.publish(pub, self.auth, rebuilt).value['state'], 'applied')
        self.assertEqual(self.port.bind(request(self.principal)).encoded, bound.encoded)
        new = self.port.bind(request(self.principal, 'query-b'))
        self.assertEqual(new.value['context']['read_view_id'], 'view-b')
        self.assertEqual(self.port.reauthorize(bound), 2)
        self.assertEqual(self.row()['generation'], 4)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM gura_cf1a.identities '
            "WHERE kind='revision'").fetchone()['n'], 1)

    def test_replay_precedes_new_cas_and_protection_no_duplicate_effect(self):
        result = self.published()
        self.authority.withdraw(self.target)
        self.assertEqual(self.port.publish(self.publish, self.auth, self.target).encoded, result.encoded)
        registered = self.port.register(self.register, self.auth, self.target)
        self.assertEqual(registered.value['generation'], 1)
        self.assertEqual(self.row()['generation'], 2)
        self.fail(lambda: self.port.bind(request(self.principal)), 'revoked')
        self.fail(lambda: self.port.register(self.publish, self.auth, self.target))

    def test_superseded_plan_and_wrong_expected_generation_rejected_durably(self):
        self.port.register(self.register, self.auth, self.target)
        replacement = target(self.clock['ms'], 'view-b', generation=3, sequence=1)
        self.authority.allow(replacement)
        reg, pub = intents(replacement, 'register-b', 'publish-b', 1)
        self.assertEqual(self.port.register(reg, self.auth, replacement).value['state'], 'applied')
        stale = self.port.publish(self.publish, self.auth, self.target)
        self.assertEqual(stale.value['state'], 'rejected')
        self.assertEqual(stale.value['result_id'], '')
        self.assertEqual(self.port.publish(self.publish, self.auth, self.target).encoded, stale.encoded)
        self.assertEqual(self.port.publish(pub, self.auth, replacement).value['state'], 'applied')
        self.assertEqual(self.row()['published'], 'view-b')

    def test_linear_new_revision_and_same_revision_content_conflict(self):
        self.published()
        successor = target(self.clock['ms'], 'view-b', 'revision-b', ['revision-a'], 4, 2)
        self.authority.allow(successor)
        reg, pub = intents(successor, 'register-b', 'publish-b', 2, prior_view='view-a')
        self.assertEqual(self.port.register(reg, self.auth, successor).value['state'], 'applied')
        self.assertEqual(self.port.publish(pub, self.auth, successor).value['state'], 'applied')
        historic = target(self.clock['ms'], 'view-c', generation=6, sequence=3)
        self.authority.allow(historic)
        reg, _ = intents(historic, 'register-c', 'publish-c', 4, prior_view='view-b')
        self.assertEqual(self.port.register(reg, self.auth, historic).value['state'], 'rejected')
        self.assertEqual(self.row()['head_revision'], 'revision-b')

    def test_commit_unknown_and_absent_tombstone_excludes_late_request(self):
        self.store.fault = 'after_commit'
        unknown = self.port.register(self.register, self.auth, self.target)
        self.assertEqual(unknown.value['state'], 'outcome_unknown')
        self.assertEqual(self.row()['generation'], 1)
        recovered = self.port.reconcile(self.register, self.auth)
        self.assertEqual(recovered.value['state'], 'applied')
        self.store.fault = 'before_commit'
        self.assertEqual(self.port.publish(self.publish, self.auth, self.target).value['state'], 'outcome_unknown')
        self.assertEqual(self.row()['published'], '')
        tombstone = self.port.reconcile(self.publish, self.auth)
        self.assertEqual(tombstone.value['state'], 'rejected')
        self.assertEqual(self.port.publish(self.publish, self.auth, self.target).encoded, tombstone.encoded)
        self.assertEqual(self.row()['published'], '')

    def test_admin_unknown_exact_replay_old_revoke_does_not_revoke_regrant(self):
        c, p, now = self.catalog, self.principal, self.clock['ms']
        c.grant(p, 'grant-reader', 'dataset-1', 'reader', 'reader-session', ['read'], now + 60000)
        self.store.fault = 'after_commit'
        result = c.revoke(p, 'revoke-reader', 'dataset-1', 'reader', 'reader-session')
        self.assertEqual(result.value['state'], 'outcome_unknown')
        params = {'subject_id': 'reader', 'delegation_ref': 'reader-session'}
        known = c.admin_status(p, 'revoke-reader', 'dataset-1', 'revoke', params)
        self.assertEqual(known.value['state'], 'applied')
        c.grant(p, 'regrant-reader', 'dataset-1', 'reader', 'reader-session', ['read'], now + 60000)
        self.assertEqual(c.revoke(p, 'revoke-reader', 'dataset-1', 'reader', 'reader-session').encoded, known.encoded)
        self.assertIsNotNone(self.conn.execute('SELECT subject FROM gura_cf1a.grants WHERE subject=%s', ('reader',)).fetchone())
        self.fail(lambda: c.revoke(p, 'revoke-reader', 'dataset-1', 'other', 'reader-session'), 'conflict')
        self.assertEqual(c.admin_status(p, 'absent-op', 'dataset-1', 'revoke', params).value['state'], 'outcome_unknown')
        self.assertEqual(c.admin_status(p, 'absent-op', 'absent-dataset', 'revoke', params).value['state'], 'outcome_unknown')

    def test_bind_unknown_same_query_immutable_bytes_and_exact_cleanup(self):
        self.published()
        req = request(self.principal)
        self.store.fault = 'after_commit'
        self.fail(lambda: self.port.bind(req), 'outcome_unknown')
        bound = self.port.bind(req)
        mutated = req.value; mutated['trace_id'] = 'other-trace'
        self.fail(lambda: self.port.bind(contract('bind_request', mutated)), 'conflict')
        forged = bound.value; forged['context']['budget']['memory_bytes'] += 1
        fake = contract('read_binding', forged)
        self.fail(lambda: self.port.reauthorize(fake), 'unauthorized')
        self.fail(lambda: self.port.release_pin(fake), 'unauthorized')
        self.catalog.revoke(self.principal, 'revoke-self', 'dataset-1', self.principal.subject_id,
                            self.principal.delegation_ref)
        self.fail(lambda: self.port.reauthorize(bound), 'unauthorized')
        self.port.release_pin(bound)
        self.port.release_pin(bound)
        self.assertTrue(self.conn.execute('SELECT released FROM gura_cf1a.queries').fetchone()['released'])

    def test_owner_fencing_and_policy_epoch_are_independent(self):
        self.published()
        bound = self.port.bind(request(self.principal))
        result = self.catalog.rotate_owner(self.principal, 'rotate-a', 'dataset-1', self.principal.subject_id)
        self.assertEqual(result.value['owner_epoch'], 2)
        self.assertEqual(self.port.reauthorize(bound), 2)
        rebuilt = target(self.clock['ms'], 'view-b', generation=4, sequence=2)
        self.authority.allow(rebuilt)
        reg, _ = intents(rebuilt, 'register-b', 'publish-b', 2, prior_view='view-a')
        rejected = self.port.register(reg, self.auth, rebuilt)
        self.assertEqual(rejected.value['error_code'], 'stale_generation')
        self.catalog.grant(self.principal, 'grant-self-again', 'dataset-1', self.principal.subject_id,
            self.principal.delegation_ref, ['read', 'register', 'publish', 'reconcile'], self.clock['ms'] + 90000)
        self.fail(lambda: self.port.reauthorize(bound), 'revoked')
        self.port.release_pin(bound)

    def test_private_admin_values_are_closed_immutable_and_strict(self):
        params = {'subject_id': 'r', 'delegation_ref': 's', 'actions': ['read'],
                  'expires_unix_ms': self.clock['ms'] + 60000, 'publish_plan_id': ''}
        intent = admin_intent(self.principal, 'admin-test', 'dataset-1', 'grant', params)
        params['actions'].append('publish')
        self.assertEqual(intent['parameters']['actions'], ['read'])
        self.fail(lambda: admin_intent(self.principal, 'admin-test', 'dataset-1', 'grant', {**params, 'extra': True}))
        result = self.catalog.admin_status(self.principal, 'admin-test', 'dataset-1', 'grant', intent['parameters'])
        mutable = bytearray(result.encoded)
        frozen = AdminResult(memoryview(mutable))
        mutable[:] = b'0' * len(mutable)
        self.assertEqual(frozen.encoded, result.encoded)
        with self.assertRaises(FrozenInstanceError): frozen.encoded = b'{}'
        self.fail(lambda: counter(True))
        self.fail(lambda: counter(MAX_COUNTER, 1), 'resource_limit')
        self.fail(lambda: private_value(b'bad-json', sha(b'bad-json')))
        self.fail(lambda: private_value(b'{} ', sha(b'{} ')))
        self.assertEqual(self.catalog.admin_status(self.principal, 'absent-provision', 'absent-dataset',
            'provision', {'owner_subject': self.principal.subject_id}).value['state'], 'outcome_unknown')

    def test_current_time_after_authority_and_expired_exact_cleanup(self):
        original = self.authority.verify
        def advance(*args):
            original(*args)
            self.clock['ms'] += 100000
        with patch.object(self.authority, 'verify', side_effect=advance):
            self.fail(lambda: self.port.register(self.register, self.auth, self.target), 'expired_context')
        self.assertEqual(self.row()['generation'], 0)
        self.clock['ms'] -= 100000
        self.published()
        binding = self.port.bind(request(self.principal))
        self.clock['ms'] = binding.value['context']['deadline_unix_ms'] + 1
        self.fail(lambda: self.port.bind(request(self.principal)), 'deadline')
        self.port.release_pin(binding)
        self.assertTrue(self.conn.execute('SELECT released FROM gura_cf1a.queries').fetchone()['released'])

    def test_shared_receipt_quota_still_allows_known_admin_replay(self):
        self.published()
        count = self.conn.execute('SELECT count(*) AS n FROM gura_cf1a.operations').fetchone()['n']
        for number in range(count, 512):
            self.catalog.revoke(self.principal, 'fill-' + str(number), 'dataset-1', 'absent', 'absent-session')
        self.fail(lambda: self.catalog.revoke(self.principal, 'over-limit', 'dataset-1', 'absent', 'absent-session'),
                  'resource_limit')
        params = {'owner_subject': self.principal.subject_id}
        self.assertEqual(self.catalog.admin_status(self.principal, 'provision-a', 'dataset-1', 'provision', params)
                         .value['state'], 'applied')
        epoch = self.row()['policy_epoch']
        fresh_auth = authorization(self.principal, self.clock['ms'], epoch)
        self.assertEqual(self.port.publish(self.publish, fresh_auth, self.target).value['state'], 'applied')
        other = TrustedPrincipal('tenant-1', 'other-admin', 'other-session', administrator=True)
        self.fail(lambda: self.catalog.provision(other, 'provision-a', 'dataset-1', other.subject_id), 'conflict')

    def test_worker_publish_requires_live_exact_plan_and_cannot_register(self):
        self.port.register(self.register, self.auth, self.target)
        worker = TrustedPrincipal('tenant-1', 'worker', 'worker-session')
        c, p, now = self.catalog, self.principal, self.clock['ms']
        count = self.conn.execute('SELECT count(*) AS n FROM gura_cf1a.operations').fetchone()['n']
        self.fail(lambda: c.grant(p, 'invalid-plan-grant', 'dataset-1', worker.subject_id,
            worker.delegation_ref, ['read'], now + 60000, publish_plan_id='view-a'))
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM gura_cf1a.operations').fetchone()['n'], count)
        wrong = c.grant(p, 'wrong-plan-grant', 'dataset-1', worker.subject_id, worker.delegation_ref,
                        ['publish'], now + 60000, publish_plan_id='view-other')
        worker_port = c.port(worker)
        auth = authorization(worker, now, wrong.value['policy_epoch'], actions=('publish',))
        self.fail(lambda: worker_port.publish(self.publish, auth, self.target), 'unauthorized')
        self.assertEqual((self.row()['generation'], self.row()['published']), (1, ''))
        self.assertIsNone(self.conn.execute('SELECT operation_id FROM gura_cf1a.operations WHERE operation_id=%s',
                                           ('publish-a',)).fetchone())
        granted = c.grant(p, 'exact-plan-grant', 'dataset-1', worker.subject_id, worker.delegation_ref,
                          ['publish', 'register'], now + 60000, publish_plan_id='view-a')
        auth = authorization(worker, now, granted.value['policy_epoch'], actions=('publish', 'register'))
        self.fail(lambda: worker_port.register(self.register, auth, self.target), 'unauthorized')
        self.assertEqual(worker_port.publish(self.publish, auth, self.target).value['state'], 'applied')
        self.assertEqual((self.row()['generation'], self.row()['published']), (2, 'view-a'))

    def test_authorization_unknown_and_release_unknown_do_not_claim_success(self):
        self.published()
        binding = self.port.bind(request(self.principal))
        self.store.fault = 'after_commit'
        self.fail(lambda: self.port.reauthorize(binding), 'backend_unavailable')
        self.assertEqual(self.port.reauthorize(binding), 2)
        for fault in ('before_commit', 'after_commit'):
            bound = self.port.bind(request(self.principal, 'release-' + fault))
            self.store.fault = fault
            self.fail(lambda: self.port.release_pin(bound), 'outcome_unknown')
            row = self.conn.execute('SELECT released FROM gura_cf1a.queries WHERE query_id=%s',
                                    ('release-' + fault,)).fetchone()
            self.assertEqual(row['released'], fault == 'after_commit')
            self.port.release_pin(bound)
            self.port.release_pin(bound)
            self.assertTrue(self.conn.execute('SELECT released FROM gura_cf1a.queries WHERE query_id=%s',
                                             ('release-' + fault,)).fetchone()['released'])
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM gura_cf1a.queries').fetchone()['n'], 3)

    def test_reconcile_unknown_keeps_terminal_or_absent_outcome_distinct(self):
        self.store.fault = 'after_commit'
        result = self.port.reconcile(self.register, self.auth)
        self.assertEqual(result.value['state'], 'outcome_unknown')
        stored = self.conn.execute('SELECT terminalized FROM gura_cf1a.operations WHERE operation_id=%s',
                                   ('register-a',)).fetchone()
        self.assertTrue(stored['terminalized'])
        self.assertEqual(self.port.reconcile(self.register, self.auth).value['state'], 'rejected')
        self.assertEqual(self.port.register(self.register, self.auth, self.target).value['state'], 'rejected')
        self.assertEqual(self.row()['generation'], 0)
        second, _ = intents(self.target, 'register-before', 'publish-before')
        self.store.fault = 'before_commit'
        self.assertEqual(self.port.reconcile(second, self.auth).value['state'], 'outcome_unknown')
        self.assertIsNone(self.conn.execute('SELECT operation_id FROM gura_cf1a.operations WHERE operation_id=%s',
                                           ('register-before',)).fetchone())
        self.assertEqual(self.port.register(second, self.auth, self.target).value['state'], 'applied')
        self.assertEqual(self.row()['generation'], 1)

    def test_register_reserves_two_generations_without_partial_rejection(self):
        self.conn.execute('UPDATE gura_cf1a.datasets SET generation=%s WHERE dataset=%s',
                          (MAX_COUNTER - 1, 'dataset-1'))
        self.conn.commit()
        value = self.register.value
        value['expected_generation'] = MAX_COUNTER - 1
        self.fail(lambda: self.port.register(contract('register_intent', value), self.auth, self.target), 'resource_limit')
        self.assertEqual(self.row()['generation'], MAX_COUNTER - 1)
        self.assertEqual(self.row()['active_plan'], '')
        self.assertIsNone(self.conn.execute('SELECT operation_id FROM gura_cf1a.operations WHERE operation_id=%s',
                                           ('register-a',)).fetchone())
        for table in ('targets', 'identities'):
            self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM gura_cf1a.' + table).fetchone()['n'], 0)
