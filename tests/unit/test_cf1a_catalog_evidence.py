"""Driver identity/artifact/cleanup negatives; these mocks prove no PG semantics."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import fixed_catalog_acceptance as driver


class DriverEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root/'artifacts/run'
        (self.root/'.gitignore').write_text('artifacts/\n')
        self.watched = self.root/'watched.py'
        self.watched.write_text('original fixture source\n')
        def git(*arguments):
            subprocess.run(['git', *arguments], cwd=self.root, check=True, capture_output=True)
        git('init', '-q', '-b', 'main')
        git('add', '.gitignore', 'watched.py')
        git('-c', 'user.name=Harness Test', '-c', 'user.email=harness@example.invalid',
            'commit', '-qm', 'independent evidence fixture')
        self.calls = []
        self.logs_returncode = 0
        self.restarted = False
        self.restart_port = 12345
        for patcher in (patch.object(driver, 'ROOT', self.root),
                        patch.object(driver, 'docker', side_effect=self.docker),
                        patch.object(driver, 'choose_loopback_port', return_value=12345)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def docker(self, *arguments, **kwargs):
        self.calls.append(arguments)
        stdout, code = '', 0
        if arguments[0] == 'port':
            port = self.restart_port if self.restarted else 12345
            stdout = f'127.0.0.1:{port}\n'
        elif arguments[0] == 'restart':
            self.restarted = True
        elif arguments[0] == 'inspect':
            stdout = '"sha256:unit-only-image"\n'
        elif arguments[0] == 'logs':
            code = self.logs_returncode
            stdout = 'unit-only service log\n' if code == 0 else ''
        return SimpleNamespace(returncode=code, stdout=stdout,
                               stderr='unit-only extraction failure\n' if code else '')

    @staticmethod
    def runtime():
        binding = SimpleNamespace(encoded=b'fixed-unit-binding', sha256='unit-binding', document={'unit': True})
        port = SimpleNamespace(bind=lambda request: binding, release_pin=lambda value: None)
        catalog = SimpleNamespace(initialize=lambda: None, port=lambda principal: port)
        psycopg = SimpleNamespace(connect=lambda *args, **kwargs: nullcontext(), Error=Exception)
        store = SimpleNamespace(connect=lambda *args: None)
        class Cases:
            def __init__(self, *args):
                self.trace, self.inputs, self.now = [], [{'unit': 'synthetic lifecycle input'}], 1000

            def functional(self):
                pass

            def race_and_fence(self):
                pass

            def capacity(self):
                self.event('unit-only-original-operation-capacity')

            def byte_capacity(self):
                self.event('unit-only-original-byte-capacity')

            def audit_metadata(self):
                pass

            def event(self, name, **fields):
                self.trace.append({'scenario': name, **fields})

            def sql(self, *args):
                return []

            def dump(self, output):
                return []
        return (psycopg, store, lambda dsn: (catalog, object(), object(), 1000),
                lambda *args, **kwargs: object(), Cases, None, None)

    def report(self):
        return json.loads((self.output/'report.json').read_text())

    def assert_owned_remove_attempted(self):
        started = next(arguments[3] for arguments in self.calls if arguments[0] == 'run')
        removed = [arguments[-1] for arguments in self.calls if arguments[0] == 'rm']
        self.assertEqual(removed, [started])

    def test_import_failure_after_source_change_retains_distinct_identities(self):
        original = hashlib.sha256(self.watched.read_bytes()).hexdigest()
        def import_failure():
            before = json.loads((self.output/'source-before.json').read_text())
            self.assertEqual(before['files']['watched.py'], original)
            self.watched.write_text('changed while importing fixture\n')
            raise ImportError('unit-only import failure')
        with patch.object(driver, 'runtime_components', side_effect=import_failure):
            with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                driver.run(self.output, 'functional')
        report = self.report()
        self.assertEqual(report['status'], 'failed')
        self.assertIs(report['unchanged_source'], False)
        after = json.loads((self.output/'source-after.json').read_text())
        self.assertEqual(after['files']['watched.py'], hashlib.sha256(self.watched.read_bytes()).hexdigest())
        self.assertNotEqual(after['files']['watched.py'], original)
        self.assertIn('ImportError', (self.output/'failure.log').read_text())
        self.assertEqual(self.calls, [])

    def test_nonzero_log_extraction_cannot_pass_after_successful_remove(self):
        self.logs_returncode = 42
        with patch.object(driver, 'runtime_components', side_effect=self.runtime):
            with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                driver.run(self.output, 'functional')
        report = self.report()
        self.assertEqual(report['status'], 'failed')
        self.assertIs(report['unchanged_source'], True)
        self.assertEqual(report['service_logs_returncode'], 42)
        self.assertEqual(report['service_cleanup_returncode'], 0)
        self.assertIn({'action': 'logs', 'returncode': 42}, report['cleanup_errors'])
        self.assertFalse((self.output/'postgres.log').exists())
        self.assertTrue((self.output/'postgres-log-extraction-error.log').is_file())
        self.assert_owned_remove_attempted()

    def test_input_artifact_write_failure_still_cleans_owned_service(self):
        original_write = driver.write
        def failed_inputs(path, value):
            if path.name == 'actual-inputs.json':
                raise OSError('unit-only artifact write failure')
            original_write(path, value)
        with patch.object(driver, 'runtime_components', side_effect=self.runtime), \
                patch.object(driver, 'write', side_effect=failed_inputs):
            with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                driver.run(self.output, 'functional')
        report = self.report()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['service_cleanup_returncode'], 0)
        self.assertIn({'stage': 'actual-inputs', 'error_type': 'OSError'}, report['evidence_errors'])
        self.assertTrue((self.output/'source-after.json').is_file())
        self.assertTrue((self.output/'postgres.log').is_file())
        self.assert_owned_remove_attempted()

    def test_changed_restart_endpoint_cannot_claim_persisted_binding(self):
        self.restart_port = 12346
        with patch.object(driver, 'runtime_components', side_effect=self.runtime):
            with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                driver.run(self.output, 'functional')
        report = self.report()
        self.assertEqual(report['status'], 'failed')
        self.assertIs(report['unchanged_source'], True)
        self.assertEqual(report['published_ports'],
                         {'requested': 12345, 'before_restart': 12345, 'after_restart': 12346})
        self.assertIn('endpoint changed after restart', (self.output/'failure.log').read_text())
        self.assert_owned_remove_attempted()

    def test_performance_quota_failure_preserves_original_work_and_cleans_service(self):
        def quota_failure(cases):
            self.assertEqual([row['scenario'] for row in cases.trace],
                             ['unit-only-original-operation-capacity', 'unit-only-original-byte-capacity'])
            raise AssertionError('unit-only new quota boundary failure')
        with patch.object(driver, 'runtime_components', side_effect=self.runtime), \
                patch('tests.catalog_support.pg_quota_cases.remaining_capacities', side_effect=quota_failure):
            with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                driver.run(self.output, 'performance')
        report = self.report()
        self.assertEqual(report['status'], 'failed')
        self.assertIs(report['unchanged_source'], True)
        self.assertIn('new quota boundary failure', (self.output/'failure.log').read_text())
        self.assertEqual(report['service_cleanup_returncode'], 0)
        self.assert_owned_remove_attempted()
