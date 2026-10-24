"""Real adapter writes reach every remaining FC10 row quota independently."""
from copy import deepcopy
import time

from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_codec import contract
from tests.catalog_support.fixed_fixture import intents, request
from tests.catalog_support.pg_quota_truth import (
    artifacts, counts, encoded, exact_release, expect, note, publish, rebuild, same_state,
    sha, state, target_guard, unchanged,
)


def grant_capacity(cases):
    c, p, dataset = cases.catalog, cases.principal, 'quota-grants'
    c.provision(p, 'quota-grants-provision', dataset, p.subject_id)
    expires = cases.now + 300000
    first = None
    for number in range(64):
        result = c.grant(p, f'quota-grant-{number:02d}', dataset, f'subject-{number:02d}',
                         f'session-{number:02d}', ['read'], expires)
        assert result.value['policy_epoch'] == number + 2
        if number == 0:
            first = result
    expect(cases, dataset, grants=64, operations=65, policy_epoch=65,
           identities=0, targets=0, queries=0, generation=0)
    unchanged(cases, 'grant65-atomic-capacity', lambda: c.grant(p, 'quota-grant-65', dataset,
              'subject-65', 'session-65', ['read'], expires), dataset)
    before = state(cases, dataset)
    assert c.grant(p, 'quota-grant-00', dataset, 'subject-00', 'session-00', ['read'], expires).encoded == first.encoded
    same_state(cases, 'full-grant-known-replay', before, state(cases, dataset), dataset)
    updated = c.grant(p, 'quota-grant-existing-update', dataset, 'subject-00', 'session-00',
                      ['read', 'reconcile'], expires)
    assert updated.value['policy_epoch'] == 66
    expect(cases, dataset, grants=64, operations=66, policy_epoch=66)
    row = cases.sql('SELECT body FROM gura_cf1a.grants WHERE dataset=%s AND subject=%s AND delegation=%s',
                    (dataset, 'subject-00', 'session-00'))[0]
    expected = {'tenant_id': p.tenant_id, 'dataset_id': dataset, 'subject_id': 'subject-00',
                'delegation_ref': 'session-00', 'actions': ['read', 'reconcile'],
                'expires_unix_ms': expires, 'publish_plan_id': ''}
    assert bytes(row['body']) == encoded(expected)
    before = state(cases, dataset)
    assert c.grant(p, 'quota-grant-00', dataset, 'subject-00', 'session-00', ['read'], expires).encoded == first.encoded
    same_state(cases, 'old-grant-replay-does-not-revert-update', before, state(cases, dataset), dataset)
    note(cases, 'actual64-grants-update-and-old-replay', dataset, expected_grants=64, expected_epoch=66)


def identity_capacity(cases):
    dataset, port = 'quota-identities', cases.catalog.port(cases.principal)
    auth, seed, _ = cases.prepare(dataset)
    first_artifacts = artifacts(seed, 'identity-first', 125)
    first = rebuild(seed, 'identity-view-1', 2, 1, first_artifacts)
    first_ops = publish(cases, auth, first, 0, '')
    expect(cases, dataset, identities=129, targets=1, operations=4, generation=2, sequence=1,
           grants=1, queries=0, policy_epoch=2)
    second = rebuild(seed, 'identity-view-2', 4, 2, artifacts(seed, 'identity-second', 126))
    publish(cases, auth, second, 2, 'identity-view-1')
    expect(cases, dataset, identities=256, targets=2, operations=6, generation=4, sequence=2,
           grants=1, queries=0, policy_epoch=2)
    third = rebuild(seed, 'identity-view-3', 6, 3, first_artifacts[:1])
    target_guard(cases, third, dataset)
    cases.authority.allow(third)
    registration, _ = intents(third, 'identity-view-3-register', 'identity-view-3-publish', 4,
                             prior_view='identity-view-2')
    cases.inputs.append({'dataset': dataset, 'target': third.document, 'intents': [registration.document]})
    unchanged(cases, 'identity257-atomic-capacity', lambda: port.register(registration, auth, third), dataset)
    before = state(cases, dataset)
    reg, pub, registered, published = first_ops
    assert port.register(reg, auth, first).encoded == registered.encoded
    assert port.publish(pub, auth, first).encoded == published.encoded
    same_state(cases, 'full-identity-known-mutation-replay', before, state(cases, dataset), dataset)
    note(cases, 'actual256-identities-under-other-quotas', dataset, expected_identities=256)


