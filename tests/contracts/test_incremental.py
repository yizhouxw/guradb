"""Independent Iceberg append history, fail-closed delta validation."""
from pathlib import Path
import json
import tempfile
import unittest

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField, LongType, StringType

from modules.common.contracts import Budget, Failure, digest, encoded
from modules.connectors.iceberg import snapshot
from modules.connectors.incremental import validate
from modules.storage.objects import Objects


class IncrementalContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        catalog = load_catalog('oracle', type='sql', uri='sqlite:///'+str(self.root/'catalog.db'),
                               warehouse=(self.root/'warehouse').as_uri())
        catalog.create_namespace('oracle')
        self.table = catalog.create_table('oracle.documents', schema=Schema(
            NestedField(1, 'id', LongType(), required=True), NestedField(2, 'title', StringType())))
        self.arrow = pa.schema([pa.field('id', pa.int64(), nullable=False), pa.field('title', pa.string())])
        self.append(1)
        first = self.target()
        self.base = snapshot(self.objects(), first['metadata_uri'], first['metadata_sha256'], first['snapshot_id'],
                             '11111111-1111-1111-1111-111111111111', 'documents', 'id', self.root/'copy')
        self.append(2)
        self.append(3)

    def objects(self):
        return Objects(self.root.as_uri(), Budget())

    def append(self, value):
        self.table.append(pa.Table.from_pylist([{'id': value, 'title': str(value)}], schema=self.arrow))

    def target(self):
        uri = self.table.metadata_location
        return {'metadata_uri': uri, 'metadata_sha256': digest(Path(uri.removeprefix('file://')).read_bytes()),
                'snapshot_id': self.table.current_snapshot().snapshot_id}

    def mutated(self, mutate):
        target = self.target()
        meta = json.loads(Path(target['metadata_uri'].removeprefix('file://')).read_bytes())
        mutate(meta)
        raw = encoded(meta)
        path = self.root/'mutated.json'
        path.write_bytes(raw)
        return dict(target, metadata_uri=path.as_uri(), metadata_sha256=digest(raw))

    def test_append_chain_matches_independent_reader(self):
        proof = validate(self.objects(), self.base, self.target())
        self.assertEqual(len(proof['chain']), 2)
        self.assertEqual(len(proof['added_files']), 2)
        self.assertEqual(sorted(self.table.scan().to_arrow()['id'].to_pylist()), [1, 2, 3])

    def test_rejects_history_gap_rewrite_schema_and_identity(self):
        mutations = [lambda m:m.update({'table-uuid': '22222222-2222-2222-2222-222222222222'}),
                     lambda m:m['schemas'][0]['fields'][0].update(name='different'),
                     lambda m:m['snapshots'][-1]['summary'].update(operation='overwrite'),
                     lambda m:m['snapshots'].pop(1),
                     lambda m:m['snapshots'][-1].update({'parent-snapshot-id': m['snapshots'][-1]['snapshot-id']}),
                     lambda m:m.update({'current-snapshot-id': m['snapshots'][0]['snapshot-id']})]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(Failure):
                validate(self.objects(), self.base, self.mutated(mutation))

    def test_old_file_byte_replacement_is_rejected(self):
        dependency = next(d for d in self.base['source']['dependencies'] if d['uri'].endswith('.parquet'))
        Path(dependency['uri'].removeprefix('file://')).write_bytes(b'replaced')
        with self.assertRaises(Failure):
            validate(self.objects(), self.base, self.target())
