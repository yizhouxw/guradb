"""New SQL target assembly: fake SDK plus independent real PyArrow truth.

Definitions only until the authorized unit window. No real S3/PG evidence.
"""
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import pyarrow.parquet as pq

from modules.common.cf1a_primitives import ContractFailure, digest
from tests.source_support.fixed_acceptance import upload_multisource
from tests.source_support.fixed_backend_cases import many_rows
from tests.source_support.fixed_catalog_pair import prepare_target
from tests.source_support.fixed_fd_fixture import SQL_FIELDS, expected_cells, sql_target_from_uploaded
from tests.source_support.fixed_fixture import encoded
from tests.unit import test_cf1a_catalog_controlled as catalog_fixture


class FakeSdk:
    def __init__(self):
        self.puts = []

    def put_object(self, **arguments):
        self.puts.append(arguments)
        return {'VersionId': 'unit-version-' + str(len(self.puts))}


class SqlTargetFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.client = FakeSdk()

    def uploaded(self, dual=False):
        options = {}
        if dual:
            rows = many_rows()
            options = {'source_rows': [('source-main', 'p04-main-v2', rows[:65]),
                                      ('source-mirror', 'p04-mirror-v2', rows[65:])],
                       'writer_options': {'row_group_size': 16}}
        return upload_multisource(self.client, self.root / ('old-dual' if dual else 'old-full'), **options)

    def target(self, fixture, name='new'):
        return sql_target_from_uploaded(fixture, self.client, self.root / name, 'fd-dataset', 'fd-schema',
                                        protected_until_unix_ms=time.time_ns() // 1000000 + 300000)

    def verify_target(self, fixture, result):
        value = result['target'].value
        self.assertEqual(result['target'].kind, 'read_descriptors')
        self.assertEqual(value['resource']['fields'], SQL_FIELDS)
        self.assertEqual(len(value['revision']['objects']), 4)
        self.assertEqual(len(result['objects']), 4)
        self.assertEqual(len(self.client.puts), 12)  # Old four objects and new two, each versioned twice.
        new_puts = self.client.puts[8:]
        self.assertTrue(all(call['Key'].endswith('/metadata.json') for call in new_puts))
        independent = []
        for index, metadata in enumerate(fixture['source_metadata']):
            old = metadata['files'][0]['object']
            self.assertEqual(result['parquet_refs'][index], old)
            raw = fixture['objects'][encoded(old)]
            self.assertIs(result['objects'][encoded(old)], raw)
            source = value['revision']['sources'][index]
            previous = fixture['binding'].value['revision']['sources'][index]
            self.assertNotEqual(source['source_version_id'], previous['source_version_id'])
            self.assertNotEqual(source['snapshot_id'], previous['snapshot_id'])
            self.assertEqual(result['source_metadata'][index]['source_schema'], metadata['source_schema'])
            self.assertEqual([field['source_field_id'] for field in source['field_mapping']],
                             [100 * (index + 1) + offset for offset in (1, 2, 5, 4, 6, 3)])
            self.assertEqual([field['resource_field_id'] for field in source['field_mapping']], [1, 2, 3, 4, 6, 17])
            for row in pq.ParquetFile(io.BytesIO(raw)).read().to_pylist():
                independent.append(row)
        # Decode all original Parquet cells independently, including null/int8;
        # production reader/adapter is not used by this oracle.
        self.assertEqual(result['truth'], expected_cells(independent))
        self.assertEqual(len(result['truth']), len(fixture['rows']))
        self.assertEqual(result['truth'], expected_cells(fixture['rows']))
        self.assertTrue(any(cell['type'] == 'null' for row in result['truth'] for cell in row['cells']))
        self.assertTrue(any(cell['type'] == 'int8' for row in result['truth'] for cell in row['cells']))

    def test_full11_new_metadata_preserves_all_original_parquet_cells(self):
        fixture = self.uploaded()
        before = fixture['binding'].encoded, deepcopy(fixture['source_metadata']), dict(fixture['objects'])
        self.verify_target(fixture, self.target(fixture))
        self.assertEqual((fixture['binding'].encoded, fixture['source_metadata'], fixture['objects']), before)

    def test_dual130_new_metadata_preserves_all_original_parquet_cells(self):
        fixture = self.uploaded(True)
        self.verify_target(fixture, self.target(fixture))

    def test_preflight_rejects_physical_schema_and_missing_uploaded_version_without_put(self):
        fixture = self.uploaded()
        before = len(self.client.puts)
        fixture['source_metadata'][1]['source_schema'][0]['source_field_id'] = 999
        with self.assertRaises(ContractFailure):
            self.target(fixture)
        self.assertEqual(len(self.client.puts), before)
        self.assertFalse((self.root / 'new').exists())

    def test_old_dataset_and_fake_sealed_version_are_rejected(self):
        fixture = self.uploaded()
        old = fixture['binding'].value['resource']
        with self.assertRaises(ContractFailure):
            sql_target_from_uploaded(fixture, self.client, self.root / 'new', old['dataset_id'], 'fresh-schema',
                                     protected_until_unix_ms=10000)
        metadata = fixture['source_metadata'][0]
        ref = metadata['files'][0]['object']
        raw = fixture['objects'].pop(encoded(ref))
        ref['version'] = 'sealed-v1'
        fixture['objects'][encoded(ref)] = raw
        with self.assertRaises(ContractFailure):
            self.target(fixture)

    def test_failure_journal_does_not_mask_original_sdk_failure(self):
        fixture = self.uploaded()
        primary = OSError('unit SDK failure')
        with patch.object(self.client, 'put_object', side_effect=primary), \
                patch('tests.source_support.fixed_fd_fixture.save', side_effect=OSError('journal failed')):
            with self.assertRaises(OSError) as caught:
                self.target(fixture)
        self.assertIs(caught.exception, primary)

    def test_new_metadata_requires_two_distinct_versions_and_success_journal(self):
        fixture = self.uploaded()
        with patch.object(self.client, 'put_object', return_value={'VersionId': 'same-version'}):
            with self.assertRaises(ContractFailure):
                self.target(fixture, 'bad-version')
        # A complete target with missing durability evidence is also a failure.
        from tests.source_support import fixed_fd_fixture as factory
        original = factory.save

        def save(path, raw):
            if path.name == 'new-metadata-progress.json':
                raise OSError('unit journal failure')
            original(path, raw)

        with patch.object(factory, 'save', side_effect=save):
            with self.assertRaises(OSError):
                self.target(fixture, 'bad-journal')

    def test_prepare_target_actual_sqlite_register_publish_uses_final_digest(self):
        fixture = self.uploaded()
        result = self.target(fixture)
        local = catalog_fixture.ControlledReadTests()
        local.setUp()
        self.addCleanup(local.doCleanups)
        initial = result['target'].sha256
        final = prepare_target(local.catalog, local.authority, local.principal, result['target'], 'fd-published')
        self.assertNotEqual(initial, final.sha256)
        self.assertEqual(final.value['resource']['dataset_id'], 'fd-published')
        local.authority.verify(final, local.wall['ms'], local.wall['ms'] + 1000)
        self.assertEqual(final.value['revision']['content_sha256'], digest({
            key: value for key, value in final.value['revision'].items() if key != 'content_sha256'}))
        # Query through existing C1, not fabricated binding/context.
        from tests.catalog_support.fixed_fixture import request
        issued = local.reader().bind(request(local.principal, query='fd-target', dataset='fd-published'))
        self.assertEqual(issued.value['resource'], final.value['resource'])
        self.assertEqual(issued.value['revision'], final.value['revision'])


if __name__ == '__main__':
    unittest.main()