def target_capacity(cases):
    dataset, port = 'quota-targets', cases.catalog.port(cases.principal)
    auth, seed, _ = cases.prepare(dataset)
    previous, first, first_ops = '', None, None
    for sequence in range(1, 129):
        value = rebuild(seed, f'target-view-{sequence:03d}', 2 * sequence, sequence)
        actual = counts(cases, dataset)
        assert actual['identities'] + (5 if sequence == 1 else 1) <= 256
        current = publish(cases, auth, value, 2 * (sequence - 1), previous)
        if sequence == 1:
            first, first_ops = value, current
        previous = value.value['view']['read_view_id']
    expect(cases, dataset, identities=132, targets=128, operations=258, generation=256, sequence=128,
           grants=1, queries=0, policy_epoch=2)
    extra = rebuild(seed, 'target-view-129', 258, 129)
    target_guard(cases, extra, dataset)
    cases.authority.allow(extra)
    registration, _ = intents(extra, 'target-view-129-register', 'target-view-129-publish', 256,
                             prior_view=previous)
    cases.inputs.append({'dataset': dataset, 'target': extra.document, 'intents': [registration.document]})
    unchanged(cases, 'target129-atomic-capacity', lambda: port.register(registration, auth, extra), dataset)
    before = state(cases, dataset)
    reg, pub, registered, published = first_ops
    assert port.register(reg, auth, first).encoded == registered.encoded
    assert port.publish(pub, auth, first).encoded == published.encoded
    same_state(cases, 'full-target-known-mutation-replay', before, state(cases, dataset), dataset)
    note(cases, 'actual128-targets-with132-identities', dataset, expected_targets=128)


def wait_expired(cases, binding):
    expires = binding.value['context']['pin']['expires_unix_ms']
    started, stop = time.monotonic(), time.monotonic() + 1
    while True:
        now = cases.sql('SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS ms')[0]['ms']
        if now > expires:
            return time.monotonic() - started
        assert time.monotonic() < stop, 'bounded real-PG expiry wait failed; never extend original lease'
        time.sleep(.01)


