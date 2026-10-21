"""Current PG grant checks; wire scope and trusted session identity stay distinct."""
from modules.common.cf1a_primitives import require, validate_shape
from modules.common.cf1a_publication import check_mutation_auth
from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_codec import private_value

ACTIONS = frozenset(('read', 'register', 'publish', 'reconcile'))


def principal_for(principal, tenant):
    require(type(principal) is TrustedPrincipal and principal.tenant_id == tenant,
            'trusted principal scope mismatch', 'unauthorized')


def grant_value(value):
    require(type(value) is dict and set(value) == {'tenant_id', 'dataset_id', 'subject_id',
            'delegation_ref', 'actions', 'expires_unix_ms', 'publish_plan_id'}, 'invalid grant fields')
    for name in ('tenant_id', 'dataset_id', 'subject_id', 'delegation_ref'):
        validate_shape(value[name], 'id')
    actions = value['actions']
    require(type(actions) is list and 0 < len(actions) <= 4 and all(type(x) is str for x in actions)
            and len(set(actions)) == len(actions) and set(actions) <= ACTIONS, 'invalid grant actions')
    validate_shape(value['expires_unix_ms'], 'positive')
    validate_shape(value['publish_plan_id'], 'text')
    if value['publish_plan_id']:
        validate_shape(value['publish_plan_id'], 'id')
        require('publish' in actions, 'plan grant lacks publish action')
    return value


def live_grant(conn, dataset, principal, actions, now, plan=None):
    principal_for(principal, dataset['tenant'])
    row = conn.execute('SELECT body,sha256 FROM gura_cf1a.grants WHERE dataset=%s AND subject=%s '
                       'AND delegation=%s', (dataset['dataset'], principal.subject_id,
                                            principal.delegation_ref)).fetchone()
    require(row is not None, 'current catalog grant unavailable', 'unauthorized')
    value = grant_value(private_value(row['body'], row['sha256']))
    require(value['tenant_id'] == dataset['tenant'] and value['dataset_id'] == dataset['dataset'] and
            value['subject_id'] == principal.subject_id and value['delegation_ref'] == principal.delegation_ref,
            'stored grant lookup mismatch')
    require(set(actions) <= set(value['actions']), 'current action is not granted', 'unauthorized')
    require(now < value['expires_unix_ms'], 'catalog grant expired', 'expired_context')
    if plan is not None and not principal.administrator:
        require(value['publish_plan_id'] == plan, 'worker publish grant must bind exact plan', 'unauthorized')
    return value


def mutation_access(conn, dataset, principal, intent, auth, now, reconcile=False):
    principal_for(principal, dataset['tenant'])
    require(auth.kind == 'mutation_auth', 'expected mutation authorization')
    value = auth.value
    require(value['subject_id'] == principal.subject_id and value['delegation_ref'] == principal.delegation_ref,
            'wire authorization is not authenticated principal', 'unauthorized')
    check_mutation_auth(intent, auth, now, dataset['policy_epoch'], reconcile)
    original = 'register' if intent.kind == 'register_intent' else 'publish'
    action = 'reconcile' if reconcile else original
    live_grant(conn, dataset, principal, [action], now,
               intent.value.get('target_view_id') if not reconcile and action == 'publish' else None)
    if not reconcile and action == 'register':
        require(principal.administrator and principal.subject_id == dataset['owner_subject'],
                'registration requires trusted current owner', 'unauthorized')
    return original
