"""Durable idempotent private administrative effects, sharing the bounded op log."""
import time
import json
from modules.common.cf1a_primitives import canonical, require, validate_shape
from modules.catalog.cf1a_access import grant_value, principal_for
from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_codec import AdminResult, LIMITS, counter, private_value, sha
from modules.catalog.cf1a_store import CommitUnknown


def admin_intent(principal, operation_id, dataset, action, parameters):
    validate_shape(operation_id, 'id')
    validate_shape(dataset, 'id')
    require(action in ('provision', 'grant', 'revoke', 'rotate_owner'), 'unknown admin action')
    require(type(parameters) is dict, 'invalid admin parameters')
    if action in ('provision', 'rotate_owner'):
        require(set(parameters) == {'owner_subject'}, 'invalid owner parameters')
        validate_shape(parameters['owner_subject'], 'id')
    elif action == 'revoke':
        require(set(parameters) == {'subject_id', 'delegation_ref'}, 'invalid revoke parameters')
        for name in parameters:
            validate_shape(parameters[name], 'id')
    else:
        require(set(parameters) == {'subject_id', 'delegation_ref', 'actions', 'expires_unix_ms',
                                    'publish_plan_id'}, 'invalid grant parameters')
        grant_value({'tenant_id': principal.tenant_id, 'dataset_id': dataset, **parameters})
    value = {'version': 'cf1a-admin/1', 'operation_id': operation_id, 'tenant_id': principal.tenant_id,
            'subject_id': principal.subject_id, 'delegation_ref': principal.delegation_ref,
            'dataset_id': dataset, 'action': action, 'parameters': parameters}
    return json.loads(canonical(value))


def result_for(intent, state, row=None):
    return AdminResult(canonical({'version': 'cf1a-admin/1', 'operation_id': intent['operation_id'],
        'dataset_id': intent['dataset_id'], 'request_sha256': sha(canonical(intent)), 'state': state,
        'generation': row['generation'] if row else 0, 'policy_epoch': row['policy_epoch'] if row else 0,
        'owner_epoch': row['owner_epoch'] if row else 0, 'reconcile_ref': intent['operation_id']}))