def query_capacity(cases):
    dataset, p, c = 'quota-queries', cases.principal, cases.catalog
    auth, seed, _ = cases.prepare(dataset)
    compact = rebuild(seed, 'query-scan-view', 2, 1, [])
    publish(cases, auth, compact, 0, '')
    port = c.port(p)
    initial = counts(cases, dataset)
    short_request = request(p, 'quota-query-0000', timeout_ms=150, dataset=dataset)
    assert len(short_request.encoded) < 1024 * 1024
    expired = port.bind(short_request)
    per_row_bound = len(expired.encoded) + len(short_request.encoded) + 64
    assert initial['metadata_bytes'] + 1024 * per_row_bound < 8 * 1024 * 1024
    saved = {}
    for number in range(1, 1024):
        value = request(p, f'quota-query-{number:04d}', dataset=dataset)
        assert len(value.encoded) < 1024 * 1024
        binding = port.bind(value)
        assert len(value.encoded) + len(binding.encoded) <= per_row_bound
        if number in (1, 2, 1023):
            saved[number] = (value, binding)
        if number == 1:
            port.release_pin(binding)
        if number in (255, 511, 767, 1023):
            expect(cases, dataset, queries=number + 1, operations=4, identities=4, targets=1,
                   grants=1, policy_epoch=2)
    waited = wait_expired(cases, expired)
    mixture = cases.sql('SELECT count(*) AS total, count(*) FILTER (WHERE released) AS released, '
        'count(*) FILTER (WHERE NOT released AND expires_unix_ms <= '
        'floor(extract(epoch FROM clock_timestamp())*1000)::bigint) AS expired, '
        'count(*) FILTER (WHERE NOT released AND expires_unix_ms > '
        'floor(extract(epoch FROM clock_timestamp())*1000)::bigint) AS live '
        'FROM gura_cf1a.queries WHERE dataset=%s', (dataset,))[0]
    assert mixture['total'] == 1024 and mixture['released'] == 1
    assert mixture['expired'] >= 1 and mixture['live'] >= 1
    live_request, live_binding = saved[1023]
    before = state(cases, dataset)
    assert port.bind(live_request).encoded == live_binding.encoded
    same_state(cases, 'full-query-known-live-replay', before, state(cases, dataset), dataset)
    extra = request(p, 'quota-query-1024', dataset=dataset)
    unchanged(cases, 'query1025-atomic-capacity', lambda: port.bind(extra), dataset)
    unchanged(cases, 'expired-query-cannot-revive', lambda: port.bind(short_request), dataset, ('deadline',))
    released_request, _ = saved[1]
    unchanged(cases, 'released-query-cannot-revive', lambda: port.bind(released_request), dataset, ('expired_context',))
    forged = deepcopy(live_binding.value)
    forged['context']['pin']['lease_id'] = 'forged-quota-lease'
    unchanged(cases, 'full-quota-forged-lease', lambda: port.release_pin(contract('read_binding', forged)),
              dataset, ('unauthorized',))
    foreign = TrustedPrincipal(p.tenant_id, 'foreign-owner', 'foreign-session')
    unchanged(cases, 'full-quota-foreign-release', lambda: c.port(foreign).release_pin(live_binding),
              dataset, ('unauthorized',))
    bytes_before = counts(cases, dataset)['metadata_bytes']
    exact_release(cases, port, expired, 'full-query-expired-owner-release')
    exact_release(cases, port, expired, 'full-query-repeated-expired-release')
    cleanup = TrustedPrincipal(p.tenant_id, 'quota-cleanup', 'quota-cleanup-session', cleanup=True)
    exact_release(cases, c.port(cleanup), saved[2][1], 'full-query-trusted-cleanup-exact-release')
    expect(cases, dataset, queries=1024, metadata_bytes=bytes_before, operations=4, policy_epoch=2)
    unchanged(cases, 'release-does-not-free-query-identity', lambda: port.bind(extra), dataset)
    c.revoke(p, 'quota-query-revoke-owner', dataset, p.subject_id, p.delegation_ref)
    exact_release(cases, port, live_binding, 'full-query-revoked-owner-release')
    exact_release(cases, port, live_binding, 'full-query-repeated-revoked-release')
    expect(cases, dataset, queries=1024, grants=0, operations=5, policy_epoch=3)
    note(cases, 'actual1024-mixed-query-identities-and-exact-cleanup', dataset,
         expected_queries=1024, real_expiry_wait_seconds=waited, mixture_before_cleanup=mixture)


def dataset_capacity(cases):
    c, p = cases.catalog, cases.principal
    starting = cases.sql('SELECT count(*) AS n FROM gura_cf1a.datasets')[0]['n']
    assert 0 < starting < 16
    first = None
    for number in range(16 - starting):
        dataset = f'quota-dataset-fill-{number:02d}'
        result = c.provision(p, dataset + '-provision', dataset, p.subject_id)
        assert result.value['state'] == 'applied'
        if first is None:
            first = (dataset, result)
    global_state = state(cases)
    assert len(global_state['datasets']) == 16
    assert all(row['tenant'] == p.tenant_id for row in global_state['datasets'])
    assert all(sum(row['dataset'] == dataset['dataset'] and
                   row['operation_id'] == dataset['dataset'] + '-provision'
                   for row in global_state['operations']) == 1
               for dataset in global_state['datasets'])
    cases.reject('dataset17-atomic-capacity', lambda: c.provision(p, 'quota-dataset-17-provision',
                 'quota-dataset-17', p.subject_id), {'resource_limit'})
    same_state(cases, 'dataset17-no-partial-global-effect', global_state, state(cases), None)
    dataset, known = first
    assert c.provision(p, dataset + '-provision', dataset, p.subject_id).encoded == known.encoded
    assert c.admin_status(p, dataset + '-provision', dataset, 'provision',
                          {'owner_subject': p.subject_id}).encoded == known.encoded
    same_state(cases, 'full-dataset-known-provision-replay', global_state, state(cases), None)
    cases.event('actual16-global-datasets-known-provision-replay', state='pass', expected_datasets=16,
                independent_sql_sha256=sha(encoded(global_state)))


def remaining_capacities(cases):
    grant_capacity(cases)
    identity_capacity(cases)
    target_capacity(cases)
    query_capacity(cases)
    # No scenario after this point may create a new dataset. Restart only opens
    # an existing one; original512-op/8MiB scenarios have already run unchanged.
    dataset_capacity(cases)
