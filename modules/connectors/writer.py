"""Trusted single-host Iceberg append committer. Workers never hold this object."""
from contextlib import contextmanager
import fcntl
from pathlib import Path

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema
from pyiceberg.types import BooleanType, LongType, NestedField, StringType

from modules.common.contracts import digest, encoded, identifier, require

ARROW = pa.schema([pa.field('id', pa.int64(), nullable=False), pa.field('title', pa.string()), pa.field('active', pa.bool_())])
SCHEMA = Schema(NestedField(1, 'id', LongType(), required=True), NestedField(2, 'title', StringType()),
                NestedField(3, 'active', BooleanType()))


def validate(rows):
    require(isinstance(rows, list) and 1 <= len(rows) <= 1000, 'resource_limit')
    require(len(encoded(rows)) <= 2 << 20, 'resource_limit')
    ids = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'id', 'title', 'active'}, 'invalid_request', 'fixed writer schema required')
        require(type(row['id']) is int and -(1 << 63) <= row['id'] < (1 << 63), 'invalid_key')
        require(row['title'] is None or isinstance(row['title'], str), 'invalid_request')
        require(row['active'] is None or type(row['active']) is bool, 'invalid_request')
        require(row['id'] not in ids, 'duplicate_key')
        ids.add(row['id'])
    return digest(encoded(rows))


