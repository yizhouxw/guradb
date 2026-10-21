"""Actual PG effects plus independent SQL truth, including private admin replay."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import time
from pathlib import Path
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_codec import contract
from modules.common.cf1a_primitives import ContractFailure, canonical, digest
from modules.common.cf1a_wire import Contract
from tests.catalog_support.fixed_fixture import GOLDEN, authorization, intents, request, target


class Cases:
    def __init__(self, catalog, authority, principal, dsn):
        self.catalog, self.authority, self.principal, self.dsn = catalog, authority, principal, dsn
        self.now = int(time.time() * 1000)
        self.trace = []
        self.inputs = []

    def sql(self, text, params=()):
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=2,
                             options='-c statement_timeout=3000') as conn:
            cursor = conn.execute(text, params)
            return cursor.fetchall() if cursor.description else []

    def event(self, name, **fields):
        self.trace.append({'sequence': len(self.trace), 'scenario': name, **fields})

    def reject(self, name, callback, codes):
        try:
            callback()
        except ContractFailure as error:
            assert error.code in codes, (name, error.code)
            self.event(name, state='rejected', code=error.code)
        else:
            raise AssertionError(name + ' succeeded')

    def prepare(self, dataset):
        c, p = self.catalog, self.principal
        c.provision(p, dataset + '-provision', dataset, p.subject_id)
        result = c.grant(p, dataset + '-grant', dataset, p.subject_id, p.delegation_ref,
                         ['read', 'register', 'publish', 'reconcile'], self.now + 300000)
        auth = authorization(p, int(time.time() * 1000), result.value['policy_epoch'], dataset=dataset)
        value = target(self.now, dataset=dataset)
        self.authority.allow(value)
        pair = intents(value, dataset + '-register', dataset + '-publish')
        self.inputs.append({'dataset': dataset, 'target': value.document, 'authorization': auth.document,
                            'intents': [item.document for item in pair]})
        return auth, value, pair

    def functional(self):
        c, p, dataset = self.catalog, self.principal, 'dataset-functional'
        auth, value, (reg, pub) = self.prepare(dataset)
        port = c.port(p)
        # A bytea domain probe only; the catalog does not store source ReadBatch rows.
        wire = canonical(GOLDEN[1])
        returned = bytes(self.sql('SELECT %s::bytea AS wire', (wire,))[0]['wire'])
        assert returned == wire and Contract(returned).value == GOLDEN[1]['payload']['read_batch']
        assert port.register(reg, auth, value).value['generation'] == 1
        self.reject('registered-not-bindable', lambda: port.bind(request(p, dataset=dataset)), {'conflict'})
        applied = port.publish(pub, auth, value)
        assert applied.value['state'] == 'applied' and applied.value['generation'] == 2
        commit = c.store.commit
        def lose_bind(conn):
            commit(conn)
            raise OSError('synthetic lost bind response after real COMMIT')
        with patch.object(c.store, 'commit', side_effect=lose_bind):
            self.reject('lost-bind-response', lambda: port.bind(request(p, dataset=dataset)), {'outcome_unknown'})
        stored = self.sql('SELECT binding,binding_sha256 FROM gura_cf1a.queries WHERE dataset=%s', (dataset,))[0]
        expected_binding = Contract(bytes(stored['binding']))
        assert stored['binding_sha256'] == expected_binding.sha256
        identities = self.sql('SELECT body FROM gura_cf1a.identities WHERE dataset=%s AND kind=%s', (dataset, 'resource'))
        assert b'\\u0000' in bytes(identities[0]['body'])
        rebuilt = target(self.now, 'view-b', generation=4, sequence=2, dataset=dataset)
        self.authority.allow(rebuilt)
        register, publish = intents(rebuilt, dataset + '-register-b', dataset + '-publish-b', 2, prior_view='view-a')
        assert port.register(register, auth, rebuilt).value['state'] == 'applied'
        assert port.publish(publish, auth, rebuilt).value['state'] == 'applied'
        binding = port.bind(request(p, dataset=dataset))
        assert binding.encoded == expected_binding.encoded and binding.value['context']['read_view_id'] == 'view-a'
        assert port.reauthorize(binding) == 2
        assert port.bind(request(p, 'new-query', dataset=dataset)).value['context']['read_view_id'] == 'view-b'
        self.authority.withdraw(value)
        assert port.publish(pub, auth, value).encoded == applied.encoded
        self.reject('withdrawn-protection-old-read', lambda: port.reauthorize(binding), {'revoked'})
        self.authority.allow(value)
        forged = binding.value; forged['context']['budget']['memory_bytes'] += 1
        self.reject('binding-budget-forgery', lambda: port.reauthorize(contract('read_binding', forged)), {'unauthorized'})
        expiry = c.grant(p, dataset + '-new-grant', dataset, p.subject_id, p.delegation_ref,
                        ['read', 'register', 'publish', 'reconcile'], self.now + 300000)
        assert expiry.value['policy_epoch'] == 3
        self.reject('grant-epoch-invalidates-old-bind', lambda: port.reauthorize(binding), {'revoked'})
        port.release_pin(binding); port.release_pin(binding)
        assert self.sql('SELECT released FROM gura_cf1a.queries WHERE dataset=%s AND query_id=%s',
                        (dataset, 'query-a'))[0]['released'] is True
        reader = TrustedPrincipal(p.tenant_id, 'reader', 'reader-session')
        c.grant(p, 'functional-reader-grant', dataset, reader.subject_id, reader.delegation_ref,
                ['read'], self.now + 300000)
        reader_port = c.port(reader)
        first = reader_port.bind(request(reader, 'reader-first', dataset=dataset))
        second = reader_port.bind(request(reader, 'reader-second', dataset=dataset))
        revoked = c.revoke(p, 'functional-reader-revoke', dataset, reader.subject_id, reader.delegation_ref)
        self.reject('revoked-reader-output', lambda: reader_port.reauthorize(first), {'unauthorized'})
        reader_port.release_pin(first)
        granted = c.grant(p, 'functional-reader-regrant', dataset, reader.subject_id, reader.delegation_ref,
                           ['read'], self.now + 300000)
        self.reject('regrant-does-not-revive-old-epoch', lambda: reader_port.reauthorize(second), {'revoked'})
        reader_port.release_pin(second)
        assert c.revoke(p, 'functional-reader-revoke', dataset, reader.subject_id, reader.delegation_ref).encoded == revoked.encoded
        current = reader_port.bind(request(reader, 'reader-current', dataset=dataset))
        assert reader_port.reauthorize(current) == granted.value['policy_epoch']
        reader_port.release_pin(current)
        self.event('full-target-fixed-views-canonical-and-cleanup', state='pass', dataset=dataset,
                   raw_binding_sha256=binding.sha256)
        return binding

    def race_and_fence(self):
        dataset, p = 'dataset-race', self.principal
        auth, first, _ = self.prepare(dataset)
        second = target(self.now, 'view-b', dataset=dataset)
        self.authority.allow(second)
        proposals = [(first, intents(first, 'race-register-a', 'race-publish-a')[0]),
                     (second, intents(second, 'race-register-b', 'race-publish-b')[0])]
        def register(pair):
            value, intent = pair
            return self.catalog.port(p).register(intent, auth, value)
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(register, proposals))
        assert sorted(r.value['state'] for r in receipts) == ['applied', 'rejected']
        row = self.sql('SELECT generation,active_plan FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]
        assert row['generation'] == 1
        winner = next(value for value, _ in proposals if value.value['view']['read_view_id'] == row['active_plan'])
        register_id = next(intent.value['operation_id'] for value, intent in proposals if value is winner)
        _, pub = intents(winner, register_id, 'race-publish-final')
        rotated = self.catalog.rotate_owner(p, 'race-rotate', dataset, p.subject_id)
        refreshed = pub.value; refreshed['owner_epoch'] = rotated.value['owner_epoch']
        rejected = self.catalog.port(p).publish(contract('publish_intent', refreshed), auth, winner)
        assert rejected.value['state'] == 'rejected'
        row = self.sql('SELECT generation,published,active_plan FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]
        assert row == {'generation': 1, 'published': '', 'active_plan': ''}
        self.event('concurrent-cas-and-refreshed-owner-fenced-plan', state='pass', receipts=[r.document for r in receipts])

    def admin_and_unknown(self):
        dataset, p, c = 'dataset-unknown', self.principal, self.catalog
        auth, value, (reg, pub) = self.prepare(dataset)
        commit = c.store.commit
        def lose_after(conn):
            commit(conn)
            raise OSError('synthetic response loss after real COMMIT')
        with patch.object(c.store, 'commit', side_effect=lose_after):
            assert c.port(p).register(reg, auth, value).value['state'] == 'outcome_unknown'
        assert self.sql('SELECT generation FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]['generation'] == 1
        assert c.port(p).reconcile(reg, auth).value['state'] == 'applied'
        with patch.object(c.store, 'commit', side_effect=OSError('synthetic before send COMMIT')):
            assert c.port(p).publish(pub, auth, value).value['state'] == 'outcome_unknown'
        assert self.sql('SELECT published FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]['published'] == ''
        tombstone = c.port(p).reconcile(pub, auth)
        assert tombstone.value['state'] == 'rejected'
        assert c.port(p).publish(pub, auth, value).encoded == tombstone.encoded
        c.grant(p, 'unknown-grant-reader', dataset, 'reader', 'reader-session', ['read'], self.now + 90000)
        with patch.object(c.store, 'commit', side_effect=lose_after):
            assert c.revoke(p, 'unknown-revoke', dataset, 'reader', 'reader-session').value['state'] == 'outcome_unknown'
        parameters = {'subject_id': 'reader', 'delegation_ref': 'reader-session'}
        result = c.admin_status(p, 'unknown-revoke', dataset, 'revoke', parameters)
        assert result.value['state'] == 'applied'
        c.grant(p, 'unknown-regrant', dataset, 'reader', 'reader-session', ['read'], self.now + 90000)
        epoch = self.sql('SELECT policy_epoch FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]['policy_epoch']
        assert c.revoke(p, 'unknown-revoke', dataset, 'reader', 'reader-session').encoded == result.encoded
        assert self.sql('SELECT policy_epoch FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]['policy_epoch'] == epoch
        assert len(self.sql('SELECT subject FROM gura_cf1a.grants WHERE dataset=%s AND subject=%s', (dataset, 'reader'))) == 1
        assert c.admin_status(p, 'absent-revoke', dataset, 'revoke', parameters).value['state'] == 'outcome_unknown'
        self.reject('admin-replay-parameter-conflict', lambda: c.revoke(p, 'unknown-revoke', dataset,
                    'other-reader', 'reader-session'), {'conflict'})
        other = TrustedPrincipal(p.tenant_id, 'other-admin', 'other-session', administrator=True)
        self.reject('admin-replay-principal-conflict', lambda: c.revoke(other, 'unknown-revoke', dataset,
                    'reader', 'reader-session'), {'conflict'})
        self.event('real-commit-unknown-admin-and-cf1', state='pass', admin_result_sha256=sha_bytes(result.encoded))

    def capacity(self):
        dataset, p, c = 'dataset-capacity', self.principal, self.catalog
        self.prepare(dataset)
        # Fill by actual adapter side effects, including shared CF1/admin receipts.
        target_value = target(self.now, dataset=dataset)
        reg, _ = intents(target_value, 'capacity-register', 'capacity-publish')
        auth = authorization(p, self.now, dataset=dataset)
        assert c.port(p).register(reg, auth, target_value).value['state'] == 'applied'
        while True:
            count = self.sql('SELECT count(*) AS n FROM gura_cf1a.operations WHERE dataset=%s', (dataset,))[0]['n']
            if count == 512:
                break
            c.revoke(p, 'capacity-revoke-' + str(count), dataset, 'absent-reader', 'absent-session')
        first = c.admin_status(p, dataset + '-provision', dataset, 'provision', {'owner_subject': p.subject_id})
        assert first.value['state'] == 'applied'
        self.reject('shared-512-operation-capacity', lambda: c.revoke(p, 'over-capacity', dataset,
                    'absent-reader', 'absent-session'), {'resource_limit'})
        assert self.sql('SELECT count(*) AS n FROM gura_cf1a.operations WHERE dataset=%s', (dataset,))[0]['n'] == 512
        epoch = self.sql('SELECT policy_epoch FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]['policy_epoch']
        assert c.port(p).register(reg, authorization(p, self.now, epoch, dataset=dataset), target_value).value['state'] == 'applied'
        self.event('shared-admin-cf1-512-receipt-capacity', state='pass', actual_operations=512)

    def byte_capacity(self):
        dataset, c, p = 'dataset-bytes', self.catalog, self.principal
        auth, first, _ = self.prepare(dataset)
        value = first.value
        base = value['indexes'][0]['shards'][0]
        value['indexes'][0]['shards'] = [{**base, 'key': 'large-' + str(i) + '-' + 'x' * 3800} for i in range(128)]
        value['indexes'][0]['shard_count'] = 128
        large = contract('read_descriptors', value)
        artifact = deepcopy(large.value['indexes'])
        previous, generation, sequence, accepted = '', 0, 1, 0
        while accepted < 20:
            content = target(self.now, 'byte-view-' + str(sequence), generation=generation + 2,
                             sequence=sequence, dataset=dataset).value
            content['indexes'] = artifact
            content['view']['required_artifact_ids'] = [artifact[0]['artifact_id']]
            content['view']['index_requirements'] = large.value['view']['index_requirements']
            from modules.common.cf1a_read import without
            content['view']['descriptor_sha256'] = digest(without(content['view'], 'descriptor_sha256'))
            candidate = contract('read_descriptors', content)
            self.inputs.append({'dataset': dataset, 'target': candidate.document})
            self.authority.allow(candidate)
            reg, pub = intents(candidate, 'byte-register-' + str(sequence), 'byte-publish-' + str(sequence),
                               generation, prior_view=previous)
            try:
                result = c.port(p).register(reg, auth, candidate)
            except ContractFailure as error:
                assert error.code == 'resource_limit'
                break
            assert result.value['state'] == 'applied'
            generation += 1
            try:
                assert c.port(p).publish(pub, auth, candidate).value['state'] == 'applied'
            except ContractFailure as error:
                assert error.code == 'resource_limit'
                break
            previous = content['view']['read_view_id']
            generation += 1; sequence += 1; accepted += 1
        assert 0 < accepted < 20
        row = self.sql('SELECT generation,metadata_bytes FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]
        assert row['generation'] == generation and row['metadata_bytes'] <= 8 << 20
        self.event('actual-canonical-byte-capacity', state='pass', accepted_views=accepted, **row)

    def fresh_time_and_expired_cleanup(self):
        dataset, p, c = 'dataset-time', self.principal, self.catalog
        _, value, (reg, pub) = self.prepare(dataset)
        now = self.sql('SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS ms')[0]['ms']
        short_auth = authorization(p, self.now, dataset=dataset).value
        short_auth['expires_unix_ms'] = now + 40
        original = self.authority.verify
        def slow(*args):
            original(*args)
            time.sleep(.08)
        with patch.object(self.authority, 'verify', side_effect=slow):
            self.reject('authority-time-consumes-auth-expiry', lambda: c.port(p).register(
                reg, contract('mutation_auth', short_auth), value), {'expired_context'})
        assert self.sql('SELECT generation FROM gura_cf1a.datasets WHERE dataset=%s', (dataset,))[0]['generation'] == 0
        auth = authorization(p, self.now, dataset=dataset)
        assert c.port(p).register(reg, auth, value).value['state'] == 'applied'
        assert c.port(p).publish(pub, auth, value).value['state'] == 'applied'
        binding = c.port(p).bind(request(p, timeout_ms=150, dataset=dataset))
        time.sleep(.17)
        self.reject('expired-binding-retry', lambda: c.port(p).bind(request(p, timeout_ms=150, dataset=dataset)), {'deadline'})
        c.port(p).release_pin(binding)
        assert self.sql('SELECT released FROM gura_cf1a.queries WHERE dataset=%s', (dataset,))[0]['released'] is True
        self.event('expired-exact-lease-cleanup', state='pass')

    def audit_metadata(self):
        results = []
        for row in self.sql('SELECT dataset,metadata_bytes FROM gura_cf1a.datasets'):
            actual = 0
            for table in ('identities', 'grants', 'targets'):
                actual += self.sql('SELECT COALESCE(sum(octet_length(body)),0) AS n FROM gura_cf1a.' +
                                   table + ' WHERE dataset=%s', (row['dataset'],))[0]['n']
            for table, first, second in (('operations', 'intent', 'receipt'), ('queries', 'request', 'binding')):
                actual += self.sql('SELECT COALESCE(sum(octet_length(' + first + ')+octet_length(' + second +
                                   ')),0) AS n FROM gura_cf1a.' + table + ' WHERE dataset=%s', (row['dataset'],))[0]['n']
            assert actual == row['metadata_bytes'] and actual <= 8 << 20
            results.append({'dataset': row['dataset'], 'canonical_bytes': actual})
        self.event('independent-all-dataset-byte-accounting', state='pass', datasets=results)

    def dump(self, output):
        directory = Path(output) / 'pg-canonical-records'
        directory.mkdir()
        manifest = []
        for table, bodies in (('identities', ['body']), ('grants', ['body']), ('targets', ['body']),
                              ('operations', ['intent', 'receipt']), ('queries', ['request', 'binding'])):
            rows = self.sql('SELECT * FROM gura_cf1a.' + table + ' ORDER BY dataset')
            for ordinal, row in enumerate(rows):
                for column in bodies:
                    raw = bytes(row[column])
                    path = directory / (table + '-' + str(ordinal) + '-' + column + '.json')
                    path.write_bytes(raw)
                    row[column] = {'path': path.relative_to(output).as_posix(),
                                   'size_bytes': len(raw), 'sha256': sha_bytes(raw)}
                manifest.append({'table': table, 'row': row})
        return manifest


def sha_bytes(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()
