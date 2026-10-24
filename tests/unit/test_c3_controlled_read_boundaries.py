"""Failure/ownership unit checks; fake libpq does not prove remote PG stop."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from psycopg import pq

from modules.catalog import cf1a_pg
from modules.catalog.cf1a_control import CatalogReadControl
from modules.common.cf1a_primitives import ContractFailure, canonical
from modules.connectors import fixed_source_located as located
from modules.connectors.fixed_source_reader import FixedSourceReader
from modules.storage.fixed_parent import ReadParent
from tests.source_support.fixed_fixture import make_multisource_fixture, unit_objects
from tests.storage_support.fixtures import binding, object_ref


class ControlledBoundaryTests(unittest.TestCase):
    def refuse(self, code, callback):
        with self.assertRaises(ContractFailure) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def control(self):
        return CatalogReadControl(lambda: 10, lambda: 0)

    def test_invalid_clock_keeps_contract_failure_without_catalog_work(self):
        control = CatalogReadControl(lambda: 10, lambda: float('nan'))
        self.refuse('invalid_contract', control.now)
        self.assertEqual(control.invoice['counts'], {})

    def test_parent_callback_unavailable_consumes_admission_without_object_execution(self):
        issued = binding(object_ref())
        def unavailable():
            raise OSError('private callback detail')
        parent = ReadParent(1000, issued.value['context']['budget'], unavailable)
        from modules.storage.fixed_scope import ReadScope
        self.refuse('cancelled', lambda: ReadScope(issued, parent=parent))
        self.assertEqual(parent.invoice['admission'], 'rejected_before_object_execution')
        self.assertIsNone(parent.invoice['execution'])
        self.refuse('expired_context', lambda: ReadScope(issued, parent=parent))

    def test_inherited_native_close_is_counted_once_even_when_repeated(self):
        control = self.control()
        pgconn = Mock(status=pq.ConnStatus.OK)
        pgconn.finish.side_effect = lambda: setattr(pgconn, 'status', pq.ConnStatus.BAD)
        connection = cf1a_pg.DeadlineConnection(pgconn, 10, control)
        self.assertFalse(connection.closed)
        connection.close()
        connection.close()
        self.assertTrue(connection.closed)
        pgconn.finish.assert_called_once()
        self.assertEqual(control.invoice['counts'], {'closed': 1})

    def test_successful_wait_tail_marks_success_and_preserves_return_value(self):
        control = self.control()
        pgconn = Mock(status=pq.ConnStatus.OK)
        pgconn.finish.side_effect = lambda: setattr(pgconn, 'status', pq.ConnStatus.BAD)
        connection = cf1a_pg.DeadlineConnection(pgconn, 10, control)
        def complete():
            if False:
                yield
            return ('immutable-row',)
        with patch.object(cf1a_pg.time, 'monotonic', return_value=0):
            self.assertEqual(connection.wait(complete()), ('immutable-row',))
        self.assertFalse(connection.closed)
        self.assertEqual(control.invoice['counts'], {'sql_attempt': 1, 'sql_success': 1})
        connection.close()
        self.assertEqual(control.invoice['counts']['closed'], 1)

    def test_successful_poll_returns_same_operation_control_without_new_budget(self):
        control = self.control()
        pgconn = Mock()
        pgconn.connect_poll.return_value = pq.PollingStatus.OK
        stub = SimpleNamespace(PGconn=Mock(connect_start=Mock(return_value=pgconn)),
                               PollingStatus=pq.PollingStatus)
        result = object()
        with patch.object(cf1a_pg, 'pq', stub), patch.object(cf1a_pg, 'DeadlineConnection', return_value=result) as made:
            self.assertIs(cf1a_pg.connect('unit-no-socket', 7, control), result)
        made.assert_called_once_with(pgconn, 7, control)
        self.assertEqual(pgconn.nonblocking, 1)
        self.assertEqual(control.invoice['counts'], {'connect_attempt': 1, 'connect_success': 1})
        pgconn.finish.assert_not_called()

    def fixture_page(self, directory):
        fixture = make_multisource_fixture(directory)
        objects, fetched, _ = unit_objects(fixture)
        reader = FixedSourceReader(objects)
        with patch('modules.storage.fixed_objects.fetch', side_effect=fetched):
            page = reader.read_located_batch(fixture['binding'], 0)
        return fixture, objects.scope, page

    def test_nonfinite_provenance_rejected_without_recharging_original_output(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, scope, page = self.fixture_page(Path(directory))
            before = scope.usage()
            for constant in (b'NaN', b'Infinity', b'-Infinity'):
                changed = located.LocatedBatch(page.batch, b'{"unsupported":' + constant + b'}')
                self.refuse('invalid_contract', lambda: located.validate_located_for(fixture['binding'], changed))
            self.assertEqual(scope.usage()['output_bytes'], before['output_bytes'])
            self.assertEqual(scope.usage()['object_requests'], before['object_requests'])

    def test_unstable_located_encoder_stops_after_bounded_attempts_without_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, scope, page = self.fixture_page(Path(directory))
            body = deepcopy(page.batch.value)
            positions = {identifier: {key: rows[0][key] for key in
                ('source_version_id', 'object', 'row_group', 'row_offset')}
                for identifier, rows in fixture['locations'].items()}
            bounds = {(metadata['source_version_id'], canonical(entry['object'])): tuple(entry['row_group_rows'])
                for metadata in fixture['source_metadata'] for entry in metadata['files']}
            calls, before = [], scope.usage()
            def unstable(value):
                calls.append(True)
                return canonical(value) + b' ' * len(calls)
            with patch.object(located, 'canonical', side_effect=unstable):
                error = self.refuse('resource_limit', lambda: located.encode_located(
                    fixture['binding'], body, positions, bounds, scope, 768 << 10))
            self.assertIn('converge', str(error))
            self.assertEqual(len(calls), 64)
            self.assertEqual(scope.usage()['output_bytes'], before['output_bytes'])
            self.assertEqual(scope.usage()['object_requests'], before['object_requests'])


if __name__ == '__main__':
    unittest.main()