class Writer:
    def __init__(self, root, name):
        require(identifier(name), 'invalid_request')
        supplied = Path(root).absolute()
        require(not supplied.is_symlink(), 'invalid_request')
        supplied.mkdir(parents=True, exist_ok=True)
        self.root, self.name = supplied.resolve(), name
        self.identity = str(self.root)

    @contextmanager
    def locked(self):
        # Every writer for this source MUST use this file, including recovery.
        # It remains held if PG disconnects while the local source commit runs.
        with (self.root/'.committer.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def catalog(self):
        return load_catalog('managed', type='sql', uri='sqlite:///'+str(self.root/'catalog.db'),
                            warehouse=(self.root/'warehouse').as_uri())

    def initialize(self, managed):
        with self.locked():
            managed.register(self.name, self.identity)
            catalog = self.catalog()
            if ('managed',) not in catalog.list_namespaces():
                catalog.create_namespace('managed')
            if not catalog.table_exists(('managed', self.name)):
                catalog.create_table(('managed', self.name), schema=SCHEMA, properties={'format-version': '2'})
            self.table()

    def table(self):
        table = self.catalog().load_table(('managed', self.name))
        require(table.metadata.format_version == 2 and table.schema() == SCHEMA and not table.spec().fields and
                len(table.metadata.schemas) == 1 and len(table.metadata.partition_specs) == 1,
                'unsupported_source', 'managed schema/partition contract changed')
        require(all(snapshot.summary.operation.value == 'append' and
                    'gura.operation' in snapshot.summary.additional_properties for snapshot in table.snapshots()),
                'unsupported_source', 'managed table accepts append history only')
        snapshots = table.snapshots()
        previous = None
        for snapshot in snapshots:
            require(snapshot.parent_snapshot_id == previous, 'source_outcome_unknown', 'source history has a gap or branch')
            previous = snapshot.snapshot_id
        head = table.current_snapshot()
        require((head.snapshot_id if head else None) == previous and
                set(table.metadata.refs) <= {'main'}, 'source_outcome_unknown', 'source head changed outside committer')
        return table

    @staticmethod
    def match(table, row):
        matches = [snapshot for snapshot in table.snapshots()
                   if snapshot.summary.additional_properties.get('gura.operation') == row['operation']]
        require(len(matches) <= 1, 'source_conflict', 'multiple snapshots for one operation')
        if not matches:
            return None
        snapshot = matches[0]
        require(snapshot.summary.additional_properties.get('gura.fingerprint') == row['fingerprint'] and
                str(snapshot.parent_snapshot_id) == snapshot.summary.additional_properties.get('gura.parent') and
                str(row['generation']) == snapshot.summary.additional_properties.get('gura.generation'),
                'source_conflict')
        if row['status'] != 'prepared':
            require(snapshot.parent_snapshot_id == row['parent'], 'source_conflict')
        return snapshot

    def _reconcile_locked(self, managed, operation):
        with managed.committing(self.name, operation, self.identity) as (conn, row, _):
            require(row['status'] != 'aborted', 'operation_aborted')
            table = self.table()
            found = self.match(table, row)
            if found:
                if row['status'] == 'committed':
                    require(found.snapshot_id == row['snapshot'], 'source_conflict')
                    raw = Path(row['metadata'].removeprefix('file://')).read_bytes()
                    require(digest(raw) == row['metadata_sha256'], 'source_conflict')
                    return {'snapshot_id': row['snapshot'], 'metadata_uri': row['metadata'],
                            'metadata_sha256': row['metadata_sha256']}
                result = self.result(table, found.snapshot_id)
                managed.confirmed(conn, row, found.snapshot_id, result['metadata_uri'], result['metadata_sha256'])
                return result
            require(row['status'] != 'committed', 'source_conflict', 'confirmed snapshot missing')
            if row['status'] == 'committing':
                head = table.current_snapshot()
                require(row['parent'] == (head.snapshot_id if head else None),
                        'source_outcome_unknown', 'missing operation with changed parent; operator reconciliation required')
            return None

    @staticmethod
    def result(table, snapshot):
        return {'snapshot_id': snapshot, 'metadata_uri': table.metadata_location,
                'metadata_sha256': digest(Path(table.metadata_location.removeprefix('file://')).read_bytes())}

    def append(self, managed, operation, rows, fault=lambda stage: None):
        fingerprint = validate(rows)
        intent = managed.prepare(self.name, operation, fingerprint)
        return self.commit(managed, intent, rows, fault)

    def commit(self, managed, intent, rows, fault=lambda stage: None):
        fingerprint = validate(rows)
        require(fingerprint == intent['fingerprint'], 'operation_conflict')
        operation = intent['operation']
        with self.locked():
            # Reconcile every unknown source outcome before allowing another append.
            for pending in managed.pending(self.name):
                reconciled = self._reconcile_locked(managed, pending['operation'])
                if reconciled is None and pending['operation'] != operation:
                    managed.abort(self.name, pending['operation'])
            result = self._reconcile_locked(managed, operation)
            if result:
                return result
            table = self.table()
            require(len(table.snapshots()) < 32, 'resource_limit', 'managed reader supports at most 32 data files')
            current = table.current_snapshot()
            parent = current.snapshot_id if current else None
            existing = table.scan().to_arrow().to_pylist() if current else []
            require(len(existing)+len(rows) <= 10000, 'resource_limit')
            combined = existing + rows
            require(len(encoded(combined)) <= 8 << 20, 'resource_limit', 'cumulative managed input exceeds 8 MiB')
            require(pa.Table.from_pylist(combined, schema=ARROW).nbytes <= 16 << 20,
                    'resource_limit', 'cumulative decoded data exceeds 16 MiB')
            source_bytes = sum(task.file.file_size_in_bytes for task in table.scan().plan_files()) if current else 0
            require(source_bytes <= 12 << 20, 'resource_limit', 'existing source files exceed 12 MiB')
            require(not ({row['id'] for row in existing} & {row['id'] for row in rows}), 'duplicate_key')
            # Persist the parent BEFORE source commit, so process death cannot erase
            # our reconciliation boundary. The flock spans both PG transactions.
            with managed.committing(self.name, operation, self.identity) as (conn, row, generation):
                require(row['fingerprint'] == fingerprint, 'operation_conflict')
                require(row['generation'] == generation, 'stale_generation')
                managed.parent(conn, row, parent)
            fault('before_source')
            with managed.committing(self.name, operation, self.identity) as (conn, row, generation):
                require(row['generation'] == generation and row['parent'] == parent, 'stale_generation')
                # No worker-supplied URI/catalog or commit callback is accepted.
                table.append(pa.Table.from_pylist(rows, schema=ARROW), snapshot_properties={
                    'gura.operation': operation, 'gura.fingerprint': fingerprint, 'gura.parent': str(parent),
                    'gura.generation': str(generation)})
                fault('after_source')
                snapshot = table.current_snapshot().snapshot_id
                result = self.result(table, snapshot)
                managed.confirmed(conn, row, snapshot, result['metadata_uri'], result['metadata_sha256'])
            fault('after_confirm')
            return self.result(table, snapshot)
