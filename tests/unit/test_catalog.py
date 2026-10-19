"""Catalog orchestration tests; live PG locking and fencing remain in scenarios."""
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch

from modules.catalog.control import Control
from modules.catalog.jobs import Jobs
from modules.catalog.managed import Managed
from modules.common.contracts import Failure, digest, encoded
from support import Connection, transaction, control_for

DATASET = '89b349e2-cc73-4c22-871d-c80a159d7789'
PRINCIPAL = {'tenant': 'tenant', 'subject': 'reader', 'token_sha256': 'a'*64}


class CatalogTest(unittest.TestCase):
    def call(self, method, steps, *args):
        conn = Connection(steps)
        obj = Control('unused')
        with patch.object(obj, 'transaction', side_effect=lambda: transaction(conn)):
            result = getattr(obj, method)(*args)
        conn.complete()
        return result, conn

    def test_connect_and_initialize(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.execute.return_value.fetchone.return_value = {'version': 1}
        with patch('modules.catalog.control.psycopg.connect', return_value=connection):
            obj = Control('dsn')
            obj.initialize()
            self.assertIn('CREATE', connection.execute.call_args_list[-2].args[0])
        self.call('initialize', [('CREATE', None), ('SELECT version', {'version': 1})])

    def test_registration_and_immutable_replay(self):
        steps = [('advisory', None), ('FOR UPDATE', None), ('count', {'n': 0}), ('INSERT', None)]
        _, conn = self.call('register', steps, DATASET, 't', 'docs', {})
        self.assertEqual(conn.calls[-1][1][:3], (DATASET, 't', 'docs'))
        self.call('register', [('advisory', None), ('FOR UPDATE', {'tenant': 't', 'name': 'docs', 'definition': {}})], DATASET, 't', 'docs', {})
        with self.assertRaisesRegex(Failure, 'immutable'):
            self.call('register', [('advisory', None), ('FOR UPDATE', {'tenant': 'other', 'name': 'docs', 'definition': {}})], DATASET, 't', 'docs', {})
        with self.assertRaises(Failure):
            self.call('register', [], DATASET, 't', 'Invalid', {})

    def test_begin_fences_and_reconciles(self):
        target = {'snapshot': 1}
        created = {'id': 'run', 'generation': 4}
        row, conn = self.call('begin', [('advisory', None), ('datasets', {'generation': 3}), ('operation', None),
                                      ('count', {'n': 0}), ('UPDATE', None), ('INSERT', created)], DATASET, 'op', target)
        self.assertEqual(row, created)
        self.assertEqual(conn.calls[-1][1][4], 4)
        previous = {'fingerprint': digest(encoded(target))}
        self.assertEqual(self.call('begin', [('advisory', None), ('datasets', {}), ('operation', previous)], DATASET, 'op', target)[0], previous)
        with self.assertRaises(Failure):
            self.call('begin', [('advisory', None), ('datasets', None)], DATASET, 'op', target)

    def test_lookup_ready_and_fail(self):
        for method in ('run', 'dataset'):
            self.assertEqual(self.call(method, [('SELECT', {'id': 'x'})], 'x')[0], {'id': 'x'})
            with self.assertRaises(Failure):
                self.call(method, [('SELECT', None)], 'x')
        self.call('ready', [('FOR UPDATE', {'status': 'building'}), ('UPDATE', None)], 'x', {})
        self.call('ready', [('FOR UPDATE', {'status': 'published', 'artifact': {}})], 'x', {})
        with self.assertRaises(Failure):
            self.call('ready', [('FOR UPDATE', {'status': 'published', 'artifact': {'old': 1}})], 'x', {})
        self.call('fail', [('UPDATE', None)], 'x', 'build_failed')

    def test_publish_cas_and_unknown_outcome(self):
        row = {'dataset': 'd', 'generation': 3, 'published_epoch': None, 'status': 'ready'}
        steps = [('runs', row), ('datasets', {'generation': 3, 'epoch': 2}), ('runs', row), ('UPDATE', None), ('UPDATE', None)]
        self.assertEqual(self.call('publish', steps, 'r', 2)[0], 3)
        row['published_epoch'] = 3
        self.assertEqual(self.call('publish', [('runs', row), ('datasets', {}), ('runs', row)], 'r', 1)[0], 3)
        row['published_epoch'] = None
        with self.assertRaises(Failure) as caught:
            self.call('publish', [('runs', row), ('datasets', {'generation': 4}), ('runs', row)], 'r', 2)
        self.assertEqual(caught.exception.code, 'stale_generation')

    def test_authentication_grants_and_pins(self):
        self.assertEqual(self.call('principal', [('principals', PRINCIPAL)], 'secret')[0], PRINCIPAL)
        with self.assertRaises(Failure):
            self.call('principal', [('principals', None)], 'bad')
        conn = Connection([('JOIN', {'id': DATASET})])
        self.assertEqual(Control.authorize(conn, PRINCIPAL, DATASET), {'id': DATASET})
        self.call('grant', [('SELECT tenant', {'tenant': 't'}), ('INSERT', None), ('INSERT', None)], 'a'*64, 't', 's', DATASET)
        self.call('revoke', [('DELETE', None)], 't', 's', DATASET)
        self.call('pin', [('FOR UPDATE', {'status': 'published'}), ('count', {'n': 0}), ('INSERT', None)], 'run', 'owner')
        self.call('unpin', [('DELETE', None)], 'run', 'owner')
        row = {'id': 'r', 'dataset': 'd', 'status': 'published'}
        self.assertEqual(self.call('retire', [('runs', row), ('datasets', {'published': 'new'}), ('runs', row), ('pins', None), ('UPDATE', None)], 'r')[0], row)
        with self.assertRaises(Failure) as caught:
            self.call('retire', [('runs', row), ('datasets', {'published': 'r'}), ('runs', row)], 'r')
        self.assertEqual(caught.exception.code, 'still_referenced')


class ManagedTest(unittest.TestCase):
    def test_transactions_and_intention_lifecycle(self):
        conn = Connection([("lock_timeout", None), ('CREATE', None)])
        cm = Mock(__enter__=Mock(return_value=conn), __exit__=Mock(return_value=False))
        obj = Managed('dsn')
        with patch('modules.catalog.managed.psycopg.connect', return_value=cm):
            obj.initialize()
        conn.complete()
        conn = Connection([('INSERT', None), ('SELECT', {'root': '/root'}), ('tables', {'generation': 1}),
                           ('intents', None), ('UPDATE', None), ('INSERT', {'status': 'prepared'}),
                           ('tables', {'root': '/root', 'generation': 2}), ('intents', {'status': 'prepared'}),
                           ('UPDATE', None), ('UPDATE', None), ('SELECT', []), ('UPDATE', None)])
        with patch.object(obj, 'transaction', side_effect=lambda: transaction(conn)):
            obj.register('docs', '/root')
            self.assertEqual(obj.prepare('docs', 'op', 'fp')['status'], 'prepared')
            with obj.committing('docs', 'op', '/root') as (db, row, generation):
                self.assertEqual(generation, 2)
                row.update(name='docs', operation='op')
                Managed.parent(db, row, 5)
                Managed.confirmed(db, row, 6, 'metadata', 'hash')
            self.assertEqual(obj.pending('docs'), [])
            obj.abort('docs', 'op')
        conn.complete()
        with patch.object(obj, 'transaction', side_effect=lambda: transaction(Connection([
                ('tables', {'generation': 1}), ('intents', {'fingerprint': 'fp'})]))):
            self.assertEqual(obj.prepare('docs', 'op', 'fp')['fingerprint'], 'fp')
        Managed.parent(Connection(), {'status': 'committed', 'parent': 5}, 5)
        with self.assertRaises(Failure):
            Managed.parent(Connection(), {'status': 'committed', 'parent': 5}, 6)


class JobsTest(unittest.TestCase):
    def test_job_lifecycle(self):
        row = {'id': 'j', 'dataset': 'd', 'run': 'r', 'worker': 'w', 'kind': 'scan', 'status': 'queued', 'cancelled': False, 'tenant': 'tenant', 'subject': 'reader'}
        conn = Connection([('advisory', None), ('count', {'n': 0}), ('FOR UPDATE', {'published': 'r'}),
                           ('runs', {'id': 'r', 'status': 'published', 'artifact': {'context': {'view': 'v'}}}),
                           ('INSERT', None), ('INSERT', row)])
        control = control_for(conn)
        jobs = Jobs(control, 'w')
        with patch.object(Control, 'authorize', return_value={}):
            submitted = jobs.submit(PRINCIPAL, 'd', 'scan', {}, None)
        self.assertEqual(submitted['id'], 'j')
        conn.complete()
        conn = Connection([('SELECT', row)])
        jobs.control = control_for(conn)
        with patch.object(Control, 'authorize', return_value={}):
            self.assertEqual(jobs.get('j', PRINCIPAL), row)
        conn.complete()
        conn = Connection([('SELECT', row), ('UPDATE', None)])
        jobs.control = control_for(conn)
        with patch.object(Control, 'authorize', return_value={}):
            jobs.active('j', PRINCIPAL)
        conn.complete()
        conn = Connection([('SELECT', {'cancelled': False})])
        jobs.control = control_for(conn)
        self.assertFalse(jobs.cancelled('j'))
        conn.complete()
        conn = Connection([('SELECT', dict(row, status='running')), ('UPDATE', None), ('DELETE', None)])
        jobs.control = control_for(conn)
        with patch.object(Control, 'authorize', return_value={}):
            jobs.finish('j', PRINCIPAL, result={'path': 'result'})
        self.assertEqual(conn.calls[1][1][0], 'succeeded')
        conn.complete()
        conn = Connection([('SELECT', dict(row, worker='different'))])
        jobs.control = control_for(conn)
        jobs.finish('j', PRINCIPAL, error='failure')
        conn.complete()
        conn = Connection([('UPDATE', None)])
        jobs.control = control_for(conn)
        with patch.object(jobs, 'get', return_value=row):
            self.assertEqual(jobs.cancel('j', PRINCIPAL), row)
        conn.complete()
        terminal = dict(row, status='succeeded')
        conn = Connection([('SELECT', terminal), ('DELETE', None), ('DELETE', None)])
        jobs.control = control_for(conn)
        cleanup = Mock()
        with patch.object(jobs, 'get', return_value=terminal), patch.object(Control, 'authorize', return_value={}):
            jobs.release('j', PRINCIPAL, cleanup)
        cleanup.assert_called_once_with()
        conn.complete()
        conn = Connection([('UPDATE', [{'id': 'j', 'run': 'r'}]), ('DELETE', None), ('DELETE', None)])
        jobs.control = control_for(conn)
        self.assertEqual(jobs.recover(), 1)
        conn.complete()
