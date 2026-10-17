"""Independent Iceberg append history, fail-closed delta validation."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch, Mock

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField, LongType, StringType

from modules.common.contracts import Budget, Failure, digest, encoded, key
from modules.connectors.iceberg import snapshot
from modules.connectors.incremental import validate, verify_identity
from modules.storage.objects import Objects
from modules.query.snapshot import construct
from modules.index.retrieval import load_bundle


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

    def test_old_bundle_without_identity_requires_snapshot(self):
        for dependency in self.base['source']['dependencies']:
            dependency.pop('identity', None)
        with self.assertRaises(Failure) as rejected:
            validate(self.objects(), self.base, self.target())
        self.assertEqual(rejected.exception.code, 'unsupported_change')

    def test_s3_identity_checks_head_without_get(self):
        s3 = Mock()
        s3.head_object.return_value = {'ETag': 'etag', 'VersionId': 'version', 'ContentLength': 123}
        objects = Objects('s3://bucket/table', Budget(), s3)
        dependency = {'uri': 's3://bucket/table/data.parquet', 'identity': {
            'kind': 's3-head-v1', 'etag': 'etag', 'version': 'version', 'size': 123}}
        verify_identity(objects, dependency)
        s3.get_object.assert_not_called()
        self.assertEqual(objects.budget.reads, 1)
        s3.head_object.return_value['ETag'] = 'different'
        with self.assertRaises(Failure):
            verify_identity(objects, dependency)

    def test_source_replacement_during_digest_is_rejected(self):
        path = self.root/'race.bin'
        path.write_bytes(b'old bytes')
        def racing_digest(raw):
            path.write_bytes(b'new bytes')
            return digest(raw)
        with patch('modules.storage.objects.digest', racing_digest), self.assertRaises(Failure) as rejected:
            self.objects().read(path.as_uri())
        self.assertEqual(rejected.exception.code, 'source_invalid')

    def test_inherited_decoded_rows_count_toward_budget(self):
        inherited = dict(self.base, rows=[{'logical_key': key(1, 'long'),
                                          'values': {'id': 1, 'title': 'x'*(64 << 20)}}])
        selected = self.target()
        with self.assertRaises(Failure) as rejected:
            snapshot(self.objects(), selected['metadata_uri'], selected['metadata_sha256'], selected['snapshot_id'],
                     '11111111-1111-1111-1111-111111111111', 'documents', 'id', self.root/'budget-copy',
                     inherited=inherited, added_files=set())
        self.assertEqual(rejected.exception.code, 'resource_limit')

    def test_exhausted_request_budget_never_sends_head(self):
        s3 = Mock()
        objects = Objects('s3://bucket/table', Budget(), s3)
        objects.budget.reads = objects.budget.limits['reads']
        dependency = {'uri': 's3://bucket/table/data.parquet', 'identity': {
            'kind': 's3-head-v1', 'etag': 'etag', 'version': None, 'size': 123}}
        with self.assertRaises(Failure) as rejected:
            verify_identity(objects, dependency)
        self.assertEqual(rejected.exception.code, 'resource_limit')
        s3.head_object.assert_not_called()

    def test_head_deadline_is_checked_after_response(self):
        s3 = Mock()
        objects = Objects('s3://bucket/table', Budget(), s3)
        def delayed(**kwargs):
            objects.budget.deadline = 0
            return {'ETag': 'etag', 'ContentLength': 123}
        s3.head_object.side_effect = delayed
        dependency = {'uri': 's3://bucket/table/data.parquet', 'identity': {
            'kind': 's3-head-v1', 'etag': 'etag', 'version': None, 'size': 123}}
        with self.assertRaises(Failure) as rejected:
            verify_identity(objects, dependency)
        self.assertEqual(rejected.exception.code, 'timeout')
        self.assertEqual(objects.budget.reads, 1)


class IncrementalBuildContract(IncrementalContract):
    def test_build_reads_only_added_source_files_and_inherits_versions(self):
        dataset = '11111111-1111-1111-1111-111111111111'
        class Control:
            def dataset(inner, _):
                return {'id': dataset, 'name': 'documents', 'definition': {
                    'root': self.root.as_uri(), 'key_field': 'id', 'text_field': 'title'}}
            def begin(inner, _, operation, target):
                inner.current = {'id': operation, 'status': 'building', 'target': target}
                return inner.current
            def ready(inner, _, artifact):
                inner.current.update(status='ready', artifact=artifact)
            def run(inner, _):
                return inner.current
            def fail(inner, _, error):
                inner.current.update(status='failed', error=error)
        control = Control()
        old_target = dict(self.base['source'])
        def selected(source, ids):
            records = [{'logical_key': key(i, 'long'),
                        'vector': [float(i)], 'media': []} for i in ids]
            raw = encoded({'model': 'test', 'dimension': 1, 'metric': 'squared_l2',
                           'preprocessing': 'identity-v1', 'records': records})
            path = self.root / ('features-' + str(len(ids)) + '.json')
            path.write_bytes(raw)
            return {**{k: source[k] for k in ('metadata_uri', 'metadata_sha256')},
                    'snapshot_id': int(source['snapshot_id']), 'features_uri': path.as_uri(),
                    'features_sha256': digest(raw)}
        first = construct(control, dataset, 'first', selected(old_target, [1]), self.root/'builds')
        base = load_bundle(first['artifact'], Budget())
        proof = validate(self.objects(), base, self.target())
        old_paths = {d['uri'] for d in base['source']['dependencies'] if d['uri'].endswith('.parquet')}
        calls, original = [], Objects.read
        def read(objects, uri, *args, **kwargs):
            calls.append(uri)
            if uri in old_paths:
                raise AssertionError('old source Parquet was fetched')
            return original(objects, uri, *args, **kwargs)
        with patch.object(Objects, 'read', read):
            candidate = construct(control, dataset, 'delta', selected(self.target(), [1, 2, 3]),
                                  self.root/'builds', inherited=base, added_files=set(proof['added_files']))
        result = load_bundle(candidate['artifact'], Budget())
        self.assertEqual(sorted(r['values']['id'] for r in result['rows']), [1, 2, 3])
        self.assertEqual(result['rows'][0]['record_version'], base['rows'][0]['record_version'])
        self.assertEqual({uri for uri in calls if uri.endswith('.parquet')}, set(proof['added_files']))
        self.assertNotEqual(result['rows'][1]['record_version'], base['rows'][0]['record_version'])
        from modules.storage.objects import get
        import shutil
        shutil.rmtree(self.root/'builds'/'first')
        self.assertEqual(len(load_bundle(candidate['artifact'], Budget())['rows']), 3)
        self.assertTrue(all(get(d['copy']) for d in result['source']['dependencies']))
        changed = selected(self.target(), [1, 2, 3])
        path = Path(changed['features_uri'].removeprefix('file://'))
        value = json.loads(path.read_bytes())
        value['records'][0]['vector'] = [999.0]
        path.write_bytes(encoded(value))
        changed['features_sha256'] = digest(path.read_bytes())
        with self.assertRaises(Failure) as rejected:
            construct(control, dataset, 'changed', changed, self.root/'builds', inherited=result, added_files=set())
        self.assertEqual(rejected.exception.code, 'unsupported_change')
