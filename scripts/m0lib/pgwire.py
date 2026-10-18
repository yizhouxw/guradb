"""Isolated PG18 psql and fixed psycopg clients, with no exposed plaintext port."""
from contextlib import contextmanager
import json
import hashlib
import os
import selectors
import subprocess

from m0lib.kit import PG, ROOT, docker, mapped, write

CLIENT = 'guradb-pg-client:3.2.10'
LISTEN = '127.0.0.1:5433'


def build_client(log_path):
    with log_path.open('xb') as log:
        subprocess.run(['docker', 'build', '-q', '-t', CLIENT, '-f', 'tools/m0/pg-client.Dockerfile', str(ROOT)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)


def publish_auth(lab):
    temporary = lab.auth.with_suffix('.next.json')
    write(temporary, {'principals': lab.principals})
    temporary.replace(lab.auth)
    expected_hash = hashlib.sha256(lab.auth.read_bytes()).hexdigest()
    # Make the administrative publication visible inside Docker before asking a
    # long-lived SDK session to prove revocation/restoration. Never retry SQL.
    script = 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())'
    lab.wait(lambda: docker('exec', lab.server, 'python3', '-c', script, mapped(lab.auth)).stdout.strip() == expected_hash, 2)


class Client:
    def __init__(self, lab, password=None, **kwargs):
        self.lab = lab
        self.name = lab.client_container(CLIENT, 'python', '/workspace/scripts/m0lib/pg_client.py',
                                         options=('-v', f'{ROOT}:/workspace:ro'))
        self.stderr = (lab.directory / (self.name + '-sdk.log')).open('x')
        try:
            self.process = subprocess.Popen(['docker', 'start', '--attach', '--interactive', self.name],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1)
        except Exception:
            self.stderr.close()
            raise
        try:
            self.connected = self.command('connect', password=password or lab.token, **kwargs)
        except Exception:
            self.close()
            raise

    def command(self, command, **kwargs):
        self.process.stdin.write(json.dumps({'command': command, **kwargs}) + '\n')
        self.process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(20):
                raise AssertionError(f'PG SDK bridge timed out during {command}')
        line = self.process.stdout.readline()
        assert line, f'PG SDK bridge exited during {command}'
        return json.loads(line)

    def query(self, sql='SELECT * FROM documents ORDER BY id', **kwargs):
        return self.command('query', sql=sql, **kwargs)

    def finished(self):
        def done():
            value = self.command('poll')
            return value['result'] if not value['running'] else None
        return self.lab.wait(done, 15)

    def kill(self):
        docker('kill', self.name, check=False)
        self.process.wait(timeout=5)

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.kill()
        self.process.stdout.close()
        if not self.process.stdin.closed:
            self.process.stdin.close()
        self.stderr.close()
        self.lab.remove(self.name)


@contextmanager
def client(lab, **kwargs):
    connection = Client(lab, **kwargs)
    try:
        yield connection
    finally:
        connection.close()


def psql(lab, sql, **kwargs):
    env = dict(os.environ, PGPASSWORD=kwargs.pop('password', lab.token))
    name = lab.client_container(PG, 'psql', '-XAt', '-h', '127.0.0.1', '-p', '5433',
        '-U', kwargs.pop('user', 'reader'), '-d', kwargs.pop('database', 'guradb'), '-v', 'ON_ERROR_STOP=1',
        '-F', '\t', '-P', 'null=<NULL>', options=('-e', 'PGPASSWORD', '-e', 'PGSSLMODE=disable'), env=env)
    try:
        assert not kwargs, kwargs
        return subprocess.run(['docker', 'start', '--attach', '--interactive', name], input=sql,
                              capture_output=True, text=True, timeout=20)
    finally:
        lab.remove(name)


def expected(rows):
    return [[r['id'], r['title'], r['active']] for r in rows]
