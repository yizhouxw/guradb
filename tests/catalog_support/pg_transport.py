"""Actual blackhole, paused PG and held-row-lock whole-deadline checks."""
import socket
import threading
import time
from unittest.mock import patch
import psycopg
from modules.catalog.cf1a_auth import FixedInputAuthority
from modules.catalog.cf1a_catalog import FixedCatalog
from modules.catalog.cf1a_pg import connect
from modules.common.cf1a_primitives import ContractFailure
from tests.catalog_support.fixed_fixture import request


def timed_refusal(callback):
    started = time.monotonic()
    try:
        callback()
    except ContractFailure as error:
        assert error.code == 'deadline', error.code
    else:
        raise AssertionError('deadline operation returned success')
    elapsed = (time.monotonic() - started) * 1000
    assert 40 <= elapsed <= 150, elapsed
    return {'elapsed_ms': elapsed, 'admission_budget_ms': 100,
            'return_lateness_tolerance_ms': 50}


def blackhole(principal):
    accepted, received, eof_times = [], [], []
    stop, peer_eof = threading.Event(), threading.Event()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(1)
    listener.settimeout(.5)
    def serve():
        try:
            conn, _ = listener.accept()
            accepted.append(conn)
            conn.settimeout(.2)
            while not stop.is_set():
                try:
                    raw = conn.recv(4096)
                    if not raw:
                        eof_times.append(time.monotonic())
                        peer_eof.set()
                        return
                    received.append(len(raw))
                except socket.timeout:
                    continue
        finally:
            for conn in accepted:
                conn.close()
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        dsn = f'host=127.0.0.1 port={listener.getsockname()[1]} dbname=blackhole user=fixture sslmode=disable'
        catalog = FixedCatalog(dsn, FixedInputAuthority())
        req = request(principal, timeout_ms=100)
        started = time.monotonic()
        timing = timed_refusal(lambda: catalog.port(principal).bind(req))
        # Observe EOF from the client before any stop/close by this fixture.
        assert peer_eof.wait(max(0, started + .150 - time.monotonic())), 'client did not close startup socket'
        eof_ms = (eof_times[0] - started) * 1000
        assert eof_ms <= 150
    finally:
        stop.set(); listener.close(); worker.join(1)
    assert accepted and received and not worker.is_alive()
    return {'scenario': 'blackhole-startup-packet', **timing, 'peer_eof_ms': eof_ms,
            'peer_eof_before_fixture_stop': True, 'actual_startup_bytes': sum(received),
            'listener_thread_closed': True}


def paused_and_locked(catalog, principal, dsn, container, docker):
    records = []
    conn = connect(catalog.store.dsn, time.monotonic() + 2)
    conn.execute('SELECT 1')
    try:
        docker('pause', container)
        conn.deadline = time.monotonic() + .1
        timing = timed_refusal(lambda: conn.execute('SELECT 1'))
        assert conn.closed
        records.append({'scenario': 'paused-existing-sql', **timing, 'connection_closed': True})
    finally:
        docker('unpause', container, check=False)
        conn.close()
    with psycopg.connect(dsn, connect_timeout=2) as owner:
        owner.execute('SELECT dataset FROM gura_cf1a.datasets WHERE dataset=%s FOR UPDATE', ('dataset-functional',))
        req = request(principal, 'lock-wait-query', timeout_ms=100, dataset='dataset-functional')
        timing = timed_refusal(lambda: catalog.port(principal).bind(req))
        owner.rollback()
    records.append({'scenario': 'held-dataset-row-lock', **timing})
    records.append(paused_commit(catalog, principal, dsn, container, docker))
    return records


def paused_commit(catalog, principal, dsn, container, docker):
    """Real libpq COMMIT wait; server resume occurs after measuring client return."""
    dataset, operation = 'dataset-functional', 'paused-commit-revoke'
    with psycopg.connect(dsn, connect_timeout=2) as independent:
        before = independent.execute('SELECT policy_epoch FROM gura_cf1a.datasets WHERE dataset=%s',
                                     (dataset,)).fetchone()[0]
    original = catalog.store.commit
    phase, owned = {}, []
    started = time.monotonic()
    def pause_then_commit(conn):
        owned.append(conn)
        phase['commit_entered_ms'] = (time.monotonic() - started) * 1000
        docker('pause', container)
        phase['server_paused_before_commit_ms'] = (time.monotonic() - started) * 1000
        phase['connection_deadline_monotonic'] = conn.deadline
        phase['remaining_before_real_commit_ms'] = (conn.deadline - time.monotonic()) * 1000
        phase['entered_real_commit'] = True
        try:
            original(conn)
        finally:
            phase['commit_wait_return_ms'] = (time.monotonic() - started) * 1000
    try:
        with patch.object(catalog.store, 'commit', side_effect=pause_then_commit):
            result = catalog.revoke(principal, operation, dataset, 'absent-commit-reader', 'absent-commit-session')
        elapsed = (time.monotonic() - started) * 1000
        # These driver assertions must stay outside the transaction's unknown
        # conversion; an injection failure cannot prove that COMMIT was sent.
        assert phase.get('entered_real_commit') is True
        assert phase['remaining_before_real_commit_ms'] >= 25, 'injection consumed the commit wait budget'
        assert result.value['state'] == 'outcome_unknown'
        assert len(owned) == 1 and owned[0].closed
        assert 4500 <= elapsed <= 5050, elapsed
        phase['client_return_ms'] = elapsed
    finally:
        resumed = time.monotonic()
        docker('unpause', container, check=False)
        phase['service_resume_injection_ms'] = (time.monotonic() - resumed) * 1000
    with psycopg.connect(dsn, connect_timeout=2) as independent:
        count = independent.execute('SELECT count(*) FROM gura_cf1a.operations WHERE dataset=%s AND operation_id=%s',
                                    (dataset, operation)).fetchone()[0]
        epoch = independent.execute('SELECT policy_epoch FROM gura_cf1a.datasets WHERE dataset=%s',
                                    (dataset,)).fetchone()[0]
    assert count in (0, 1) and epoch == before + count
    replay = catalog.revoke(principal, operation, dataset, 'absent-commit-reader', 'absent-commit-session')
    assert catalog.revoke(principal, operation, dataset, 'absent-commit-reader', 'absent-commit-session').encoded == replay.encoded
    with psycopg.connect(dsn, connect_timeout=2) as independent:
        assert independent.execute('SELECT count(*) FROM gura_cf1a.operations WHERE dataset=%s AND operation_id=%s',
                                   (dataset, operation)).fetchone()[0] == 1
        assert independent.execute('SELECT policy_epoch FROM gura_cf1a.datasets WHERE dataset=%s',
                                   (dataset,)).fetchone()[0] == before + 1
    return {'scenario': 'paused-real-commit', 'state': 'outcome_unknown', 'connection_closed': True,
            'admission_budget_ms': 5000, 'return_lateness_tolerance_ms': 50,
            'receipt_count_after_resume': count, 'same_intent_final_receipt_count': 1, **phase}
