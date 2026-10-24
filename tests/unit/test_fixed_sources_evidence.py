"""Synthetic driver lifecycle negatives; no S3/source/latency claims."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import fixed_sources_acceptance as driver


class SourceDriverEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root/'artifacts/run'
        self.calls, self.log_rc, self.cleanup_error = [], 0, False
        self.body = lambda *_: {'passed': True}
        self.lab = None
        for patcher in (patch.object(driver, 'ROOT', self.root),
                        patch.object(driver, 'identity', return_value={'code': 'unit-fixed'}),
                        patch.object(driver, 'runtime_components', side_effect=self.runtime),
                        patch('sys.argv', ['fixed_sources_acceptance', '--mode', 'functional',
                                           '--run-dir', str(self.output)])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def runtime(self):
        @contextmanager
        def laboratory(directory):
            self.calls.append('entered')
            self.lab = SimpleNamespace(directory=directory, names=['unit-owned'], removed=set(),
                                       network='unit-network', trace=[])
            try:
                yield self.lab
            finally:
                self.calls.append('cleanup-attempted')
                if self.cleanup_error:
                    raise RuntimeError('SECRET-UNIT-CLEANUP must not enter report')
                self.lab.removed.add('unit-owned')
                self.lab.trace.append({'action': 'container_logs_collected', 'returncode': self.log_rc})
        class Logs:
            def __enter__(self):
                return self

            def audit(self):
                return {'unit_only_logging': True}

            def __exit__(self, *arguments):
                pass
        return ('unit-image', lambda *args, **kw: SimpleNamespace(returncode=0, stdout=''),
                laboratory, lambda *args: self.body(*args), lambda _: {}, Logs)

    def failure(self):
        result = json.loads((self.output/'failure.json').read_text())
        self.assertIs(result['passed'], False)
        self.assertNotIn('SECRET-UNIT', json.dumps(result))
        return result

    def test_runtime_import_and_secondary_identity_failure_preserve_both_errors(self):
        with patch.object(driver, 'runtime_components', side_effect=ImportError('SECRET-UNIT-IMPORT')), \
                patch.object(driver, 'identity', side_effect=[{'code': 'unit-fixed'}, OSError('SECRET-UNIT-IDENTITY')]):
            self.assertEqual(driver.main(), 1)
        report = self.failure()
        self.assertEqual(report['primary_error']['error_class'], 'ImportError')
        self.assertEqual(report['identity_error']['error_class'], 'OSError')
        self.assertEqual(self.calls, [])
        self.assertIs(report['lifecycle']['initialized'], False)

    def test_failed_component_still_records_owned_cleanup_and_private_lab(self):
        def failed(*arguments):
            raise AssertionError('SECRET-UNIT-BODY')
        self.body = failed
        self.assertEqual(driver.main(), 1)
        report = self.failure()
        self.assertEqual(self.calls, ['entered', 'cleanup-attempted'])
        self.assertEqual(report['primary_error']['error_class'], 'AssertionError')
        self.assertIs(report['lifecycle']['cleanup_confirmed'], True)
        self.assertEqual(report['lifecycle']['owned_containers'], 1)
        self.assertTrue(Path(report['lifecycle']['private_lab']).is_relative_to(self.root/'artifacts/private'))

    def test_cleanup_failure_keeps_original_component_cause_and_incomplete_counts(self):
        def failed(*arguments):
            raise AssertionError('SECRET-UNIT-BODY')
        self.body, self.cleanup_error = failed, True
        self.assertEqual(driver.main(), 1)
        report = self.failure()
        self.assertEqual(report['primary_error']['error_class'], 'RuntimeError')
        self.assertEqual(report['earliest_error']['error_class'], 'AssertionError')
        self.assertIs(report['lifecycle']['cleanup_confirmed'], False)
        self.assertEqual(report['lifecycle']['removed_containers'], 0)

    def test_nonzero_service_log_extraction_cannot_pass_after_remove(self):
        self.log_rc = 42
        self.assertEqual(driver.main(), 1)
        report = self.failure()
        self.assertEqual(report['code'], 'service_cleanup_not_confirmed')
        self.assertEqual(report['lifecycle']['log_returncodes'], [42])
        self.assertEqual(report['lifecycle']['removed_containers'], 1)

    def test_case_artifact_write_failure_still_exits_owned_laboratory(self):
        def failed(*arguments):
            raise OSError('SECRET-UNIT-ARTIFACT')
        self.body = failed
        self.assertEqual(driver.main(), 1)
        report = self.failure()
        self.assertEqual(report['primary_error']['error_class'], 'OSError')
        self.assertEqual(self.calls, ['entered', 'cleanup-attempted'])
        self.assertIs(report['lifecycle']['cleanup_confirmed'], True)

    def test_cost_assertion_failure_retains_actual_binding_and_returned_page(self):
        from modules.connectors.fixed_source_reader import FixedSourceReader
        from tests.source_support.fixed_acceptance import measured, save_case_input
        from tests.source_support.fixed_fixture import make_fixture, unit_objects
        fixture = make_fixture(self.root/'source')
        objects, fetched, _ = unit_objects(fixture)
        reader = FixedSourceReader(objects)
        original = reader.port.read_batch
        def corrupt_after_return(*arguments):
            result = original(*arguments)
            objects.scope.output_bytes += 1  # Explicitly falsify the observed test ledger.
            return result
        reader.port = SimpleNamespace(read_batch=corrupt_after_return)
        directory = self.root/'journal'
        save_case_input(reader, fixture, directory)
        with patch('modules.storage.fixed_objects.fetch', side_effect=fetched):
            with self.assertRaises(AssertionError):
                measured(reader, 0)
        self.assertEqual((directory/'binding.json').read_bytes(), fixture['binding'].encoded)
        journal = json.loads((directory/'pages-journal.json').read_text())
        self.assertEqual(len(journal), 1)
        self.assertIs(journal[0]['returned_envelope'], True)
        self.assertEqual(journal[0]['context_sha256'], fixture['binding'].sha256)
        self.assertEqual(journal[0]['primary_error']['error_class'], 'AssertionError')
        self.assertEqual(len(journal[0]['sample']['rows']), 11)
        self.assertTrue((directory/'call-0.json').is_file())
