"""Atomic fixed-view issuance and exact persisted lease reauthorization/cleanup."""
import time
import uuid
from modules.common.cf1a_primitives import ContractFailure, require
from modules.common.cf1a_read import validate_access
from modules.catalog.cf1a_access import live_grant, principal_for
from modules.catalog.cf1a_codec import contract, stored_contract
from modules.catalog.cf1a_pg import remaining
from modules.catalog.cf1a_store import CommitUnknown


class Bindings:
    def __init__(self, store):
        self.store = store

    def stored(self, conn, dataset, query_id):
        row = conn.execute('SELECT * FROM gura_cf1a.queries WHERE dataset=%s AND query_id=%s',
                           (dataset, query_id)).fetchone()
        require(row is not None, 'query lease unavailable', 'unauthorized')
        request = stored_contract(row['request'], row['request_sha256'], 'bind_request')
        binding = stored_contract(row['binding'], row['binding_sha256'], 'read_binding')
        context, value = binding.value['context'], request.value
        require(context['dataset_id'] == value['dataset_id'] == dataset and
                context['query_id'] == value['query_id'] == query_id and
                context['auth']['subject_id'] == value['subject_id'] == row['subject'] and
                context['auth']['delegation_ref'] == value['delegation_ref'] == row['delegation'] and
                context['pin']['pin_id'] == row['pin_id'] and context['pin']['lease_id'] == row['lease_id'] and
                context['pin']['expires_unix_ms'] == row['expires_unix_ms'] and type(row['released']) is bool,
                'stored query/lease lookup mismatch')
        for name in ('request_id', 'budget', 'cancellation_id', 'trace_id', 'span_id'):
            require(context[name] == value[name], 'stored query/request mismatch')
        require(context['tenant_id'] == value['tenant_id'] and context['remaining_ttl_ms'] <= value['timeout_ms'] and
                (value['view_mode'] == 'published' or value['read_view_id'] == context['read_view_id']),
                'stored view selector mismatch')
        return row, request, binding

    def current(self, conn, row, principal, binding, deadline):
        value = binding.value
        context = value['context']
        principal_for(principal, row['tenant'])
        require(context['auth']['subject_id'] == principal.subject_id and
                context['auth']['delegation_ref'] == principal.delegation_ref, 'query belongs to another principal', 'unauthorized')
        now = self.store.now(conn)
        live_grant(conn, row, principal, ['read'], now)
        validate_access(value, now, row['policy_epoch'])
        target_row, target = self.store.target(conn, row['tenant'], row['dataset'], context['read_view_id'])
        require(target_row['state'] == 'published' and
                all(value[name] == target.value[name] for name in ('resource', 'revision', 'view', 'indexes')),
                'query no longer identifies retained published target', 'unauthorized')
        self.store.protection.verify(target, now, context['pin']['expires_unix_ms'])
        remaining(deadline)
        validate_access(value, self.store.now(conn), row['policy_epoch'])
        return row['policy_epoch']

    def bind(self, principal, request):
        require(request.kind == 'bind_request', 'expected BindRequest')
        value = request.value
        principal_for(principal, value['tenant_id'])
        require(value['subject_id'] == principal.subject_id and value['delegation_ref'] == principal.delegation_ref,
                'bind request does not authenticate subject', 'unauthorized')
        deadline = time.monotonic() + value['timeout_ms'] / 1000
        try:
            with self.store.transaction(deadline) as conn:
                row = self.store.dataset(conn, value['tenant_id'], value['dataset_id'])
                old = conn.execute('SELECT query_id FROM gura_cf1a.queries WHERE dataset=%s AND query_id=%s',
                                   (value['dataset_id'], value['query_id'])).fetchone()
                if old is not None:
                    query, original, binding = self.stored(conn, value['dataset_id'], value['query_id'])
                    require(original.sha256 == request.sha256 and original.encoded == request.encoded,
                            'query ID reused with different complete request', 'conflict')
                    require(not query['released'], 'released query identity cannot revive', 'expired_context')
                    self.current(conn, row, principal, binding, deadline)
                    return binding
                now = self.store.now(conn)
                grant = live_grant(conn, row, principal, ['read'], now)
                selected = row['published'] if value['view_mode'] == 'published' else value['read_view_id']
                require(bool(selected), 'no published read view', 'conflict')
                target_row, target = self.store.target(conn, row['tenant'], row['dataset'], selected)
                require(target_row['state'] == 'published', 'target is not published', 'conflict')
                until = now + min(value['timeout_ms'], int(remaining(deadline) * 1000))
                self.store.protection.verify(target, now, until)
                now = self.store.now(conn)
                ttl = min(value['timeout_ms'], int(remaining(deadline) * 1000))
                require(ttl > 0, 'bind deadline reached', 'deadline')
                expires = now + ttl
                require(grant['expires_unix_ms'] >= expires and
                        all(source['protected_until_unix_ms'] >= expires for source in target.value['revision']['sources']),
                        'authority/grant cannot protect complete query lease', 'expired_context')
                context = {name: value[name] for name in ('request_id', 'query_id', 'tenant_id', 'dataset_id',
                                                         'budget', 'cancellation_id', 'trace_id', 'span_id')}
                resource, revision = target.value['resource'], target.value['revision']
                context.update(schema_id=resource['schema_id'], schema_version=resource['schema_version'],
                    data_revision_id=revision['data_revision_id'], read_view_id=selected,
                    source_version_ids=[source['source_version_id'] for source in revision['sources']],
                    artifact_ids=target.value['view']['required_artifact_ids'], bound_at_unix_ms=now,
                    deadline_unix_ms=expires, remaining_ttl_ms=ttl,
                    auth={'tenant_id': value['tenant_id'], 'dataset_id': value['dataset_id'],
                          'subject_id': principal.subject_id, 'actions': ['read'], 'policy_epoch': row['policy_epoch'],
                          'expires_unix_ms': grant['expires_unix_ms'], 'delegation_ref': principal.delegation_ref},
                    pin={'pin_id': 'pin-' + uuid.uuid4().hex, 'lease_id': 'lease-' + uuid.uuid4().hex,
                         'data_revision_id': revision['data_revision_id'], 'read_view_id': selected,
                         'expires_unix_ms': expires})
                binding = contract('read_binding', {**target.value, 'context': context})
                self.store.quota(conn, row['dataset'], 'queries')
                self.store.charge(conn, row['dataset'], len(request.encoded) + len(binding.encoded))
                conn.execute('INSERT INTO gura_cf1a.queries(dataset,query_id,subject,delegation,request,request_sha256,'
                    'binding,binding_sha256,pin_id,lease_id,expires_unix_ms) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (row['dataset'], value['query_id'], principal.subject_id, principal.delegation_ref,
                     request.encoded, request.sha256, binding.encoded, binding.sha256,
                     context['pin']['pin_id'], context['pin']['lease_id'], expires))
                remaining(deadline)
                validate_access(binding.value, self.store.now(conn), row['policy_epoch'])
                return binding
        except CommitUnknown:
            raise ContractFailure('outcome_unknown', 'retry identical BindRequest/query ID to recover issued lease') from None

    def reauthorize(self, principal, binding):
        require(binding.kind == 'read_binding', 'expected issued ReadBinding')
        context = binding.value['context']
        # Keep this operation inside the original fixed query deadline.
        wall_remaining = context['deadline_unix_ms'] - int(time.time() * 1000)
        require(wall_remaining > 0, 'query deadline reached', 'deadline')
        deadline = time.monotonic() + min(5000, wall_remaining) / 1000
        try:
            with self.store.transaction(deadline) as conn:
                row = self.store.dataset(conn, context['tenant_id'], context['dataset_id'])
                query, _, issued = self.stored(conn, row['dataset'], context['query_id'])
                require(issued.encoded == binding.encoded, 'binding differs from issued immutable bytes', 'unauthorized')
                require(not query['released'], 'query lease released', 'expired_context')
                return self.current(conn, row, principal, binding, deadline)
        except CommitUnknown:
            raise ContractFailure('backend_unavailable', 'reauthorization result not confirmed') from None

    def release(self, principal, binding):
        require(binding.kind == 'read_binding', 'expected issued ReadBinding')
        context = binding.value['context']
        principal_for(principal, context['tenant_id'])
        try:
            with self.store.transaction(time.monotonic() + 5) as conn:
                row = self.store.dataset(conn, context['tenant_id'], context['dataset_id'])
                query, _, issued = self.stored(conn, row['dataset'], context['query_id'])
                require(issued.encoded == binding.encoded, 'cleanup must match exact issued binding', 'unauthorized')
                require(principal.cleanup or (query['subject'] == principal.subject_id and
                        query['delegation'] == principal.delegation_ref), 'not exact lease owner/cleanup', 'unauthorized')
                if not query['released']:
                    conn.execute('UPDATE gura_cf1a.queries SET released=true WHERE dataset=%s AND query_id=%s',
                                 (row['dataset'], context['query_id']))
        except CommitUnknown:
            raise ContractFailure('outcome_unknown', 'retry the same exact binding/lease release') from None
