"""Three real loopback services authenticate fixed workers and persist task ownership."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, closing, ExitStack
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import socket
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from modules.cluster.transport import endpoint, fanout_remote, request, signature
from modules.common.contracts import MAX_BYTES, Budget, Failure, digest, encoded, key

SECRET = 'local-test-secret-with-at-least-32-bytes'
REPO = Path(__file__).resolve().parents[2]


def payload(shard=0):
    return {'kind': 'scan', 'request': {'limit': 10},
            'scope': {'tenant': 'tenant', 'subject': 'subject', 'dataset': 'dataset'},
            'bundle': {'revision': 'revision', 'context': {'view': 'fixed'},
                       'manifest': {'dataset_id': 'dataset'},
                       'rows': [{'logical_key': key(shard, 'long'), 'values': {'id': shard}, 'media': []}]}}


def task():
    value = payload()
    return {'task_id': uuid.uuid4().hex, 'owner': uuid.uuid4().hex, 'shard': 0,
            'expires_at': time.time()+20, 'payload': value, 'fingerprint': digest(encoded(value)),
            'limits': Budget().allocation(3)}


@contextmanager
def service(root, shared):
    process = subprocess.Popen([sys.executable, 'scripts/worker.py', '--root', str(root), '--shared-root', str(shared)],
                               cwd=REPO, env=dict(os.environ, GURADB_WORKER_SECRET=SECRET),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        if not ready:
            raise AssertionError('worker startup timed out')
        port = process.stdout.readline().strip()
        if not port.isdigit():
            raise AssertionError('worker startup failed: '+process.stderr.read(1000))
        yield 'http://127.0.0.1:'+port, process
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


class TransportContract(unittest.TestCase):
    def test_three_services_and_persistent_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with service(root/'one', root) as (one,p1), service(root/'two', root) as (two,p2), service(root/'three', root) as (three,p3):
                result = fanout_remote([payload(n) for n in range(3)], Budget(seconds=10), root/'coordinator', [one,two,three], SECRET)
                self.assertEqual([r['records'] for r in result], [1,1,1])
                self.assertEqual({r['server_pid'] for r in result}, {p1.pid,p2.pid,p3.pid})
                self.assertEqual(len({r['pid'] for r in result}), 3)
                value = task()
                first = request(one, '/v1/tasks', value, SECRET, 5)
                self.assertEqual(request(one, '/v1/tasks', value, SECRET, 5), first)
                foreign = dict(value, owner=uuid.uuid4().hex)
                with self.assertRaises(Failure) as caught:
                    request(one, '/v1/tasks', foreign, SECRET, 5)
                self.assertEqual(caught.exception.code, 'worker_owner')
                with self.assertRaises(Failure) as caught:
                    request(one, '/v1/cancel', {'task_id': value['task_id'], 'owner': foreign['owner']}, SECRET, 5)
                self.assertEqual(caught.exception.code, 'worker_owner')
                with self.assertRaises(Failure) as caught:
                    request(one, '/v1/tasks', task(), 'incorrect-secret-with-at-least-32-bytes', 5)
                self.assertEqual(caught.exception.code, 'worker_unauthorized')
                expired = task()
                expired['expires_at'] = time.time()-1
                with self.assertRaises(Failure) as caught:
                    request(one, '/v1/tasks', expired, SECRET, 5)
                self.assertEqual(caught.exception.code, 'worker_expired')
                escaped = task()
                escaped['payload']['bundle']['index_path'] = '/etc'
                escaped['fingerprint'] = digest(encoded(escaped['payload']))
                with self.assertRaises(Failure) as caught:
                    request(one, '/v1/tasks', escaped, SECRET, 5)
                self.assertEqual(caught.exception.code, 'worker_scope')
            with service(root/'one', root) as (restarted, _):
                self.assertEqual(request(restarted, '/v1/tasks', value, SECRET, 5), first)

    def test_cancel_and_deadline_reject_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with service(root/'one', root) as (one,_), service(root/'two', root) as (two,_), service(root/'three', root) as (three,_):
                started = time.monotonic()
                def active():
                    for name in ('one','two','three'):
                        with closing(sqlite3.connect(root/name/'tasks.sqlite')) as db:
                            if db.execute("SELECT count(*) FROM tasks WHERE state='running'").fetchone()[0]:
                                return True
                    return False
                with self.assertRaises(Failure) as caught:
                    fanout_remote([payload(n) for n in range(3)], Budget(cancelled=active, seconds=10),
                                  root/'coordinator', [one,two,three], SECRET)
                self.assertEqual(caught.exception.code, 'cancelled')
                self.assertLess(time.monotonic()-started, 3)
                for name in ('one','two','three'):
                    with closing(sqlite3.connect(root/name/'tasks.sqlite')) as db:
                        states = [r[0] for r in db.execute('SELECT state FROM tasks')]
                    self.assertNotIn('running', states)
                    self.assertNotIn('done', states)
                short = task()
                short['expires_at'] = time.time()+.01
                with self.assertRaises(Failure) as caught:
                    request(one, '/v1/tasks', short, SECRET, 5)
                self.assertIn(caught.exception.code, ('timeout','worker_expired'))

    def test_running_duplicate_cancel_reaps_worker_and_restart_abandons(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            pipe = root/'blocked-artifact'
            os.mkfifo(pipe)
            value = task()
            value['payload']['bundle']['serving_shard'] = {
                'shard': 0, 'revision': 'revision', 'rows': 1,
                'file': {'path': str(pipe), 'sha256': '0'*64}}
            value['fingerprint'] = digest(encoded(value['payload']))
            with service(root/'one', root) as (one,server):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(request, one, '/v1/tasks', value, SECRET, 5)
                    child = None
                    until = time.monotonic()+3
                    while child is None and time.monotonic() < until:
                        snapshot = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,command='],
                                                  capture_output=True, text=True, check=True).stdout
                        for line in snapshot.splitlines():
                            fields = line.strip().split(None,2)
                            if len(fields) == 3 and fields[1] == str(server.pid) and 'modules.query.remote_runner' in fields[2]:
                                child = int(fields[0])
                        time.sleep(.01)
                    self.assertIsNotNone(child, 'observe actual blocked query.worker subprocess')
                    with self.assertRaises(Failure) as caught:
                        request(one, '/v1/tasks', value, SECRET, 2)
                    self.assertEqual(caught.exception.code, 'operation_busy')
                    request(one, '/v1/cancel', {'task_id': value['task_id'], 'owner': value['owner']}, SECRET, 2)
                    with self.assertRaises(Failure) as caught:
                        pending.result(timeout=3)
                    self.assertEqual(caught.exception.code, 'cancelled')
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child, 0)
                unknown = task()
                with closing(sqlite3.connect(root/'one'/'tasks.sqlite')) as db:
                    db.execute('INSERT INTO tasks VALUES (?,?,?,?,NULL,?)',
                               (unknown['task_id'], unknown['owner'], digest(encoded(unknown)), 'running',unknown['expires_at']))
                    db.commit()
                pre_cancelled = task()
                request(one, '/v1/cancel', {'task_id': pre_cancelled['task_id'], 'owner': pre_cancelled['owner']}, SECRET, 2)
                with self.assertRaises(Failure) as caught:
                    request(one, '/v1/tasks', pre_cancelled, SECRET, 2)
                self.assertEqual(caught.exception.code, 'cancelled')
            with service(root/'one', root) as (restarted,_):
                with self.assertRaises(Failure) as caught:
                    request(restarted, '/v1/tasks', unknown, SECRET, 2)
                self.assertEqual(caught.exception.code, 'worker_abandoned')

    def test_expired_records_reclaimed_and_business_paths_opaque(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with service(root/'one', root) as (one,_):
                with closing(sqlite3.connect(root/'one'/'tasks.sqlite')) as db:
                    db.executemany('INSERT INTO tasks VALUES (?,?,?,?,NULL,?)',
                                   [(uuid.uuid4().hex, 'owner', 'digest', 'done', time.time()-1) for _ in range(140)])
                    db.commit()
                value = task()
                value['payload']['bundle']['rows'][0]['values'].update(path='user-column', root='not-a-directory', index_path='text')
                value['fingerprint'] = digest(encoded(value['payload']))
                result = request(one, '/v1/tasks', value, SECRET, 5)
                self.assertEqual(result['output']['rows'][0]['values']['path'], 'user-column')
                with closing(sqlite3.connect(root/'one'/'tasks.sqlite')) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
                cancelled = task()
                request(one, '/v1/cancel', {'task_id': cancelled['task_id'], 'owner': cancelled['owner']}, SECRET, 2)
                with closing(sqlite3.connect(root/'one'/'tasks.sqlite')) as db:
                    expires = db.execute('SELECT expires FROM tasks WHERE id=?', (cancelled['task_id'],)).fetchone()[0]
                self.assertGreater(expires, time.time()+29)

    def test_real_server_crash_reaps_blocked_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            pipe = root/'blocked'
            os.mkfifo(pipe)
            value = task()
            value['payload']['bundle']['serving_shard'] = {
                'shard': 0, 'revision': 'revision', 'rows': 1,
                'file': {'path': str(pipe), 'sha256': '0'*64}}
            value['fingerprint'] = digest(encoded(value['payload']))
            with service(root/'one', root) as (one,server):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(request, one, '/v1/tasks', value, SECRET, 5)
                    child = None
                    until = time.monotonic()+3
                    while child is None and time.monotonic() < until:
                        lines = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,command='],
                                               capture_output=True, text=True, check=True).stdout.splitlines()
                        for line in lines:
                            fields = line.strip().split(None,2)
                            if len(fields) == 3 and fields[1] == str(server.pid) and 'modules.query.remote_runner' in fields[2]:
                                child = int(fields[0])
                        time.sleep(.01)
                    self.assertIsNotNone(child)
                    # Allow runner to enter the actual artifact read, beyond interpreter startup.
                    time.sleep(.1)
                    server.kill()
                    server.wait(timeout=3)
                    with self.assertRaises(Failure):
                        pending.result(timeout=3)
                    until = time.monotonic()+3
                    alive = True
                    while alive and time.monotonic() < until:
                        try:
                            os.kill(child, 0)
                        except ProcessLookupError:
                            alive = False
                        time.sleep(.02)
                    self.assertFalse(alive, 'HTTP SIGKILL must not leave its blocked execution child alive')
            with service(root/'one', root) as (restarted,_):
                self.assertEqual(list((root/'one').glob('task-*')), [])
                with self.assertRaises(Failure) as caught:
                    request(restarted, '/v1/tasks', value, SECRET, 2)
                self.assertEqual(caught.exception.code, 'worker_abandoned')

    def test_slow_remote_cancellation_and_trickle_have_absolute_deadline(self):
        entered, release = threading.Event(), threading.Event()

        class SlowHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                if self.path == '/v1/tasks':
                    entered.set()
                    release.wait(4)
                raw = encoded({'cancelled': True})
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('X-Gura-Signature', signature(SECRET, self.path, raw))
                self.end_headers()
                try:
                    if self.path == '/trickle':
                        for value in raw:
                            self.wfile.write(bytes([value]))
                            self.wfile.flush()
                            time.sleep(.03)
                    else:
                        self.wfile.write(raw)
                except OSError:
                    pass

        servers = [ThreadingHTTPServer(('127.0.0.1', 0), SlowHandler) for _ in range(3)]
        threads = []
        for server in servers:
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
            thread.start()
            threads.append(thread)
        try:
            endpoints = ['http://127.0.0.1:'+str(server.server_address[1]) for server in servers]
            with tempfile.TemporaryDirectory() as directory:
                started = time.monotonic()
                with self.assertRaises(Failure) as caught:
                    fanout_remote([payload(n) for n in range(3)], Budget(cancelled=entered.is_set, seconds=10),
                                  directory, endpoints, SECRET)
                self.assertEqual(caught.exception.code, 'cancelled')
                self.assertLess(time.monotonic()-started, .7)
            started = time.monotonic()
            with self.assertRaises(Failure) as caught:
                request(endpoints[0], '/trickle', {}, SECRET, .15)
            self.assertEqual(caught.exception.code, 'timeout')
            self.assertLess(time.monotonic()-started, .5)
        finally:
            release.set()
            for server,thread in zip(servers,threads):
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_incomplete_headers_have_connection_admission_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with service(root/'one', root) as (one,server):
                host, port = endpoint(one)
                with ExitStack() as clients:
                    open_count = 0
                    for _ in range(10):
                        client = clients.enter_context(socket.create_connection((host,port), timeout=1))
                        try:
                            client.sendall(b'POST /v1/tasks HTTP/1.1\r\n')
                        except OSError:
                            pass
                        # Observe admission before connecting again: a burst can fill
                        # Linux's listen backlog before the worker accepts any peers.
                        # Retain admitted sockets so all ten attempts test the cap.
                        client.settimeout(.03)
                        try:
                            if client.recv(1):
                                open_count += 1
                        except socket.timeout:
                            open_count += 1
                        except OSError:
                            pass
                    self.assertLessEqual(open_count, 4)

    def test_transport_whitelist_and_response_budget(self):
        for url in ('https://127.0.0.1:1', 'http://localhost:1', 'http://192.0.2.1:1',
                    'http://user@127.0.0.1:1', 'http://127.0.0.1:1/path'):
            with self.assertRaises(Failure):
                endpoint(url)
        with patch('modules.cluster.transport.http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value.getheader.return_value = str(MAX_BYTES+1)
            with self.assertRaises(Failure) as caught:
                request('http://127.0.0.1:1', '/v1/tasks', {}, SECRET, 1)
            self.assertEqual(caught.exception.code, 'resource_limit')
            connection.return_value.getresponse.return_value.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
