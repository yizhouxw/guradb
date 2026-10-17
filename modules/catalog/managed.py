"""Independent source-commit intentions; no read-view publication authority."""
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from modules.common.contracts import identifier, require


class Managed:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.dsn, connect_timeout=3, row_factory=dict_row) as conn:
            conn.execute("SET LOCAL lock_timeout='5s'")
            yield conn

    def initialize(self):
        with self.transaction() as conn:
            conn.execute(Path(__file__).with_name('managed.sql').read_text())

    def register(self, name, root):
        require(identifier(name), 'invalid_request')
        with self.transaction() as conn:
            conn.execute('INSERT INTO gura_managed.tables(name,root) VALUES(%s,%s) ON CONFLICT(name) DO NOTHING', (name, root))
            row = conn.execute('SELECT * FROM gura_managed.tables WHERE name=%s', (name,)).fetchone()
            require(row['root'] == root, 'definition_conflict')

    def prepare(self, name, operation, fingerprint):
        require(isinstance(operation, str) and 0 < len(operation) <= 128, 'invalid_request')
        with self.transaction() as conn:
            table = conn.execute('SELECT * FROM gura_managed.tables WHERE name=%s FOR UPDATE', (name,)).fetchone()
            require(table is not None, 'not_found')
            row = conn.execute('SELECT * FROM gura_managed.intents WHERE name=%s AND operation=%s', (name, operation)).fetchone()
            if row:
                require(row['fingerprint'] == fingerprint, 'operation_conflict')
                return row
            generation = table['generation'] + 1
            conn.execute('UPDATE gura_managed.tables SET generation=%s WHERE name=%s', (generation, name))
            return conn.execute("INSERT INTO gura_managed.intents(name,operation,fingerprint,generation,status) "
                                "VALUES(%s,%s,%s,%s,'prepared') RETURNING *", (name, operation, fingerprint, generation)).fetchone()

    @contextmanager
    def committing(self, name, operation, root):
        # Call only while holding the source flock. A PG lease alone cannot fence
        # a disconnected process from completing a local Iceberg catalog commit.
        with self.transaction() as conn:
            table = conn.execute('SELECT * FROM gura_managed.tables WHERE name=%s FOR UPDATE', (name,)).fetchone()
            require(table is not None and table['root'] == root, 'definition_conflict')
            row = conn.execute('SELECT * FROM gura_managed.intents WHERE name=%s AND operation=%s FOR UPDATE', (name, operation)).fetchone()
            require(row is not None, 'not_found')
            yield conn, row, table['generation']

    @staticmethod
    def parent(conn, row, parent):
        if row['status'] == 'prepared':
            conn.execute("UPDATE gura_managed.intents SET parent=%s,status='committing' WHERE name=%s AND operation=%s",
                         (parent, row['name'], row['operation']))
        else:
            require(row['parent'] == parent, 'source_conflict')

    @staticmethod
    def confirmed(conn, row, snapshot, metadata, metadata_sha256):
        conn.execute("UPDATE gura_managed.intents SET status='committed',snapshot=%s,metadata=%s,metadata_sha256=%s WHERE name=%s AND operation=%s",
                     (snapshot, metadata, metadata_sha256, row['name'], row['operation']))

    def pending(self, name):
        with self.transaction() as conn:
            return conn.execute("SELECT * FROM gura_managed.intents WHERE name=%s AND status='committing' ORDER BY generation", (name,)).fetchall()

    def abort(self, name, operation):
        with self.transaction() as conn:
            conn.execute("UPDATE gura_managed.intents SET status='aborted' WHERE name=%s AND operation=%s AND status='committing'", (name, operation))
