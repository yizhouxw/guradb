"""Composition fixture unit checks with SQLite and in-memory object bytes only."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tests.unit import test_cf1a_catalog_controlled as catalog_fixture
from tests.source_support.fixed_catalog_pair import PairQuery, positive, prepare
from modules.common.cf1a_primitives import ContractFailure
from tests.source_support.fixed_fixture import encoded, make_multisource_fixture


class PairFixtureTests(unittest.TestCase):
    def setUp(self):
        self.case = catalog_fixture.ControlledReadTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_full11_real_parquet_sql_issued_bytes_and_independent_locations(self):
        fixture = make_multisource_fixture(self.directory/'inputs')
        self.assertEqual([len({row['record_id'] for row in fixture['rows']
            if row['source_id'] == source}) for source in ('source-main', 'source-mirror')], [10, 1])
        self.verify_fixture(fixture, (11,))

    def test_dual130_three_pages_with_independent_locations(self):
        from tests.source_support.fixed_backend_cases import many_rows
        rows = many_rows()
        for i, row in enumerate(rows):
            row['source_id'] = 'source-main' if i < 65 else 'source-mirror'
        fixture = make_multisource_fixture(self.directory/'inputs', source_rows=[
            ('source-main', 'p04-main-v2', rows[:65]), ('source-mirror', 'p04-mirror-v2', rows[65:])],
            writer_options={'row_group_size': 16})
        self.verify_fixture(fixture, (64, 64, 2))

    def test_ordinary_observer_keeps_prebind_t0(self):
        fixture = make_multisource_fixture(self.directory/'inputs')
        self.verify_fixture(fixture, (11,), located=False, prebind=.02)

    def test_pg_revoke_removed_grant_rejects_next_page_as_unauthorized(self):
        fixture = make_multisource_fixture(self.directory/'inputs')
        catalog, authority, principal = self.case.catalog, self.case.authority, self.case.principal
        prepare(catalog, authority, principal, fixture, 'pair-unit')
        query = PairQuery(catalog, principal, fixture, 'pair-unit', 'http://127.0.0.1:1',
                          self.directory/'query')
        reader = query.bind()
        def fetched(scope, backend, ref, offset, length):
            scope.request(length)
            raw = fixture['objects'][encoded(ref)][offset:offset + length]
            scope.received(len(raw))
            return raw
        with patch('modules.storage.fixed_objects.fetch', side_effect=fetched):
            reader.port.read_batch(query.binding, 0)
        before = reader.scope.usage()
        catalog.revoke(principal, 'pair-unit-revoke', 'pair-unit', principal.subject_id, principal.delegation_ref)
        with self.assertRaises(ContractFailure) as caught:
            reader.port.read_batch(query.binding, 0)
        self.assertEqual(caught.exception.code, 'unauthorized')
        after = reader.scope.usage()
        self.assertEqual(after['object_requests'], before['object_requests'])
        self.assertEqual(after['output_bytes'], before['output_bytes'])

    def verify_fixture(self, fixture, expected_sizes, *, located=True, prebind=0):
        catalog, authority, principal = self.case.catalog, self.case.authority, self.case.principal
        prepare(catalog, authority, principal, fixture, 'pair-unit')
        query = PairQuery(catalog, principal, fixture, 'pair-unit', 'http://127.0.0.1:1',
                          self.directory/'query')
        time.sleep(prebind)
        def fetched(scope, backend, ref, offset, length):
            scope.request(length)
            raw = fixture['objects'][encoded(ref)][offset:offset + length]
            scope.received(len(raw))
            return raw
        with patch('modules.storage.fixed_objects.fetch', side_effect=fetched):
            result = positive(query, located=located, expected_sizes=expected_sizes)
        self.assertEqual([len(page['rows']) for page in result['pages']], list(expected_sizes))
        self.assertTrue(result['terminal_ordinal_rejected'])
        self.assertEqual(query.reader.scope.started, query.parent.started)
        self.assertGreaterEqual(query.parent.invoice['elapsed_ms'], int(prebind * 1000))
        row = self.case.query('SELECT binding,binding_sha256 FROM gura_cf1a.queries WHERE query_id=%s',
                              (query.request.value['query_id'],))[0]
        self.assertEqual(bytes(row['binding']), query.binding.encoded)
        self.assertEqual(row['binding_sha256'], query.binding.sha256)
        def independent(dsn, dataset, identifier):
            row = self.case.query('SELECT binding_sha256,released,pin_id,lease_id FROM gura_cf1a.queries '
                'WHERE dataset=%s AND query_id=%s', (dataset, identifier))[0]
            return tuple(row[key] for key in ('binding_sha256', 'released', 'pin_id', 'lease_id'))
        with patch('tests.source_support.fixed_catalog_pair.query_row', side_effect=independent):
            self.assertEqual(query.finish(), {'state': 'released', 'exact_pin_confirmed': True})


if __name__ == '__main__':
    unittest.main()
