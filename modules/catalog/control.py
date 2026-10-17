"""PG-only control metadata, row-lock fencing, authorization and retention."""
from contextlib import contextmanager
import json
from pathlib import Path
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from modules.common.contracts import digest, encoded, identifier, require


class Control:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def transaction(self):
        # No reconnect/replay of unknown commit results. Caller reconciles operation ID.
        with psycopg.connect(self.dsn, connect_timeout=3, row_factory=dict_row) as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            conn.execute("SET LOCAL lock_timeout = '3s'")
            yield conn

    def initialize(self):
        with self.transaction() as conn:
            conn.execute(Path(__file__).with_name('schema.sql').read_text())
            require(conn.execute('SELECT version FROM gura_m1.version').fetchone()['version'] == 1, 'incompatible_catalog')

    def register(self, dataset, tenant, name, definition):
        uuid.UUID(dataset)
        require(identifier(name) and isinstance(tenant, str) and 0 < len(tenant) <= 128, 'invalid_request')
        require(len(encoded(definition)) <= 65536, 'resource_limit')
        with self.transaction() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(7101710)')
            existing = conn.execute('SELECT * FROM gura_m1.datasets WHERE id=%s FOR UPDATE', (dataset,)).fetchone()
            if existing:
                require(existing['tenant'] == tenant and existing['name'] == name and existing['definition'] == definition,
                        'definition_conflict', 'dataset identity/definition is immutable')
            else:
                require(conn.execute('SELECT count(*) AS n FROM gura_m1.datasets').fetchone()['n'] < 16, 'resource_limit')
                conn.execute('INSERT INTO gura_m1.datasets(id,tenant,name,definition) VALUES (%s,%s,%s,%s)',
                             (dataset, tenant, name, Jsonb(definition)))

    def begin(self, dataset, operation, target):
        require(isinstance(operation, str) and 0 < len(operation) <= 128, 'invalid_request')
        require(len(encoded(target)) <= 65536, 'resource_limit')
        fingerprint = digest(encoded(target))
        with self.transaction() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(7101710)')
            ds = conn.execute('SELECT * FROM gura_m1.datasets WHERE id=%s FOR UPDATE', (dataset,)).fetchone()
            require(ds is not None, 'not_found')
            previous = conn.execute('SELECT * FROM gura_m1.runs WHERE dataset=%s AND operation=%s', (dataset, operation)).fetchone()
            if previous:
                require(previous['fingerprint'] == fingerprint, 'operation_conflict', 'operation ID reused with different input')
                return previous
            require(conn.execute('SELECT count(*) AS n FROM gura_m1.runs').fetchone()['n'] < 128, 'resource_limit')
            generation = ds['generation'] + 1
            conn.execute('UPDATE gura_m1.datasets SET generation=%s WHERE id=%s', (generation, dataset))
            return conn.execute("INSERT INTO gura_m1.runs(id,dataset,operation,fingerprint,generation,target,status) "
                                "VALUES(%s,%s,%s,%s,%s,%s,'building') RETURNING *",
                                (uuid.uuid4(), dataset, operation, fingerprint, generation, Jsonb(target))).fetchone()

    def dataset(self, dataset):
        with self.transaction() as conn:
            row = conn.execute('SELECT * FROM gura_m1.datasets WHERE id=%s', (dataset,)).fetchone()
            require(row is not None, 'not_found')
            return row

    def run(self, run):
        with self.transaction() as conn:
            row = conn.execute('SELECT * FROM gura_m1.runs WHERE id=%s', (run,)).fetchone()
            require(row is not None, 'not_found')
            return row

    def ready(self, run, artifact):
        require(len(encoded(artifact)) <= 4096, 'resource_limit')
        with self.transaction() as conn:
            row = conn.execute('SELECT * FROM gura_m1.runs WHERE id=%s FOR UPDATE', (run,)).fetchone()
            require(row is not None, 'not_found')
            if row['status'] in ('ready', 'published'):
                require(row['artifact'] == artifact, 'artifact_conflict')
                return
            require(row['status'] == 'building', 'invalid_state')
            conn.execute("UPDATE gura_m1.runs SET status='ready',artifact=%s WHERE id=%s", (Jsonb(artifact), run))

    def fail(self, run, code):
        with self.transaction() as conn:
            conn.execute("UPDATE gura_m1.runs SET status='failed',error=%s WHERE id=%s AND status='building'", (code, run))

    def publish(self, run, expected_epoch):
        with self.transaction() as conn:
            row = conn.execute('SELECT * FROM gura_m1.runs WHERE id=%s', (run,)).fetchone()
            require(row is not None, 'not_found')
            ds = conn.execute('SELECT * FROM gura_m1.datasets WHERE id=%s FOR UPDATE', (row['dataset'],)).fetchone()
            # Reconcile after a lost response, including callers with the old expected epoch.
            if ds['published'] == row['id']:
                return ds['epoch']
            require(row['generation'] == ds['generation'], 'stale_generation', 'newer Snapshot attempt fences this worker')
            require(ds['epoch'] == expected_epoch, 'publication_conflict', 'published epoch changed')
            row = conn.execute('SELECT * FROM gura_m1.runs WHERE id=%s FOR UPDATE', (run,)).fetchone()
            require(row['status'] == 'ready', 'not_ready')
            conn.execute("UPDATE gura_m1.runs SET status='published' WHERE id=%s", (run,))
            conn.execute('UPDATE gura_m1.datasets SET published=%s,epoch=epoch+1 WHERE id=%s', (run, row['dataset']))
            return ds['epoch'] + 1

    def principal(self, token):
        require(isinstance(token, str) and 0 < len(token) <= 512, 'unauthorized')
        hashed = digest(token.encode())
        with self.transaction() as conn:
            p = conn.execute('SELECT * FROM gura_m1.principals WHERE token_sha256=%s', (hashed,)).fetchone()
            require(p is not None, 'unauthorized', 'invalid authentication')
            return p

    @staticmethod
    def authorize(conn, principal, dataset):
        # Token and grant both rechecked, including every result/worker execution point.
        row = conn.execute('SELECT d.* FROM gura_m1.datasets d JOIN gura_m1.grants g ON g.dataset=d.id '
                           'JOIN gura_m1.principals p ON p.tenant=g.tenant AND p.subject=g.subject '
                           'WHERE d.id=%s AND d.tenant=g.tenant AND p.token_sha256=%s AND p.tenant=%s AND p.subject=%s',
                           (dataset, principal['token_sha256'], principal['tenant'], principal['subject'])).fetchone()
        require(row is not None, 'not_found', 'dataset unavailable')
        return row

    def grant(self, token_hash, tenant, subject, dataset):
        require(len(token_hash) == 64 and len(tenant) <= 128 and len(subject) <= 128, 'invalid_request')
        with self.transaction() as conn:
            ds = conn.execute('SELECT tenant FROM gura_m1.datasets WHERE id=%s', (dataset,)).fetchone()
            require(ds is not None and ds['tenant'] == tenant, 'not_found')
            conn.execute('INSERT INTO gura_m1.principals VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (token_hash, tenant, subject))
            conn.execute('INSERT INTO gura_m1.grants VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (tenant, subject, dataset))

    def revoke(self, tenant, subject, dataset):
        with self.transaction() as conn:
            conn.execute('DELETE FROM gura_m1.grants WHERE tenant=%s AND subject=%s AND dataset=%s', (tenant, subject, dataset))

    def pin(self, run, owner):
        require(isinstance(owner, str) and 0 < len(owner) <= 128, 'invalid_request')
        with self.transaction() as conn:
            row = conn.execute('SELECT status FROM gura_m1.runs WHERE id=%s FOR UPDATE', (run,)).fetchone()
            require(row is not None and row['status'] == 'published', 'not_ready')
            require(conn.execute('SELECT count(*) AS n FROM gura_m1.pins').fetchone()['n'] < 1024, 'resource_limit')
            conn.execute('INSERT INTO gura_m1.pins(run,owner) VALUES(%s,%s) ON CONFLICT DO NOTHING', (run, owner))

    def unpin(self, run, owner):
        with self.transaction() as conn:
            conn.execute("DELETE FROM gura_m1.pins WHERE run=%s AND owner=%s AND scope='manual'", (run, owner))

    def retire(self, run):
        with self.transaction() as conn:
            row = conn.execute('SELECT * FROM gura_m1.runs WHERE id=%s', (run,)).fetchone()
            require(row is not None, 'not_found')
            ds = conn.execute('SELECT * FROM gura_m1.datasets WHERE id=%s FOR UPDATE', (row['dataset'],)).fetchone()
            row = conn.execute('SELECT * FROM gura_m1.runs WHERE id=%s FOR UPDATE', (run,)).fetchone()
            require(ds['published'] != row['id'], 'still_referenced', 'current published view cannot retire')
            require(row['status'] in ('published','failed','ready','retiring'), 'invalid_state')
            require(conn.execute('SELECT 1 FROM gura_m1.pins WHERE run=%s', (run,)).fetchone() is None, 'still_pinned')
            conn.execute("UPDATE gura_m1.runs SET status='retiring' WHERE id=%s", (run,))
            return row
