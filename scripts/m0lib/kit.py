"""Real Parquet fixtures, isolated Docker services, HTTP client and PG oracle."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import boto3
from botocore.config import Config
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
RUST = 'guradb-rust:1.90.0'
S3 = 'chrislusf/seaweedfs:3.97@sha256:bb05d66d2963b1cc48073190781c3dd29e2c4c88a2ae2986bf58e38c86d89c6e'
PG = 'postgres:18-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c'
DATASET = '89b349e2-cc73-4c22-871d-c80a159d7789'


def docker(*args, input=None, check=True):
    return subprocess.run(['docker', *args], input=input, capture_output=True, text=True, check=check, timeout=120)


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def mapped(path):
    return '/workspace/' + str(path.resolve().relative_to(ROOT))


def fixture(directory, count=20):
    directory.mkdir(parents=True, exist_ok=True)
    rows = [{'id': i if i != count-1 else 9223372036854775807,
             'title': None if i % 7 == 0 else ['alpha', 'beta', '数据库', "agent's data"][i % 4],
             'active': None if i % 5 == 0 else i % 2 == 0} for i in range(count)]
    schema = pa.schema([pa.field('id', pa.int64(), nullable=False), pa.field('title', pa.string()), pa.field('active', pa.bool_())])
    files = []
    for n, part in enumerate((rows[:count//2], rows[count//2:])):
        path = directory / f'part-{n}.parquet'
        pq.write_table(pa.Table.from_pylist(part, schema=schema), path, compression='snappy', row_group_size=1024)
        raw = path.read_bytes()
        files.append({'fragment_id': f'fragment_{n}', 'key': path.name,
                      'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    manifest = {'schema_version': 1, 'dataset_id': DATASET, 'table_name': 'documents',
                'schema': [{'name': f.name, 'data_type': kind, 'nullable': f.nullable}
                           for f, kind in zip(schema, ['int8', 'text', 'bool'])],
                'backend': {'kind': 'local', 'root': mapped(directory)},
                'files': files, 'retention_mode': 'best-effort'}
    # This object must never be included by implicit listing.
    pq.write_table(pa.Table.from_pylist([{'id': -100, 'title': 'unlisted', 'active': True}], schema=schema), directory / 'unlisted.parquet')
    return manifest, rows


def truth(rows):
    return [[str(r['id']), r['title'], r['active']] for r in rows]


class Lab:
    def __init__(self, directory, count=20):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest, self.rows = fixture(self.directory / 'objects', count)
        self.names = []
        self.network = 'gura-' + uuid.uuid4().hex[:12]
        self.token = secrets.token_hex(24)
        self.other_token = secrets.token_hex(24)
        self.principals = [{'token_sha256': hashlib.sha256(token.encode()).hexdigest(),
                            'tenant_id': tenant, 'principal_id': 'reader', 'datasets': [DATASET]}
                           for token, tenant in [(self.token, 'tenant-a'), (self.other_token, 'tenant-b')]]
        self.auth = self.directory / 'auth.json'
        write(self.auth, {'principals': self.principals})
        self.server = None
        self.trace = []
        docker('network', 'create', self.network)

    def event(self, action, **values):
        self.trace.append({'sequence': len(self.trace), 'action': action, **values})
        write(self.directory / 'trace.json', self.trace)

    def container(self, image, *args, options=()):
        name = self.network + '-' + str(len(self.names))
        docker('run', '-d', '--name', name, '--network', self.network, *options, image, *args)
        self.names.append(name)
        mounts = json.loads(docker('inspect', '--format', '{{json .Mounts}}', name).stdout)
        self.event('container_created', name=name, volumes=[m['Name'] for m in mounts if m['Type']=='volume'])
        return name

    def port(self, name, port):
        return docker('port', name, str(port)).stdout.strip().rsplit(':', 1)[1]

    def wait(self, predicate, seconds=30):
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            try:
                result = predicate()
                if result:
                    return result
            except Exception as error:
                last = error
            time.sleep(.05)
        raise AssertionError(f'service did not become ready: {last}')

    def s3(self):
        credentials = {'identities': [{'name': 'test-driver', 'credentials': [{'accessKey': 'm0-test-key', 'secretKey': 'm0-test-secret'}],
                                       'actions': ['Admin', 'Read', 'Write', 'List', 'Tagging']}]}
        config = self.directory / 's3.json'
        write(config, credentials)
        self.store = self.container(S3, 'server', '-s3', '-ip=s3', '-ip.bind=0.0.0.0', '-volume.max=1',
                                    '-master.volumeSizeLimitMB=32', '-master.telemetry=false', '-s3.config=' + mapped(config),
                                    options=('--network-alias', 's3', '-p', '127.0.0.1::8333', '-v', f'{ROOT}:/workspace:ro'))
        endpoint = 'http://127.0.0.1:' + self.port(self.store, 8333)
        self.client = boto3.client('s3', endpoint_url=endpoint, region_name='us-east-1', aws_access_key_id='m0-test-key',
                                   aws_secret_access_key='m0-test-secret', config=Config(signature_version='s3v4', retries={'max_attempts': 0},
                                                                                    connect_timeout=2, read_timeout=3, s3={'addressing_style': 'path'}))
        self.wait(lambda: self.client.list_buckets() is not None)
        self.client.create_bucket(Bucket='m0-data')
        for path in (self.directory / 'objects').glob('*.parquet'):
            self.client.put_object(Bucket='m0-data', Key=path.name, Body=path.read_bytes())
        self.manifest['backend'] = {'kind': 's3', 'bucket': 'm0-data', 'region': 'us-east-1', 'endpoint': 'http://s3:8333', 'allow_http': True}
        self.event('s3_ready', image=S3)

    def reject_manifest(self, manifest, expected="invalid_manifest", bad_pin=False):
        path = self.directory / 'invalid-manifest.json'
        write(path, manifest)
        config = self.directory / 'invalid-server.json'
        write(config, {'auth_file':mapped(self.auth), 'manifests':[{'path':mapped(path),
              'sha256':'0'*64 if bad_pin else hashlib.sha256(path.read_bytes()).hexdigest()}]})
        result = docker('run','--rm','--network','none','-v',f'{ROOT}:/workspace:ro',RUST,
                        '/workspace/target/debug/guradb','--config',mapped(config),check=False)
        assert result.returncode == 1 and expected in result.stderr, result.stderr

    def start(self, limits=None, pg_listen=None):
        if self.server:
            docker('rm', '-f', '-v', self.server, check=False)
        path = self.directory / 'manifest.json'
        write(path, self.manifest)
        config = {'listen': '0.0.0.0:8080', 'auth_file': mapped(self.auth),
                  'manifests': [{'path': mapped(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}], 'limits': limits or {}}
        if pg_listen is not None:
            config['pg_listen'] = pg_listen
        server_config = self.directory / 'server.json'
        write(server_config, config)
        self.server = self.container(RUST, '/workspace/target/debug/guradb', '--config', mapped(server_config),
                                     options=('-v', f'{ROOT}:/workspace:ro', '-p', '127.0.0.1::8080',
                                              '-e', 'AWS_ACCESS_KEY_ID=m0-test-key', '-e', 'AWS_SECRET_ACCESS_KEY=m0-test-secret'))
        self.url = 'http://127.0.0.1:' + self.port(self.server, 8080)
        try:
            self.wait(lambda: urllib.request.urlopen(self.url + '/healthz', timeout=1).status == 200)
        except Exception:
            raise AssertionError(docker('logs', self.server).stdout + docker('logs', self.server).stderr)
        self.event('server_started', manifest=config['manifests'][0]['sha256'], limits=limits or {}, pg_listen=pg_listen)

    def http(self, method, path, body=None, token=None, auth=True):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['Authorization'] = 'Bearer ' + (token or self.token)
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        return response.status, json.loads(response.read())

    def submit(self, sql='SELECT * FROM documents ORDER BY id', **kwargs):
        status, body = self.http('POST', '/v1/queries', {'sql': sql, **kwargs})
        assert status == 202, (status, body)
        return body

    def terminal(self, handle):
        def done():
            code, current = self.http('GET', '/v1/queries/' + handle['query_id'])
            assert code == 200, (code, current)
            return current if current['status'] in ['succeeded', 'failed', 'cancelled'] else None
        return self.wait(done, 15)

    def query(self, sql='SELECT * FROM documents ORDER BY id', **kwargs):
        handle = self.terminal(self.submit(sql, **kwargs))
        assert handle['status'] == 'succeeded', handle
        code, page = self.http('GET', '/v1/queries/' + handle['query_id'] + '/results?page_size=1000')
        assert code == 200, page
        return handle, page

    def rss(self):
        status = docker('exec', self.server, 'cat', '/proc/1/status').stdout
        return int(next(line for line in status.splitlines() if line.startswith('VmHWM:')).split()[1]) * 1024

    def postgres(self):
        self.pg = self.container(PG, options=('-e', 'POSTGRES_HOST_AUTH_METHOD=trust'))
        self.wait(lambda: docker('exec', self.pg, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', check=False).returncode == 0)
        lines = ['CREATE TABLE documents(id bigint NOT NULL, title text COLLATE "C", active boolean);']
        for row in self.rows:
            text = 'NULL' if row['title'] is None else "'" + row['title'].replace("'", "''") + "'"
            active = 'NULL' if row['active'] is None else str(row['active']).lower()
            lines.append(f"INSERT INTO documents VALUES ({row['id']},{text},{active});")
        docker('exec', '-i', self.pg, 'psql', '-U', 'postgres', '-v', 'ON_ERROR_STOP=1', input='\n'.join(lines))
        self.event('postgres_ready', image=PG)

    def oracle(self, sql):
        result = docker('exec', '-i', self.pg, 'psql', '-XAt', '-U', 'postgres', '-v', 'ON_ERROR_STOP=1',
                        input='SELECT COALESCE(json_agg(t),\'[]\'::json) FROM (' + sql + ') AS t;')
        rows = json.loads(result.stdout)
        return [[str(v) if isinstance(v, int) and not isinstance(v, bool) else v for v in row.values()] for row in rows]

    def close(self):
        for name in reversed(self.names):
            docker('unpause', name, check=False)
            logs = docker('logs', name, check=False)
            (self.directory / (name + '.log')).write_text(logs.stdout + logs.stderr)
            docker('rm', '-f', '-v', name, check=False)
        docker('network', 'rm', self.network, check=False)


@contextmanager
def laboratory(directory, count=20):
    lab = Lab(directory, count)
    try:
        yield lab
    finally:
        lab.close()
