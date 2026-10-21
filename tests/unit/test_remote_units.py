"""Loopback task service units: replay, scope, migration and process ownership."""
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from modules.cluster.transport import signature
from modules.common.contracts import Budget, Failure, digest, encoded
from modules.query import remote_runner, remote_worker
from test_worker_units import fact_bundle

SECRET = 'test-secret-with-at-least-32-characters'


def request():
    bundle = fact_bundle()
    bundle.pop('index_path')
    bundle.pop('index_files')
    payload = {'bundle': bundle, 'kind': 'scan', 'request': {}, 'scope': {'dataset': 'd', 'tenant': 't', 'subject': 's'}}
    return {'task_id': 'a'*32, 'owner': 'b'*32, 'shard': 0, 'expires_at': time.time()+20,
            'payload': payload, 'fingerprint': digest(encoded(payload)), 'limits': Budget().allocation(3)}


class RemoteTest(unittest.TestCase):
    def test_running_output_keeps_valid_result_and_cleans_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            tasks = remote_worker.Tasks(root/'tasks', root, SECRET)
            self.addCleanup(tasks.lease.close)
            value = request()
            process = Mock(pid=4321, returncode=None)
            states = iter((None, 0))
            def poll():
                process.returncode = next(states)
                return process.returncode
            process.poll.side_effect = poll
            result = {name: value[name] for name in ('task_id', 'shard', 'fingerprint')}
            result.update(pid=process.pid, records=3)
            def spawn(command, **_):
                Path(command[-1]).write_bytes(encoded(result))
                return process
            with patch.object(remote_worker.subprocess, 'Popen', side_effect=spawn) as popen, patch.object(remote_worker, 'stop_group') as stop, patch.object(remote_worker.time, 'sleep') as sleep:
                actual = tasks.run(value, threading.Event(), time.monotonic()+20)
            self.assertEqual(actual, dict(result, owner=value['owner'], server_pid=os.getpid()))
            self.assertEqual(process.poll.call_count, 2)
            popen.assert_called_once()
            sleep.assert_called_once_with(.01)
            stop.assert_called_once_with(process)

    def test_running_oversized_output_rejected_before_exit_and_cleans_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            tasks = remote_worker.Tasks(root/'tasks', root, SECRET)
            self.addCleanup(tasks.lease.close)
            process = Mock(pid=4321, returncode=None)
            states = iter((None, 0))
            def poll():
                process.returncode = next(states)
                return process.returncode
            process.poll.side_effect = poll
            def spawn(command, **_):
                with Path(command[-1]).open('wb') as stream:
                    stream.truncate(remote_worker.MAX_BYTES+1)
                return process
            with patch.object(remote_worker.subprocess, 'Popen', side_effect=spawn) as popen, patch.object(remote_worker, 'stop_group') as stop, patch.object(remote_worker.time, 'sleep') as sleep:
                with self.assertRaises(Failure) as caught:
                    tasks.run(request(), threading.Event(), time.monotonic()+20)
            self.assertEqual(caught.exception.code, 'resource_limit')
            process.poll.assert_called_once_with()
            self.assertIsNone(process.returncode)
            popen.assert_called_once()
            sleep.assert_not_called()
            stop.assert_called_once_with(process)

    def test_scope_replay_cancellation_and_abandoned_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            tasks = remote_worker.Tasks(root/'tasks', root, SECRET)
            self.addCleanup(tasks.lease.close)
            with self.assertRaises(Failure):
                remote_worker.Tasks(root/'tasks', root, SECRET)
            file = root/'file'
            file.write_bytes(b'data')
            ref = {'path': str(file)}
            bundle = {'index_path': str(root), 'index_files': [ref], 'bm25': {'stats': ref, 'files': [ref]},
                      'ann': {'path': str(root), 'files': [ref]},
                      'serving_shard': {'file': ref, 'ann': {'path': str(root), 'files': [ref]}},
                      'manifest': {'backend': {'root': str(root)}}, 'source_files': [{'key': 'file'}]}
            tasks.paths(bundle)
            with self.assertRaises(Failure):
                tasks.path('/etc/passwd')
            value = request()
            result = tasks.execute(value)
            self.assertEqual(result['records'], 3)
            self.assertEqual(tasks.execute(value), result)
            self.assertFalse(tasks.cancel({'task_id': value['task_id'], 'owner': value['owner']})['cancelled'])
            fresh = request()
            fresh['task_id'] = 'c'*32
            self.assertTrue(tasks.cancel({'task_id': fresh['task_id'], 'owner': fresh['owner']})['cancelled'])
            with self.assertRaises(Failure) as caught:
                tasks.execute(fresh)
            self.assertEqual(caught.exception.code, 'cancelled')
            bad = request()
            bad['task_id'] = 'd'*32
            with patch.object(tasks, 'run', side_effect=Failure('worker_failed', 'crash')):
                with self.assertRaises(Failure):
                    tasks.execute(bad)
            with self.assertRaises(Failure) as caught:
                tasks.execute(bad)
            self.assertEqual(caught.exception.code, 'worker_abandoned')
            failed = request()
            failed['task_id'] = 'e'*32
            failed['payload']['kind'] = 'unsupported'
            failed['fingerprint'] = digest(encoded(failed['payload']))
            with self.assertRaises(Failure) as caught:
                tasks.execute(failed)
            self.assertEqual(caught.exception.code, 'invalid_request')
            active = threading.Event()
            tasks.active['running'] = active
            with tasks.database() as db:
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,NULL,?)', ('running', 'owner', '', 'running', time.time()+10))
            self.assertTrue(tasks.cancel({'task_id': 'running', 'owner': 'owner'})['cancelled'])
            self.assertTrue(active.is_set())

    def test_legacy_database_and_stale_scratch_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            scratch = root/'task-abcdefgh'
            scratch.mkdir()
            with sqlite3.connect(root/'tasks.sqlite') as db:
                db.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY, owner TEXT, fingerprint TEXT, state TEXT, response BLOB)')
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,NULL)', ('old', 'owner', 'fp', 'running'))
            with patch.object(remote_worker.time, 'sleep'):
                tasks = remote_worker.Tasks(root, root, SECRET)
            self.addCleanup(tasks.lease.close)
            self.assertFalse(scratch.exists())
            with tasks.database() as db:
                self.assertEqual(db.execute('SELECT state FROM tasks').fetchone()[0], 'abandoned')

    def test_handler_signed_dispatch_and_server_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            server = remote_worker.serve(root/'tasks', root, SECRET)
            self.addCleanup(server.server_close)
            handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
            handler.connection = Mock()
            handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
            for route in ('/v1/tasks', '/v1/cancel', '/unknown'):
                value = request() if route == '/v1/tasks' else {'task_id': 'c'*32, 'owner': 'b'*32}
                raw = encoded(value)
                handler.path = route
                handler.headers = {'Content-Length': str(len(raw)), 'X-Gura-Signature': signature(SECRET, route, raw)}
                handler.rfile, handler.wfile = BytesIO(raw), BytesIO()
                handler.do_POST()
                result = json.loads(handler.wfile.getvalue())
                self.assertIn('error' if route == '/unknown' else 'task_id', result)
            handler.path = '/v1/cancel'
            handler.headers['X-Gura-Signature'] = signature(SECRET, handler.path, raw)
            handler.rfile = BytesIO(raw)
            handler.wfile = BytesIO()
            with patch.object(server.tasks, 'cancel', return_value={'data': 'x'*(32 << 20)}):
                handler.do_POST()
            self.assertEqual(json.loads(handler.wfile.getvalue()), {'error': 'resource_limit'})
            handler.log_message('no secrets')
            # The write boundary may disappear after execution; this must be contained.
            handler.wfile = Mock(write=Mock(side_effect=OSError('disconnected')))
            handler.rfile = BytesIO(raw)
            handler.do_POST()
            active = threading.Event()
            server.tasks.active['job'] = active
            with patch.object(remote_worker.ThreadingHTTPServer, 'process_request_thread'):
                # Acquire one permit through process_request, then reap it through the thread path.
                with patch.object(remote_worker.ThreadingHTTPServer, 'process_request'):
                    server.process_request('socket', 'address')
                server.process_request_thread('socket', 'address')
            with patch.object(remote_worker.ThreadingHTTPServer, 'process_request', side_effect=OSError('failed')):
                with self.assertRaises(OSError):
                    server.process_request('socket', 'address')
            shutdown = Mock()
            with patch.object(server, 'shutdown_request', shutdown), patch.object(remote_worker.ThreadingHTTPServer, 'process_request'):
                for _ in range(5):
                    server.process_request('socket', 'address')
                shutdown.assert_called_once_with('socket')
            with patch.object(remote_worker.ThreadingHTTPServer, 'get_request', return_value=(Mock(), 'address')):
                connection, _ = server.get_request()
                connection.settimeout.assert_called_once_with(2)
            server.server_close()
            self.assertTrue(active.is_set())
            self._cleanups.pop()  # The server was explicitly closed above.