class AdminOperations:
    def __init__(self, store):
        self.store = store

    def execute(self, principal, operation_id, dataset, action, parameters, status=False):
        require(type(principal) is TrustedPrincipal and principal.administrator,
                'trusted administrator required', 'unauthorized')
        principal_for(principal, principal.tenant_id)
        intent = admin_intent(principal, operation_id, dataset, action, parameters)
        parameters = intent['parameters']
        raw, identity = canonical(intent), sha(canonical(intent))
        try:
            with self.store.transaction(time.monotonic() + 5) as conn:
                if status and action != 'provision':
                    known = conn.execute('SELECT tenant FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,)).fetchone()
                    if known is None:
                        return result_for(intent, 'outcome_unknown')
                if action == 'provision':
                    conn.execute('SELECT pg_advisory_xact_lock(60210022)')
                    found = conn.execute('SELECT tenant FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,)).fetchone()
                    if found is None:
                        if status:
                            return result_for(intent, 'outcome_unknown')
                        count = conn.execute('SELECT count(*) AS n FROM gura_cf1a.datasets').fetchone()['n']
                        require(count < LIMITS['datasets'], 'dataset capacity reached', 'resource_limit')
                        conn.execute('INSERT INTO gura_cf1a.datasets(dataset,tenant,owner_subject) VALUES(%s,%s,%s)',
                                     (dataset, principal.tenant_id, parameters['owner_subject']))
                row = self.store.dataset(conn, principal.tenant_id, dataset)
                old = conn.execute('SELECT * FROM gura_cf1a.operations WHERE dataset=%s AND operation_id=%s',
                                   (dataset, operation_id)).fetchone()
                if old is not None:
                    require(old['kind'] == 'admin' and old['intent_sha256'] == identity and
                            bytes(old['intent']) == raw and sha(bytes(old['intent'])) == identity,
                            'admin operation ID reused with different intent', 'conflict')
                    require(old['subject'] == principal.subject_id and old['delegation'] == principal.delegation_ref
                            and old['terminalized'] is False, 'admin result owner mismatch')
                    result = AdminResult(bytes(old['receipt']))
                    require(sha(result.encoded) == old['receipt_sha256'] and
                            result.value['request_sha256'] == identity and
                            result.value['operation_id'] == operation_id and result.value['dataset_id'] == dataset and
                            result.value['reconcile_ref'] == operation_id and result.value['state'] == 'applied',
                            'stored admin result mismatch')
                    return result
                if status:
                    return result_for(intent, 'outcome_unknown', row)
                self.store.quota(conn, dataset, 'operations')
                if action == 'provision':
                    require(row['generation'] == 0 and row['owner_subject'] == parameters['owner_subject'],
                            'dataset identity is already provisioned', 'conflict')
                    # Only the newly inserted dataset may receive a provision result.
                    require(found is None, 'dataset cannot be reprovisioned', 'conflict')
                elif action in ('grant', 'revoke'):
                    new_epoch = counter(row['policy_epoch'], 1)
                    params = parameters
                    old_grant = conn.execute('SELECT body,sha256 FROM gura_cf1a.grants WHERE dataset=%s AND subject=%s '
                        'AND delegation=%s', (dataset, params['subject_id'], params['delegation_ref'])).fetchone()
                    if old_grant is not None:
                        stored = grant_value(private_value(old_grant['body'], old_grant['sha256']))
                        require(stored['tenant_id'] == row['tenant'] and stored['dataset_id'] == dataset and
                                stored['subject_id'] == params['subject_id'] and
                                stored['delegation_ref'] == params['delegation_ref'], 'stored admin grant lookup mismatch')
                    if action == 'grant':
                        value = grant_value({'tenant_id': principal.tenant_id, 'dataset_id': dataset, **params})
                        require(value['expires_unix_ms'] > self.store.now(conn), 'new grant already expired', 'expired_context')
                        if old_grant is None:
                            self.store.quota(conn, dataset, 'grants')
                        body = canonical(value)
                        self.store.charge(conn, dataset, len(body) - (len(old_grant['body']) if old_grant else 0))
                        conn.execute('INSERT INTO gura_cf1a.grants VALUES(%s,%s,%s,%s,%s) '
                            'ON CONFLICT(dataset,subject,delegation) DO UPDATE SET body=EXCLUDED.body,sha256=EXCLUDED.sha256',
                            (dataset, params['subject_id'], params['delegation_ref'], body, sha(body)))
                    elif old_grant is not None:
                        self.store.charge(conn, dataset, -len(old_grant['body']))
                        conn.execute('DELETE FROM gura_cf1a.grants WHERE dataset=%s AND subject=%s AND delegation=%s',
                                     (dataset, params['subject_id'], params['delegation_ref']))
                    conn.execute('UPDATE gura_cf1a.datasets SET policy_epoch=%s WHERE dataset=%s', (new_epoch, dataset))
                    row['policy_epoch'] = new_epoch
                else:
                    epoch = counter(row['owner_epoch'], 1)
                    conn.execute("UPDATE gura_cf1a.targets SET state='fenced' WHERE dataset=%s AND state='registered'", (dataset,))
                    conn.execute("UPDATE gura_cf1a.datasets SET owner_subject=%s,owner_epoch=%s,active_plan='' WHERE dataset=%s",
                                 (parameters['owner_subject'], epoch, dataset))
                    row['owner_epoch'] = epoch
                result = result_for(intent, 'applied', row)
                self.store.charge(conn, dataset, len(raw) + len(result.encoded))
                conn.execute('INSERT INTO gura_cf1a.operations(dataset,operation_id,kind,subject,delegation,terminalized,'
                             'intent,intent_sha256,receipt,receipt_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                             (dataset, operation_id, 'admin', principal.subject_id, principal.delegation_ref,
                              False, raw, identity, result.encoded, sha(result.encoded)))
                return result
        except CommitUnknown:
            return result_for(intent, 'outcome_unknown')
