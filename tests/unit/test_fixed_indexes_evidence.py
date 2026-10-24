"""Driver evidence lifecycle faults, without launching children or measurements."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('fixed_indexes_acceptance', ROOT / 'scripts/fixed_indexes_acceptance.py')
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


class EvidenceLifecycle(unittest.TestCase):
    def setUp(self):
        (ROOT / 'artifacts').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'artifacts')
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'run'
        self.source = {'head': 'a'*40, 'checkout_sha256': 'b'*64, 'files': {'source.py': 'c'*64}}

    def test_new_output_and_full_evidence_links_without_self_digest(self):
        with patch.object(DRIVER, 'source_manifest', return_value=self.source), \
                patch.object(DRIVER, 'environment', return_value={'fixture': True}), \
                patch.object(DRIVER, 'functional', return_value={'status': 'pass'}) as functional:
            result = DRIVER.run(self.output, 'functional')
            self.assertEqual(result['git_head'], self.source['head'])
            self.assertTrue(result['unchanged_source'])
            self.assertEqual(functional.call_args.args[2], self.source)
            manifest = json.loads((self.output / 'evidence-manifest.json').read_text())
            self.assertNotIn('evidence-manifest.json', manifest['files'])
            self.assertNotIn('report.json', manifest['files'])
            self.assertIn('source-before.json', manifest['files'])
            self.assertIn('environment.json', manifest['files'])
            with self.assertRaises(FileExistsError): DRIVER.run(self.output, 'functional')

    def test_changed_source_or_processing_failure_always_retains_failed_report(self):
        after = {**self.source, 'checkout_sha256': 'd'*64}
        with patch.object(DRIVER, 'source_manifest', side_effect=[self.source, after]), \
                patch.object(DRIVER, 'environment', return_value={}), \
                patch.object(DRIVER, 'functional', return_value={'status': 'pass'}):
            with self.assertRaises(RuntimeError): DRIVER.run(self.output, 'functional')
        result = json.loads((self.output / 'report.json').read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['unchanged_source'])
        output = Path(self.temp.name) / 'fault'
        with patch.object(DRIVER, 'source_manifest', return_value=self.source), \
                patch.object(DRIVER, 'environment', return_value={}), \
                patch.object(DRIVER, 'functional', side_effect=ValueError('injected processing failure')):
            with self.assertRaises(RuntimeError): DRIVER.run(output, 'functional')
        self.assertIn('injected processing failure', (output / 'failure.log').read_text())
        self.assertEqual(json.loads((output / 'report.json').read_text())['status'], 'failed')

    def test_initial_snapshot_failure_also_keeps_a_report(self):
        with patch.object(DRIVER, 'source_manifest', side_effect=[OSError('initial snapshot failure'), self.source]):
            with self.assertRaises(RuntimeError): DRIVER.run(self.output, 'functional')
        self.assertTrue((self.output / 'failure.log').is_file())
        self.assertEqual(json.loads((self.output / 'report.json').read_text())['status'], 'failed')