class RunnerTest(unittest.TestCase):
    def test_descendant_transitive_closure(self):
        result = Mock(stdout='1 0\n2 1\n3 2\n4 0\n')
        with patch.object(remote_runner.subprocess, 'run', return_value=result), patch.object(remote_runner.os, 'getpid', return_value=1):
            self.assertEqual(remote_runner.descendants(), {2, 3})

    def test_main_watchdog_grace_and_force_cleanup(self):
        for abandoned in (False, True):
            event = Mock()
            event.wait.side_effect = [False, False] if abandoned else [True]
            callbacks = []
            def thread(*, target, daemon):
                callbacks.append(target)
                return Mock(start=Mock(side_effect=target))
            with patch.dict(os.environ, GURADB_PARENT_PID='123'), patch.object(remote_runner.threading, 'Event', return_value=event), patch.object(remote_runner.threading, 'Thread', side_effect=thread), patch.object(remote_runner.signal, 'signal') as handler, patch.object(remote_runner.os, 'getppid', return_value=124), patch.object(remote_runner.os, 'kill') as kill, patch.object(remote_runner.os, 'killpg', side_effect=[ProcessLookupError(), None]) as killpg, patch.object(remote_runner, 'descendants', return_value={999}), patch('modules.query.worker.main'):
                remote_runner.main()
                event.set.assert_called_once_with()
                with self.assertRaises(Failure):
                    handler.call_args.args[1]()
                if abandoned:
                    kill.assert_called_once()
                    self.assertEqual(killpg.call_count, 2)
        with patch.dict(os.environ, GURADB_PARENT_PID='123'), patch.object(remote_runner.threading, 'Thread'), patch.object(remote_runner.signal, 'signal'), patch('modules.query.worker.main'):
            runpy.run_path(remote_runner.__file__, run_name='__main__')
