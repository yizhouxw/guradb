"""Independent SQL unit executor. Real PG component driver owns concurrency/transport truth."""
from contextlib import contextmanager
import sqlite3
from modules.catalog.cf1a_admin import AdminOperations
from modules.catalog.cf1a_binding import Bindings
from modules.catalog.cf1a_mutation import Mutations
from modules.catalog.cf1a_store import CatalogStore, CommitUnknown
from modules.catalog.cf1a_pg import remaining


def row(value):
    result = dict(value)
    for key in ('singleton', 'terminalized', 'released'):
        if key in result and result[key] in (0, 1):
            result[key] = bool(result[key])
    return result


class Cursor:
    def __init__(self, values):
        self.values = values

    def fetchone(self):
        return self.values[0] if self.values else None

    def fetchall(self):
        return self.values


class Connection:
    def __init__(self, clock):
        self.clock = clock
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute("ATTACH DATABASE ':memory:' AS gura_cf1a")

    def execute(self, query, parameters=()):
        text = query if isinstance(query, str) else query.as_string(None)
        if 'pg_advisory_xact_lock' in text:
            return Cursor([])
        if 'clock_timestamp' in text:
            return Cursor([{'ms': self.clock()}])
        if text.startswith('CREATE SCHEMA'):
            text = text.replace('CREATE SCHEMA IF NOT EXISTS gura_cf1a;', '')
            text = text.replace('REFERENCES gura_cf1a.datasets', 'REFERENCES datasets')
            self.db.executescript(text)
            return Cursor([])
        text = text.replace(' FOR UPDATE', '').replace('%s', '?')
        result = self.db.execute(text, parameters)
        return Cursor([row(value) for value in result.fetchall()])

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.close()


class SqliteStore(CatalogStore):
    def __init__(self, protection, clock):
        self.protection = protection
        self.connection = Connection(clock)
        self.fault = ''

    @contextmanager
    def transaction(self, deadline):
        remaining(deadline)
        self.connection.db.execute('BEGIN')
        try:
            yield self.connection
            remaining(deadline)
            if self.fault == 'before_commit':
                self.fault = ''
                self.connection.db.rollback()
                raise CommitUnknown()
            self.connection.commit()
            if self.fault == 'after_commit':
                self.fault = ''
                raise CommitUnknown()
        except BaseException:
            self.connection.db.rollback()
            raise


def install(catalog, now):
    store = SqliteStore(catalog.store.protection, lambda: now['ms'])
    catalog.store = store
    catalog.admin = AdminOperations(store)
    catalog.mutations = Mutations(store)
    catalog.bindings = Bindings(store)
    catalog.initialize()
    return store
