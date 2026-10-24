"""Coverage gates reject rounded totals, missing files and failing tests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
import unit_coverage as gate
from harnesslib.policy import load, plan


class CoverageGateTests(unittest.TestCase):
    def test_language_thresholds_use_valid_exact_counters(self):
        for language, covered, total, expected in (
                ('python', 79, 100, False), ('python', 80, 100, True),
                ('python', 81, 100, True), ('rust', 99, 100, False),
                ('rust', 100, 100, True), ('python', 79999999, 100000000, False)):
            with self.subTest(language=language, covered=covered):
                self.assertEqual(gate.meets_threshold(language, covered, total), expected)
        for covered, total in ((0, 0), (1, 0), (-1, 100), (101, 100),
                               (True, 100), (80, True), (80.0, 100), (80, -1)):
            for language in ('python', 'rust'):
                with self.subTest(language=language, covered=covered, total=total):
                    self.assertFalse(gate.meets_threshold(language, covered, total))

    def test_same_checkout_cannot_merge_concurrent_profile_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with gate.exclusive_run(root):
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    with gate.exclusive_run(root):
                        self.fail('second run acquired the same profile directory')
            with gate.exclusive_run(root):
                pass  # Closed descriptors release the lock, including failed runs.

    def test_python_includes_never_imported_files_and_requires_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('modules/common/a.py', 'clients/cli/b.py'):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('value = 1\n')
            output = root/'report'
            output.mkdir()
            catalog = {'modules/common/a.py': 'fixture', 'clients/cli/b.py': 'fixture'}
            cov = Mock()
            runner = Mock()
            runner.run.return_value.wasSuccessful.return_value = True
            for files, missing, passed in [({'modules/common/a.py': {}, 'clients/cli/b.py': {}}, 0, True),
                    ({'modules/common/a.py': {}}, 0, False),
                    ({'modules/common/a.py': {}, 'clients/cli/b.py': {}}, 1, True),
                    ({'modules/common/a.py': {}, 'clients/cli/b.py': {}}, 21, False)]:
                payload = {'files': files, 'totals': {'missing_lines': missing, 'excluded_lines': 0, 'percent_covered': 100.0, 'num_statements': 100, 'covered_lines': 100-missing}}
                cov.json_report.side_effect = lambda **kwargs: Path(kwargs['outfile']).write_text(json.dumps(payload))
                with patch.object(gate, 'ROOT', root), patch.object(gate, 'production_sources', return_value=catalog), patch('coverage.Coverage', return_value=cov), patch.object(gate.unittest, 'TestLoader') as loader, patch.object(gate.unittest, 'TextTestRunner', return_value=runner):
                    loader.return_value.discover.return_value = unittest.TestSuite()
                    self.assertEqual(gate.python_coverage(output), passed)
                self.assertEqual(set(cov.get_data.return_value.touch_files.call_args.args[0]),
                                 {str(root/'modules/common/a.py'), str(root/'clients/cli/b.py')})
            runner.run.return_value.wasSuccessful.return_value = False
            with patch.object(gate, 'ROOT', root), patch.object(gate, 'production_sources', return_value=catalog), patch('coverage.Coverage', return_value=cov), patch.object(gate.unittest, 'TestLoader') as loader, patch.object(gate.unittest, 'TextTestRunner', return_value=runner):
                loader.return_value.discover.return_value = unittest.TestSuite()
                self.assertFalse(gate.python_coverage(output))

    def test_rust_requires_matching_inventories_and_zero_eligible_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'crates/core/src/lib.rs'
            source.parent.mkdir(parents=True)
            source.write_text('fn function() {}\n')
            output = root/'report'
            output.mkdir()
            name = 'crates/core/src/lib.rs'
            catalog = {'crates/core/src/lib.rs': 'fixture'}
            (output/'rust.json').write_text(json.dumps({'data': [{'files': [
                {'filename': '/workspace/'+name, 'summary': {'lines': {'count': 100000000, 'covered': 99999999, 'percent': 100.0}}}]}]}))
            for missing, passed in [(1, False), (0, True)]:
                summary = {'metric': 'lcov-unique-source-lines', 'totals': {'missing_lines': missing, 'eligible_lines': 100000000,
                                                                       'eligible_covered': 100000000-missing}}
                with patch.object(gate, 'ROOT', root), patch.object(gate, 'production_sources', return_value=catalog), patch.object(gate.subprocess, 'run'), patch.object(gate, 'read_lcov', return_value={name: {1: 0}}), patch.object(gate, 'summarize', return_value=summary), patch('builtins.print'):
                    self.assertEqual(gate.rust_coverage(output), passed)
            (output/'rust.json').write_text(json.dumps({'data': [{'files': []}]}))
            with patch.object(gate, 'ROOT', root), patch.object(gate, 'production_sources', return_value=catalog), patch.object(gate.subprocess, 'run'), patch.object(gate, 'read_lcov', return_value={name: {1: 1}}):
                with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                    gate.rust_coverage(output)

    def test_actual_policy_selects_coverage_for_source_tests_and_config(self):
        config = load(ROOT)
        for path in ['crates/guradb-query/src/sql.rs', 'tests/unit/test_sample.py', '.coveragerc', 'scripts/unit_coverage.py', 'scripts/coverage_policy.py', 'harness/coverage-exclusions.json', 'requirements-dev.lock']:
            with self.subTest(path=path):
                self.assertIn('unit-coverage', plan(ROOT, [path], *config[:3])['required_suites'])
        self.assertIn('unit-coverage', config[0]['release_suites'])
        self.assertNotIn('unit-coverage', plan(ROOT, ['README.md'], *config[:3])['required_suites'])
