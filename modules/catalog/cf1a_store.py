"""Small PG metadata store; no automatic reconnect or transaction replay."""
from contextlib import contextmanager
from pathlib import Path
import time

import psycopg
from psycopg import sql

from modules.common.cf1a_primitives import ContractFailure, canonical, require, validate_shape
from modules.catalog.cf1a_codec import LIMITS, MAX_METADATA_BYTES, counter, identity_values, sha, stored_contract
from modules.catalog.cf1a_pg import connect, normalized_dsn, remaining


class CommitUnknown(Exception):
    """The commit was attempted; the caller must reconcile its stable identity."""


class CatalogStore:
    def __init__(self, dsn, protection):
        self.dsn = normalized_dsn(dsn)
        self.protection = protection

    @staticmethod
    def commit(conn):
        # This boundary is fault-injected after a real PG commit in component tests.
        conn.commit()

    @contextmanager
    def transaction(self, deadline):
        conn = None
        committing = False
        try:
            conn = connect(self.dsn, deadline)
            millis = max(1, int(remaining(deadline) * 1000))
            conn.execute("SELECT set_config('statement_timeout',%s,true), "
                         "set_config('lock_timeout',%s,true)", (f'{millis}ms', f'{millis}ms'))
            yield conn
            remaining(deadline)
            committing = True
            self.commit(conn)
            remaining(deadline)
        except BaseException as error:
            if committing:
                raise CommitUnknown('catalog commit outcome unknown') from None
            if not isinstance(error, Exception):
                raise
            if isinstance(error, ContractFailure):
                raise
            if isinstance(error, psycopg.errors.QueryCanceled) or isinstance(error, psycopg.errors.LockNotAvailable):
                raise ContractFailure('deadline', 'catalog operation deadline reached') from None
            raise ContractFailure('backend_unavailable', 'catalog operation unavailable') from None
        finally:
            # A pre-commit close aborts the transaction. No blocking rollback or
            # retry is allowed after the deadline; a sent COMMIT remains unknown.
            if conn is not None:
                try:
                    conn.close()
                except BaseException:
                    if committing:
                        raise CommitUnknown('catalog commit outcome unknown') from None
                    # Preserve the original pre-commit error or interruption.

    @staticmethod
    def now(conn):
        return conn.execute("SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS ms").fetchone()['ms']

    def initialize(self):
        try:
            with self.transaction(time.monotonic() + 5) as conn:
                conn.execute('SELECT pg_advisory_xact_lock(60210021)')
                conn.execute(Path(__file__).with_name('cf1a_schema.sql').read_text())
                versions = conn.execute('SELECT singleton,version FROM gura_cf1a.version').fetchall()
                require(versions == [{'singleton': True, 'version': 1}], 'unsupported catalog schema version', 'unsupported_version')
        except CommitUnknown:
            raise ContractFailure('outcome_unknown', 'reinitialize the same catalog and check version') from None

    @staticmethod
    def dataset(conn, tenant, dataset):
        validate_shape(tenant, 'id')
        validate_shape(dataset, 'id')
        row = conn.execute('SELECT * FROM gura_cf1a.datasets WHERE dataset=%s FOR UPDATE', (dataset,)).fetchone()
        require(row is not None and row['tenant'] == tenant, 'catalog dataset unavailable', 'unauthorized')
        for name in ('generation', 'owner_epoch', 'policy_epoch', 'sequence'):
            counter(row[name])
        require(row['owner_epoch'] > 0 and row['policy_epoch'] > 0, 'invalid stored catalog epoch')
        validate_shape(row['owner_subject'], 'id')
        for name in ('head_revision', 'published', 'active_plan'):
            if row[name]:
                validate_shape(row[name], 'id')
        require(type(row['metadata_bytes']) is int and 0 <= row['metadata_bytes'] <= MAX_METADATA_BYTES,
                'invalid stored catalog byte accounting')
        return row

    @staticmethod
    def quota(conn, dataset, table, additional=1):
        require(table in LIMITS and table != 'datasets' and type(additional) is int and additional > 0,
                'invalid catalog quota request')
        count = conn.execute(sql.SQL('SELECT count(*) AS n FROM gura_cf1a.{} WHERE dataset=%s').format(
            sql.Identifier(table)), (dataset,)).fetchone()['n']
        require(count + additional <= LIMITS[table], 'catalog identity capacity reached', 'resource_limit')

    @staticmethod
    def charge(conn, dataset, delta):
        require(type(delta) is int, 'invalid catalog byte delta')
        row = conn.execute('UPDATE gura_cf1a.datasets SET metadata_bytes=metadata_bytes+%s '
                           'WHERE dataset=%s AND metadata_bytes+%s BETWEEN 0 AND %s RETURNING metadata_bytes',
                           (delta, dataset, delta, MAX_METADATA_BYTES)).fetchone()
        require(row is not None, 'catalog metadata byte capacity reached', 'resource_limit')

    def identities(self, conn, dataset, target, create=False, allow_missing=False):
        for kind, identity, value in identity_values(target):
            body = canonical(value)
            old = conn.execute('SELECT body,sha256 FROM gura_cf1a.identities '
                               'WHERE dataset=%s AND kind=%s AND id=%s', (dataset, kind, identity)).fetchone()
            if old is not None:
                require(sha(bytes(old['body'])) == old['sha256'], 'stored identity digest mismatch')
                require(bytes(old['body']) == body, 'catalog identity content conflict', 'conflict')
            else:
                require(create or allow_missing, 'stored target has a missing identity')
                if not create:
                    continue
                self.quota(conn, dataset, 'identities')
                self.charge(conn, dataset, len(body))
                conn.execute('INSERT INTO gura_cf1a.identities VALUES(%s,%s,%s,%s,%s)',
                             (dataset, kind, identity, body, sha(body)))

    def target(self, conn, tenant, dataset, view_id):
        row = conn.execute('SELECT * FROM gura_cf1a.targets WHERE dataset=%s AND view_id=%s',
                           (dataset, view_id)).fetchone()
        require(row is not None, 'catalog view unavailable', 'conflict')
        target = stored_contract(row['body'], row['sha256'], 'read_descriptors')
        value = target.value
        require(value['resource']['tenant_id'] == tenant and value['resource']['dataset_id'] == dataset and
                value['view']['read_view_id'] == view_id and value['revision']['data_revision_id'] == row['revision_id'],
                'stored target lookup mismatch')
        for name in ('register_generation', 'owner_epoch', 'publish_generation', 'publication_sequence'):
            validate_shape(row[name], 'positive')
        require(row['publish_generation'] == counter(row['register_generation'], 1) and
                value['view']['publication_generation'] == row['publish_generation'] and
                value['view']['publication_sequence'] == row['publication_sequence'] and
                row['state'] in ('registered', 'superseded', 'fenced', 'published'), 'stored target lineage mismatch')
        validate_shape(row['owner_subject'], 'id')
        validate_shape(row['register_operation'], 'id')
        if row['prior_view']:
            validate_shape(row['prior_view'], 'id')
            prior = conn.execute('SELECT state,publication_sequence FROM gura_cf1a.targets WHERE dataset=%s AND view_id=%s',
                                 (dataset, row['prior_view'])).fetchone()
            require(prior is not None and prior['state'] == 'published' and
                    prior['publication_sequence'] + 1 == row['publication_sequence'], 'stored prior view mismatch')
        else:
            require(row['publication_sequence'] == 1, 'missing prior published view')
        self.identities(conn, dataset, target)
        return row, target
