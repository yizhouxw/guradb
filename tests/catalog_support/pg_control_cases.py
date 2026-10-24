"""C1 real PG control, independent SQL and bounded whole-call observations."""
from contextlib import contextmanager
from dataclasses import asdict
import json
import socket
import threading
import time
from unittest.mock import patch

import psycopg
from modules.catalog import cf1a_pg
from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_codec import contract
from modules.catalog.cf1a_control import CatalogReadControl
from modules.common.cf1a_primitives import ContractFailure
from tests.catalog_support.fixed_fixture import request


class Parent:
    def __init__(self, milliseconds):
        self.started = time.monotonic()
        self.deadline = self.started + milliseconds / 1000
        self.child = self.deadline
        self.cancelled = threading.Event()
        self.control = CatalogReadControl(self.checkpoint, time.monotonic)

    def checkpoint(self):
        if self.cancelled.is_set():
            raise ContractFailure('cancelled', 'parent cancelled')
        return min(self.deadline, self.child)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n')


class ControlCases:
    def __init__(self, cases, directory):
        self.cases, self.directory, self.records = cases, directory, []
        self.catalog, self.admin = cases.catalog, cases.principal
        self.reader = TrustedPrincipal(self.admin.tenant_id, 'controlled-reader', 'controlled-session')
        self.dataset = 'dataset-controlled'
        auth, target, (reg, pub) = cases.prepare(self.dataset)
        self.target = target
        self.catalog.port(self.admin).register(reg, auth, target)
        self.catalog.port(self.admin).publish(pub, auth, target)
        self.grant('control-grant')

    def grant(self, operation):
        return self.catalog.grant(self.admin, operation, self.dataset, self.reader.subject_id,
            self.reader.delegation_ref, ['read'], time.time_ns() // 1_000_000 + 300000)

    def req(self, query, timeout=1000):
        value = request(self.reader, query, timeout_ms=timeout, dataset=self.dataset)
        self.cases.inputs.append({'controlled_request': value.document})
        return value

    def row(self, query):
        return self.cases.sql('SELECT * FROM gura_cf1a.queries WHERE dataset=%s AND query_id=%s',
                              (self.dataset, query))

    def state(self):
        return self.cases.sql('SELECT generation,policy_epoch,owner_epoch,metadata_bytes FROM gura_cf1a.datasets '
                              'WHERE dataset=%s', (self.dataset,))

    @contextmanager
    def case(self, name, parent=None):
        record = {'scenario': name, 'passed': False, 'started_monotonic': time.monotonic()}
        try:
            yield record
            record['passed'] = True
        except BaseException as error:
            record['error_type'] = type(error).__name__
            record['error_code'] = error.code if isinstance(error, ContractFailure) else None
            raise
        finally:
            record['returned_monotonic'] = time.monotonic()
            if parent is not None:
                record['parent_started'] = parent.started
                record['parent_deadline'] = parent.deadline
                record['invoice'] = parent.control.invoice
            self.records.append(record)
            write(self.directory/'control-journal.json', self.records)

    @staticmethod
    def refuse(callback, expected):
        started = time.monotonic()
        try:
            callback()
        except ContractFailure as error:
            observed = error.code
        else:
            raise AssertionError('controlled operation returned success')
        elapsed = (time.monotonic() - started) * 1000
        assert observed == expected, (observed, expected)
        return {'code': observed, 'elapsed_ms': elapsed}

    def positive(self):
        parent, query = Parent(100), 'control-initial-anchor'
        with self.case('bind-preelapsed-no-new-ttl', parent) as record:
            time.sleep(.02)
            reads = self.catalog.controlled_reads(self.reader, parent.control)
            bound = reads.bind(self.req(query, 1000))
            context = bound.value['context']
            record.update(binding=bound.document, context_ttl=context['remaining_ttl_ms'])
            assert 0 < context['remaining_ttl_ms'] <= 90
            assert context['deadline_unix_ms'] - context['bound_at_unix_ms'] == context['remaining_ttl_ms']
            assert reads.reauthorize(bound) == self.state()[0]['policy_epoch']
            row = self.row(query)[0]
            assert bytes(row['binding']) == bound.encoded and row['pin_id'] == context['pin']['pin_id']
            assert row['lease_id'] == context['pin']['lease_id'] and not row['released']
            reads.release_pin(bound, Parent(5000).control)
            assert self.row(query)[0]['released']

    def performance(self):
        samples = []
        for number in range(32):
            parent = Parent(1000)
            with self.case(f'parent-lifecycle-{number:02d}', parent) as record:
                reads = self.catalog.controlled_reads(self.reader, parent.control)
                query = f'controlled-profile-{number:02d}'
                bound = reads.bind(self.req(query))
                epoch = reads.reauthorize(bound)
                elapsed = (time.monotonic() - parent.started) * 1000
                assert elapsed < 1000 and epoch == self.state()[0]['policy_epoch']
                cleanup = Parent(5000)
                reads.release_pin(bound, cleanup.control)
                row = self.row(query)[0]
                assert row['released'] and bytes(row['binding']) == bound.encoded
                assert parent.control.invoice['counts']['connect_attempt'] == 2
                assert cleanup.control.invoice['counts']['connect_attempt'] == 1
                record.update(query_id=query, binding_sha256=bound.sha256, read_elapsed_ms=elapsed,
                              cleanup_elapsed_ms=(time.monotonic()-cleanup.started)*1000,
                              cleanup_invoice=cleanup.control.invoice)
                samples.append(record)
        assert len(samples) == 32

    def blackhole(self):
        stop, eof = threading.Event(), threading.Event()
        received, accepted = [], []
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(.5)
        def serve():
            try:
                conn, _ = listener.accept()
                accepted.append(conn)
                conn.settimeout(.05)
                while not stop.is_set():
                    try:
                        raw = conn.recv(4096)
                        if not raw:
                            eof.set()
                            return
                        received.append(len(raw))
                    except socket.timeout:
                        continue
            finally:
                for conn in accepted:
                    conn.close()
        worker = threading.Thread(target=serve)
        worker.start()
        parent = Parent(100)
        with self.case('parent-blackhole-connect', parent) as record:
            dsn = f'host=127.0.0.1 port={listener.getsockname()[1]} dbname=fixture user=fixture sslmode=disable'
            try:
                record.update(self.refuse(lambda: cf1a_pg.connect(dsn, parent.deadline, parent.control), 'deadline'))
                assert 40 <= record['elapsed_ms'] <= 150
                assert eof.wait(max(0, parent.started+.150-time.monotonic()))
                record.update(peer_eof_before_stop=True, startup_bytes=sum(received))
            finally:
                stop.set()
                listener.close()
                worker.join(1)
            assert not worker.is_alive() and received

    def waits(self, container, docker):
        parent = Parent(1000)
        conn = cf1a_pg.connect(self.catalog.store.dsn, parent.deadline, parent.control)
        with self.case('paused-sql-min-child100ms', parent) as record:
            try:
                docker('pause', container)
                parent.child = time.monotonic() + .1
                record.update(self.refuse(lambda: conn.execute('SELECT 1'), 'deadline'))
                assert 40 <= record['elapsed_ms'] <= 150 and conn.closed
                record['connection_closed'] = conn.closed
            finally:
                docker('unpause', container, check=False)
                conn.close()
        for cancel in (False, True):
            parent = Parent(1000 if cancel else 100)
            query = 'controlled-lock-cancel' if cancel else 'controlled-lock-deadline'
            with self.case(query, parent) as record, psycopg.connect(self.cases.dsn, connect_timeout=2) as owner:
                owner.execute('SELECT dataset FROM gura_cf1a.datasets WHERE dataset=%s FOR UPDATE', (self.dataset,))
                trigger = None
                if cancel:
                    trigger = threading.Timer(.02, parent.cancelled.set)
                    trigger.start()
                try:
                    reads = self.catalog.controlled_reads(self.reader, parent.control)
                    record.update(self.refuse(lambda: reads.bind(self.req(query)), 'cancelled' if cancel else 'deadline'))
                    assert record['elapsed_ms'] <= 150
                finally:
                    if trigger is not None:
                        trigger.cancel()
                        trigger.join(1)
                    owner.rollback()
                assert self.row(query) == []

    def last_authority(self):
        parent = Parent(1000)
        with self.case('authority-return-parent-cancel', parent) as record:
            reads = self.catalog.controlled_reads(self.reader, parent.control)
            original = self.cases.authority.verify
            def late(*args):
                original(*args)
                parent.cancelled.set()
            with patch.object(self.cases.authority, 'verify', side_effect=late):
                record.update(self.refuse(lambda: reads.bind(self.req('controlled-late-authority')), 'cancelled'))
            assert self.row('controlled-late-authority') == []

    def lost_bind_and_cleanup(self):
        for expired in (False, True):
            parent = Parent(1000)
            query = 'controlled-unknown-expired' if expired else 'controlled-unknown-revoked'
            with self.case(query, parent) as record:
                reads, req = self.catalog.controlled_reads(self.reader, parent.control), self.req(query, 50 if expired else 1000)
                original = self.catalog.store.commit
                def lost(conn):
                    original(conn)
                    raise OSError('injected response lost after real commit')
                with patch.object(self.catalog.store, 'commit', side_effect=lost):
                    record.update(self.refuse(lambda: reads.bind(req), 'outcome_unknown'))
                row = self.row(query)[0]
                self.refuse(lambda: reads.bind(req), 'outcome_unknown')
                if expired:
                    wait = max(0, (row['expires_unix_ms'] - time.time_ns()//1_000_000 + 1)/1000)
                    assert wait <= .2
                    time.sleep(wait)
                else:
                    self.catalog.revoke(self.admin, 'control-revoke', self.dataset,
                                        self.reader.subject_id, self.reader.delegation_ref)
                before = self.state()
                cleanup = Parent(5000)
                with patch.object(self.catalog.store, 'commit', side_effect=lost):
                    unknown = reads.close_bind_request(req, cleanup.control)
                assert unknown.state == 'outcome_unknown'
                closed = reads.close_bind_request(req, Parent(5000).control)
                assert closed.state == 'released' and self.row(query)[0]['released']
                assert self.state() == before and len(self.row(query)) == 1
                changed = req.value
                changed['trace_id'] = 'wrong-control-trace'
                self.refuse(lambda: reads.close_bind_request(contract('bind_request', changed), Parent(5000).control), 'conflict')
                stranger = TrustedPrincipal(self.reader.tenant_id, 'foreign', 'foreign-session')
                foreign = self.catalog.controlled_reads(stranger, Parent(1000).control)
                self.refuse(lambda: foreign.close_bind_request(req, Parent(5000).control), 'unauthorized')
                record.update(cleanup_unknown=asdict(unknown), final_cleanup=asdict(closed), cleanup_invoice=cleanup.control.invoice)
                if not expired:
                    self.grant('control-regrant')
        parent = Parent(1000)
        with self.case('absent-unconfirmed-no-automatic-rebind', parent) as record:
            reads, req = self.catalog.controlled_reads(self.reader, parent.control), self.req('controlled-absent')
            before = self.state()
            result = reads.close_bind_request(req, Parent(5000).control)
            assert result.state == 'cleanup_unconfirmed'
            self.refuse(lambda: reads.bind(req), 'expired_context')
            assert self.row('controlled-absent') == [] and self.state() == before
            record['cleanup'] = asdict(result)

    def paused_bind_commit(self, container, docker):
        parent, phase = Parent(1000), {}
        with self.case('paused-real-bind-commit-parent-cancel', parent) as record:
            reads, req = self.catalog.controlled_reads(self.reader, parent.control), self.req('controlled-paused-bind')
            original_commit, original_ready = self.catalog.store.commit, cf1a_pg._ready
            def paused(conn):
                docker('pause', container)
                phase['remaining_before_real_commit_ms'] = parent.control.remaining(parent.deadline)*1000
                phase['entered_real_commit'] = True
                original_commit(conn)
            def ready(fd, mask, deadline, control=None):
                if phase.get('entered_real_commit'):
                    phase['real_commit_generator_wait'] = True
                    parent.cancelled.set()
                return original_ready(fd, mask, deadline, control)
            try:
                with patch.object(self.catalog.store, 'commit', side_effect=paused), patch.object(cf1a_pg, '_ready', side_effect=ready):
                    record.update(self.refuse(lambda: reads.bind(req), 'outcome_unknown'))
                assert phase.get('entered_real_commit') and phase.get('real_commit_generator_wait')
                assert phase['remaining_before_real_commit_ms'] >= 25
            finally:
                docker('unpause', container, check=False)
            rows = self.row('controlled-paused-bind')
            assert len(rows) in (0, 1)
            result = reads.close_bind_request(req, Parent(5000).control)
            assert result.state == ('released' if rows else 'cleanup_unconfirmed')
            self.refuse(lambda: reads.bind(req), 'outcome_unknown')
            record.update(phase=phase, actual_query_count=len(rows), cleanup=asdict(result))


def controlled(cases, container, docker, directory):
    component = ControlCases(cases, directory)
    component.positive()
    component.performance()
    component.blackhole()
    component.waits(container, docker)
    component.last_authority()
    component.lost_bind_and_cleanup()
    component.paused_bind_commit(container, docker)
    assert all(item['passed'] for item in component.records)
    return {'cases': component.records, 'performance_queries': 32,
            'cleanup_unconfirmed_is_not_terminal': True,
            'missing': ['PG/native parent memory', 'P03/P04 real parent pairing', 'C2 closed request', 'I1']}
