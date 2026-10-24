"""C3 real PG failure composition; injected loss is labeled separately from PG stop."""
from contextlib import contextmanager
import threading
import time
from unittest.mock import patch

import psycopg

from modules.common.cf1a_primitives import ContractFailure
from modules.storage.fixed_cache import VerifiedCache
from tests.source_support.fixed_evidence import error_record, write
from tests.source_support.fixed_catalog_pair import PairQuery, query_row


class RefusalMismatch(AssertionError):
    def __init__(self, expected, observed):
        self.expected, self.observed = expected, observed
        super().__init__('pair refusal differs from exact expected code')


def refused(callback, expected):
    started = time.monotonic()
    try:
        callback()
    except ContractFailure as error:
        if error.code != expected:
            raise RefusalMismatch(expected, error.code) from None
    else:
        raise RefusalMismatch(expected, 'success')
    return {'code': expected, 'elapsed_ms': (time.monotonic() - started) * 1000}


def cases(catalog, principal, fixtures, endpoint, directory, pg, docker):
    records = []
    fixture, dataset = fixtures['dual130']

    @contextmanager
    def owned(name, **arguments):
        query = PairQuery(catalog, principal, fixture, dataset, endpoint, directory/name, **arguments)
        record = {'case': name, 'passed': False}
        try:
            yield query, record
            record['passed'] = True
        except BaseException as error:
            record['primary_error'] = error_record(error)
            if isinstance(error, RefusalMismatch):
                record['refusal_mismatch'] = {'expected': error.expected, 'observed': error.observed}
            raise
        finally:
            try:
                record['cleanup'] = query.finish()
            finally:
                record['invoice'] = query.parent.invoice
                records.append(record)
                write(directory/'fault-journal.json', records)

    with owned('prebind-expired', timeout_ms=1) as (query, record):
        time.sleep(.005)
        record.update(refused(query.bind, 'deadline'))
        assert query.binding is None
        assert query.parent.invoice['execution'] is None
        assert query.finish()['state'] == 'cleanup_unconfirmed'
        record['rebind'] = refused(query.bind, 'expired_context')

    with owned('cached-next-page-revoked') as (query, record):
        reader = query.bind()
        first = reader.port.read_batch(query.binding, 0)
        assert len(first.value['rows']) == 64
        before = reader.scope.usage()
        catalog.revoke(principal, 'revoke-c3-next-page', dataset, principal.subject_id, principal.delegation_ref)
        record['refusal'] = refused(lambda: reader.port.read_batch(query.binding, 1), 'unauthorized')
        assert reader.scope.output_bytes == before['output_bytes']
        assert reader.scope.object_requests == before['object_requests']
    catalog.grant(principal, 'regrant-c3-next-page', dataset, principal.subject_id, principal.delegation_ref,
                  ['read', 'register', 'publish', 'reconcile'], time.time_ns() // 1_000_000 + 300000)

    with owned('page-pg-row-lock') as (query, record):
        reader = query.bind()
        with psycopg.connect(catalog.store.dsn, connect_timeout=2) as locker:
            locker.execute('SELECT dataset FROM gura_cf1a.datasets WHERE dataset=%s FOR UPDATE', (dataset,))
            record['refusal'] = refused(lambda: reader.port.read_batch(query.binding, 0), 'deadline')
            locker.rollback()
        assert reader.scope.output_bytes == 0 and reader.scope.object_requests == 0
        assert 800 <= record['refusal']['elapsed_ms'] <= 1100

    cancelled = threading.Event()
    with owned('page-pg-pause-cancel', cancelled=cancelled.is_set) as (query, record):
        reader = query.bind()
        docker('pause', pg)
        timer = threading.Timer(.05, cancelled.set)
        timer.start()
        try:
            record['refusal'] = refused(lambda: reader.port.read_batch(query.binding, 0), 'cancelled')
            assert reader.scope.output_bytes == 0 and reader.scope.object_requests == 0
            assert record['refusal']['elapsed_ms'] <= 150
        finally:
            docker('unpause', pg, check=False)
            timer.join(1)
            cancelled.clear()

    for found in (True, False):
        with owned('unknown-found' if found else 'unknown-absent') as (query, record):
            original = catalog.store.commit
            def lost(connection):
                if found:
                    original(connection)
                raise OSError('injected commit response loss')
            with patch.object(catalog.store, 'commit', side_effect=lost):
                record['refusal'] = refused(query.bind, 'outcome_unknown')
            assert query.binding is None
            cleanup = query.finish()
            assert cleanup['state'] == ('released' if found else 'cleanup_unconfirmed')
            record['rebind'] = refused(query.bind, 'outcome_unknown')
            record['injection'] = 'real PG commit response loss' if found else 'pre-commit injected loss/rollback'
            row = query_row(catalog.store.dsn, dataset, query.request.value['query_id'])
            assert (row is not None and row[1] is True) if found else row is None

    cache = VerifiedCache(256 << 10)
    with owned('prime-cache-final-revoke', cache=cache) as (query, record):
        reader = query.bind()
        reader.port.read_batch(query.binding, 0)
    with owned('cache-hit-final-revoke', cache=cache) as (query, record):
        reader = query.bind()
        original, revoked = cache.get, []
        def revoke_after_hit(key):
            raw = original(key)
            if raw is not None and not revoked:
                catalog.revoke(principal, 'revoke-c3-final', dataset,
                               principal.subject_id, principal.delegation_ref)
                revoked.append(True)
            return raw
        with patch.object(cache, 'get', side_effect=revoke_after_hit):
            record['refusal'] = refused(lambda: reader.port.read_batch(query.binding, 0), 'unauthorized')
        assert revoked and reader.scope.object_requests == reader.scope.output_bytes == 0
    catalog.grant(principal, 'regrant-c3-final', dataset, principal.subject_id, principal.delegation_ref,
                  ['read', 'register', 'publish', 'reconcile'], time.time_ns() // 1_000_000 + 300000)

    with owned('pg-authorized-late-object') as (query, record):
        from modules.storage import fixed_objects
        reader = query.bind()
        original = fixed_objects.fetch
        def late(*arguments):
            raw = original(*arguments)
            time.sleep(1.01)
            return raw
        with patch.object(fixed_objects, 'fetch', side_effect=late):
            record['refusal'] = refused(lambda: reader.port.read_batch(query.binding, 0), 'deadline')
        assert reader.scope.output_bytes == 0 and reader.scope.object_requests == 1
        record['injection'] = 'actual fixed GET then delayed callback return, not server stop proof'

    # Damage actual fixed object in the real GET return path, after PG authorization.
    with owned('pg-authorized-corrupt-object') as (query, record):
        from modules.storage import fixed_objects
        reader = query.bind()
        original = fixed_objects.fetch
        def damaged(*arguments):
            raw = original(*arguments)
            return bytes([raw[0] ^ 1]) + raw[1:]
        with patch.object(fixed_objects, 'fetch', side_effect=damaged):
            record['refusal'] = refused(lambda: reader.port.read_batch(query.binding, 0), 'corrupt_object')
        assert reader.scope.output_bytes == 0 and reader.scope.object_requests == 1
        assert query.control.invoice['counts']['sql_success'] > 0
        record['injection'] = 'real fixed GET bytes changed after transport; not server corruption'
    return records
