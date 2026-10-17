"""Loopback-only task service executing exactly the trusted query.worker module."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import fcntl
import os
import re
import shutil
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

from modules.cluster.transport import signature
from modules.common.contracts import MAX_BYTES, Failure, decode_json, digest, encoded, require
from modules.storage.objects import put


class Tasks:
    def __init__(self, root, shared_root, secret):
        self.root = Path(root).resolve()
        self.shared = Path(shared_root).resolve(strict=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lease = (self.root/'owner.lock').open('a+b')
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close()
            raise Failure('worker_owner', 'worker task directory already has an owner') from None
        # The root lease fences any live server using these scratch names.
        # A crashed server's fixed runner exits via parent watchdog; no task is resumed.
        stale = [path for path in self.root.iterdir() if re.fullmatch(r'task-[a-z0-9_]{8}', path.name)]
        require(len(stale) <= 128, 'resource_limit', 'worker recovery scratch count exceeded')
        if stale:
            time.sleep(.6)  # Allow the fixed runner's bounded parent-death cleanup to finish.
        for path in stale:
            require(not path.is_symlink() and path.is_dir() and path.resolve().parent == self.root, 'worker_scope')
            shutil.rmtree(path)
        self.secret, self.lock, self.active = secret, threading.Lock(), {}
        signature(secret, '', b'')
        with self.database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, owner TEXT, fingerprint TEXT, state TEXT, response BLOB, expires REAL)')
            columns = {row[1] for row in db.execute('PRAGMA table_info(tasks)')}
            if 'expires' not in columns:
                db.execute('ALTER TABLE tasks ADD COLUMN expires REAL')
                db.execute('UPDATE tasks SET expires=?', (time.time()+30,))
            db.execute("UPDATE tasks SET state='abandoned' WHERE state='running'")
            self.expire(db)

    @contextmanager
    def database(self):
        connection = sqlite3.connect(self.root/'tasks.sqlite', timeout=2)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def expire(self, db):
        db.execute("DELETE FROM tasks WHERE expires < ? AND state != 'running'", (time.time(),))

    def path(self, value):
        require(isinstance(value, str) and Path(value).is_absolute() and
                Path(value).resolve(strict=True).is_relative_to(self.shared), 'worker_scope')

    def reference(self, value):
        require(isinstance(value, dict) and 'path' in value, 'worker_scope')
        self.path(value['path'])

    def ann_paths(self, index):
        self.path(index['path'])
        for reference in index['files']:
            self.reference(reference)

    def paths(self, bundle):
        # Only executable artifact descriptors are paths. User columns remain opaque.
        if 'index_path' in bundle:
            self.path(bundle['index_path'])
        for reference in bundle.get('index_files', []):
            self.reference(reference)
        if 'bm25' in bundle:
            self.reference(bundle['bm25']['stats'])
            for reference in bundle['bm25']['files']:
                self.reference(reference)
        if 'ann' in bundle:
            self.ann_paths(bundle['ann'])
        if 'serving_shard' in bundle:
            shard = bundle['serving_shard']
            self.reference(shard['file'])
            if 'ann' in shard:
                self.ann_paths(shard['ann'])
        if bundle.get('source_files'):
            self.path(bundle['manifest']['backend']['root'])
            for fragment in bundle['source_files']:
                self.path(str(Path(bundle['manifest']['backend']['root'])/fragment['key']))

    def cancel(self, value):
        require(isinstance(value, dict) and set(value) == {'task_id','owner'}, 'invalid_request')
        with self.lock, self.database() as db:
            self.expire(db)
            row = db.execute('SELECT owner,state FROM tasks WHERE id=?', (value['task_id'],)).fetchone()
            if row is None:
                count = db.execute('SELECT count(*) FROM tasks').fetchone()[0]
                require(count < 128, 'resource_limit')
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,NULL,?)',
                           (value['task_id'], value['owner'], '', 'cancelled', time.time()+30))
                return {'task_id': value['task_id'], 'cancelled': True}
            require(row[0] == value['owner'], 'worker_owner')
            if row[1] == 'running':
                db.execute("UPDATE tasks SET state='cancelled',expires=max(expires,?) WHERE id=?", (time.time()+30,value['task_id']))
                if value['task_id'] in self.active:
                    self.active[value['task_id']].set()
        return {'task_id': value['task_id'], 'cancelled': row[1] == 'running'}

    def execute(self, value):
        names = {'task_id','owner','shard','expires_at','payload','fingerprint','limits'}
        require(isinstance(value, dict) and set(value) == names and
                all(isinstance(value[n], str) and len(value[n]) == 32 and
                    all(c in '0123456789abcdef' for c in value[n]) for n in ('task_id','owner')) and
                type(value['shard']) is int and 0 <= value['shard'] < 3 and
                type(value['expires_at']) in (int,float) and time.time() < value['expires_at'] <= time.time()+30,
                'worker_expired')
        deadline = time.monotonic() + value['expires_at']-time.time()
        payload = value['payload']
        require(isinstance(payload, dict) and {'scope','bundle','kind','request'} <= set(payload) and
                digest(encoded(payload)) == value['fingerprint'], 'worker_mismatch')
        scope = payload['scope']
        require(isinstance(scope, dict) and set(scope) == {'tenant','subject','dataset'} and
                all(isinstance(item,str) and 0 < len(item) <= 128 for item in scope.values()) and
                scope['dataset'] == payload['bundle']['manifest']['dataset_id'], 'worker_scope')
        self.paths(payload['bundle'])
        fingerprint = digest(encoded(value))
        cancelled = threading.Event()
        with self.lock, self.database() as db:
            self.expire(db)
            row = db.execute('SELECT owner,fingerprint,state,response FROM tasks WHERE id=?', (value['task_id'],)).fetchone()
            if row:
                require(row[0] == value['owner'], 'worker_owner')
                require(row[2] != 'cancelled', 'cancelled')
                require(row[1] == fingerprint, 'worker_mismatch')
                require(row[2] == 'done', 'operation_busy' if row[2] == 'running' else 'worker_abandoned')
                return decode_json(row[3])
            count, size = db.execute('SELECT count(*),coalesce(sum(length(response)),0) FROM tasks').fetchone()
            require(count < 128 and size < 128 << 20 and len(self.active) < 2, 'resource_limit')
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,NULL,?)',
                       (value['task_id'], value['owner'], fingerprint, 'running', value['expires_at']))
            self.active[value['task_id']] = cancelled
        try:
            result = self.run(value, cancelled, deadline)
            require(not cancelled.is_set() and time.monotonic() < deadline and time.time() < value['expires_at'], 'worker_expired')
            raw = encoded(result)
            require(len(raw) <= MAX_BYTES, 'resource_limit')
            with self.lock, self.database() as db:
                state = db.execute('SELECT state FROM tasks WHERE id=?', (value['task_id'],)).fetchone()[0]
                require(state == 'running' and not cancelled.is_set() and time.monotonic() < deadline and time.time() < value['expires_at'], 'worker_expired')
                size = db.execute('SELECT coalesce(sum(length(response)),0) FROM tasks').fetchone()[0]
                require(size + len(raw) <= 128 << 20, 'resource_limit')
                db.execute("UPDATE tasks SET state='done',response=? WHERE id=?", (raw, value['task_id']))
            return result
        except Exception:
            with self.lock, self.database() as db:
                db.execute("UPDATE tasks SET state='abandoned' WHERE id=? AND state='running'", (value['task_id'],))
            raise
        finally:
            with self.lock:
                self.active.pop(value['task_id'], None)

    def run(self, value, cancelled, deadline):
        with tempfile.TemporaryDirectory(prefix='task-', dir=self.root) as directory:
            task = {name: value[name] for name in ('task_id','shard','payload','fingerprint','limits')}
            task['deadline'] = deadline
            reference = put(Path(directory)/'input', encoded(task))
            output = Path(directory)/'output'
            log_path = Path(directory)/'log'
            with log_path.open('wb') as log:
                process = subprocess.Popen([sys.executable, '-m', 'modules.query.remote_runner', reference['path'],
                                            reference['sha256'], str(output)], stdout=log, stderr=log,
                                           cwd=Path(__file__).resolve().parents[2], start_new_session=True,
                                           env=dict({k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR','VIRTUAL_ENV')}, GURADB_PARENT_PID=str(os.getpid())))
            try:
                while process.poll() is None:
                    require(not cancelled.is_set(), 'cancelled')
                    require(time.monotonic() < deadline, 'timeout')
                    require(log_path.stat().st_size <= 65536, 'resource_limit')
                    if output.exists():
                        require(output.stat().st_size <= MAX_BYTES, 'resource_limit')
                    time.sleep(.01)
                require(process.returncode == 0 and output.is_file(), 'worker_failed')
                with output.open('rb') as stream:
                    raw = stream.read(MAX_BYTES+1)
                require(len(raw) <= MAX_BYTES, 'resource_limit')
                result = decode_json(raw)
                require(isinstance(result, dict) and result.get('pid') == process.pid and
                        all(result.get(n) == task[n] for n in ('task_id','shard','fingerprint')), 'worker_mismatch')
                if 'error' in result:
                    raise Failure(result['error'], 'task execution rejected')
                result['owner'] = value['owner']
                result['server_pid'] = os.getpid()
                return result
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)


def serve(root, shared_root, secret, port=0):
    tasks = Tasks(root, shared_root, secret)
    connections = threading.BoundedSemaphore(4)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                self.connection.settimeout(2)
                require(self.path in ('/v1/tasks','/v1/cancel'), 'invalid_request')
                require(self.headers.get('Transfer-Encoding') is None, 'invalid_request')
                length = self.headers.get('Content-Length', '')
                require(length.isdigit() and 0 < int(length) <= MAX_BYTES, 'resource_limit')
                raw = self.rfile.read(int(length))
                require(len(raw) == int(length), 'invalid_request')
                require(hmac.compare_digest(self.headers.get('X-Gura-Signature',''),
                                            signature(secret, self.path, raw)), 'worker_unauthorized')
                value = decode_json(raw)
                result = tasks.execute(value) if self.path == '/v1/tasks' else tasks.cancel(value)
                status = 200
            except Exception as error:
                result = {'error': error.code if isinstance(error, Failure) else 'worker_failed'}
                status = 400
            raw = encoded(result)
            if len(raw) > MAX_BYTES:
                raw, status = encoded({'error': 'resource_limit'}), 400
            self.send_response(status)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Content-Type', 'application/json')
            self.send_header('X-Gura-Signature', signature(secret, self.path, raw))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except OSError:
                pass

    class WorkerServer(ThreadingHTTPServer):
        daemon_threads = False

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(2)
            return connection, address

        def process_request(self, connection, address):
            if not connections.acquire(blocking=False):
                self.shutdown_request(connection)
                return
            try:
                super().process_request(connection, address)
            except Exception:
                connections.release()
                raise

        def process_request_thread(self, connection, address):
            try:
                super().process_request_thread(connection, address)
            finally:
                connections.release()

        def server_close(self):
            with tasks.lock:
                for event in tasks.active.values():
                    event.set()
            super().server_close()
            tasks.lease.close()

    server = WorkerServer(('127.0.0.1', port), Handler)
    server.tasks = tasks
    return server
