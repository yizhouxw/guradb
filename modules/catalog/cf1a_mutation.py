"""Whole-target publication, durable receipt replay and serialized absent reconcile."""
import time
from modules.common.cf1a_primitives import ContractFailure, digest, require
from modules.common.cf1a_publication import check_cas, check_receipt, check_replay, check_target
from modules.catalog.cf1a_access import live_grant, mutation_access
from modules.catalog.cf1a_codec import counter, receipt, sha, stored_contract
from modules.catalog.cf1a_store import CommitUnknown


class Mutations:
    def __init__(self, store):
        self.store = store

    def replay(self, conn, principal, intent):
        value = intent.value
        row = conn.execute('SELECT * FROM gura_cf1a.operations WHERE dataset=%s AND operation_id=%s',
                           (value['dataset_id'], value['operation_id'])).fetchone()
        if row is None:
            return None
        require(row['kind'] == intent.kind, 'operation ID reused across intent kinds', 'conflict')
        original = stored_contract(row['intent'], row['intent_sha256'], intent.kind)
        check_replay(original.value, value)
        require(type(row['terminalized']) is bool, 'invalid operation terminalization flag')
        require(row['terminalized'] or (row['subject'] == principal.subject_id and
                row['delegation'] == principal.delegation_ref), 'operation belongs to another principal', 'unauthorized')
        result = stored_contract(row['receipt'], row['receipt_sha256'], 'mutation_receipt')
        require(check_receipt(value, result.value), 'stored operation cannot be unknown')
        require(not row['terminalized'] or result.value['state'] == 'rejected', 'invalid terminalized receipt')
        return result

    def persist(self, conn, principal, intent, result, terminalized=False):
        dataset = intent.value['dataset_id']
        self.store.quota(conn, dataset, 'operations')
        self.store.charge(conn, dataset, len(intent.encoded) + len(result.encoded))
        conn.execute('INSERT INTO gura_cf1a.operations(dataset,operation_id,kind,subject,delegation,terminalized,'
                     'intent,intent_sha256,receipt,receipt_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (dataset, intent.value['operation_id'], intent.kind, principal.subject_id,
                      principal.delegation_ref, terminalized, intent.encoded, sha(intent.encoded),
                      result.encoded, sha(result.encoded)))

    def register_preflight(self, conn, row, principal, intent, target):
        value, content = intent.value, target.value
        check_cas(value, row['generation'], row['owner_epoch'])
        check_target(intent, target)
        planned_generation = counter(row['generation'], 2)
        planned_sequence = counter(row['sequence'], 1)
        require(content['view']['publication_generation'] == planned_generation and
                content['view']['publication_sequence'] == planned_sequence, 'target must reserve g+2 and next sequence', 'conflict')
        revision = content['revision']
        head = row['head_revision']
        if revision['data_revision_id'] != head:
            known = conn.execute("SELECT id FROM gura_cf1a.identities WHERE dataset=%s AND kind='revision' AND id=%s",
                                 (row['dataset'], revision['data_revision_id'])).fetchone()
            require(known is None and revision['parent_revision_ids'] == ([head] if head else []),
                    'revision must extend current head', 'conflict')
        existing = conn.execute('SELECT view_id FROM gura_cf1a.targets WHERE dataset=%s AND view_id=%s',
                                (row['dataset'], content['view']['read_view_id'])).fetchone()
        require(existing is None, 'view identity already registered', 'conflict')
        self.store.identities(conn, row['dataset'], target, allow_missing=True)

    def register_effect(self, conn, row, principal, intent, target):
        value = target.value
        dataset, view = row['dataset'], value['view']
        self.store.quota(conn, dataset, 'targets')
        self.store.identities(conn, dataset, target, create=True)
        self.store.charge(conn, dataset, len(target.encoded))
        conn.execute("UPDATE gura_cf1a.targets SET state='superseded' WHERE dataset=%s AND state='registered'", (dataset,))
        conn.execute('INSERT INTO gura_cf1a.targets VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (dataset, view['read_view_id'], value['revision']['data_revision_id'], target.encoded, sha(target.encoded),
             intent.value['operation_id'], counter(row['generation'], 1), row['owner_subject'], row['owner_epoch'],
             row['published'], view['publication_generation'], view['publication_sequence'], 'registered'))
        conn.execute('UPDATE gura_cf1a.datasets SET generation=%s,head_revision=%s,active_plan=%s WHERE dataset=%s',
                     (counter(row['generation'], 1), value['revision']['data_revision_id'], view['read_view_id'], dataset))

    def publish_preflight(self, conn, row, principal, intent, target):
        value = intent.value
        check_cas(value, row['generation'], row['owner_epoch'], row['published'], row['sequence'])
        check_target(intent, target)
        plan, registered = self.store.target(conn, row['tenant'], row['dataset'], value['target_view_id'])
        require(digest(registered.value) == digest(target.value), 'publish target differs from registered plan', 'conflict')
        require(plan['state'] == 'registered' and row['active_plan'] == plan['view_id'] and
                plan['owner_epoch'] == row['owner_epoch'] and plan['owner_subject'] == row['owner_subject'] and
                plan['register_generation'] == row['generation'] and plan['revision_id'] == row['head_revision'] and
                plan['prior_view'] == row['published'] and plan['publication_sequence'] == counter(row['sequence'], 1) and
                intent.value['operation_id'] != plan['register_operation'], 'publication plan superseded or fenced', 'conflict')
        counter(row['generation'], 1)

    def publish_effect(self, conn, row, principal, intent, target):
        value = intent.value
        conn.execute("UPDATE gura_cf1a.targets SET state='published' WHERE dataset=%s AND view_id=%s",
                     (row['dataset'], value['target_view_id']))
        conn.execute("UPDATE gura_cf1a.datasets SET generation=%s,published=%s,sequence=%s,active_plan='' WHERE dataset=%s",
                     (counter(row['generation'], 1), value['target_view_id'], value['publication_sequence'], row['dataset']))

    def execute(self, principal, intent, auth, target):
        require(intent.kind in ('register_intent', 'publish_intent') and target.kind == 'read_descriptors',
                'expected immutable mutation intent/target')
        check_target(intent, target)
        value = intent.value
        try:
            with self.store.transaction(time.monotonic() + 5) as conn:
                row = self.store.dataset(conn, value['tenant_id'], value['dataset_id'])
                mutation_access(conn, row, principal, intent, auth, self.store.now(conn))
                known = self.replay(conn, principal, intent)
                if known is not None:
                    return known
                action = 'register' if intent.kind == 'register_intent' else 'publish'
                try:
                    getattr(self, action + '_preflight')(conn, row, principal, intent, target)
                except ContractFailure as error:
                    if error.code not in ('conflict', 'stale_generation'):
                        raise
                    rejected = receipt(intent, 'rejected', row['generation'], error.code)
                    self.persist(conn, principal, intent, rejected)
                    return rejected
                now = self.store.now(conn)
                self.store.protection.verify(target, now, now)
                now = self.store.now(conn)
                mutation_access(conn, row, principal, intent, auth, now)
                require(all(source['protected_until_unix_ms'] >= now for source in target.value['revision']['sources']),
                        'source protection expired while validating', 'expired_context')
                self.store.quota(conn, row['dataset'], 'operations')
                getattr(self, action + '_effect')(conn, row, principal, intent, target)
                result = receipt(intent, 'applied', counter(row['generation'], 1))
                self.persist(conn, principal, intent, result)
                return result
        except CommitUnknown:
            return receipt(intent, 'outcome_unknown', value['expected_generation'], 'outcome_unknown')

    def reconcile(self, principal, intent, auth):
        require(intent.kind in ('register_intent', 'publish_intent'), 'expected mutation intent')
        value = intent.value
        try:
            with self.store.transaction(time.monotonic() + 5) as conn:
                row = self.store.dataset(conn, value['tenant_id'], value['dataset_id'])
                now = self.store.now(conn)
                original = mutation_access(conn, row, principal, intent, auth, now, True)
                known = self.replay(conn, principal, intent)
                if known is not None:
                    return known
                require(principal.administrator and original in auth.value['actions'],
                        'absent reconcile requires administrator and original action', 'unauthorized')
                live_grant(conn, row, principal, [original, 'reconcile'], now,
                           value.get('target_view_id') if original == 'publish' else None)
                result = receipt(intent, 'rejected', row['generation'], 'conflict')
                self.persist(conn, principal, intent, result, True)
                return result
        except CommitUnknown:
            return receipt(intent, 'outcome_unknown', value['expected_generation'], 'outcome_unknown')
