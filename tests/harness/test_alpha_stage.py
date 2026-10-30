"""Real Git/process receipts with toy commands, separate from Rust CLI truth."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from harnesslib.policy import HarnessError, load
from harnesslib.runner import check, checkout_digest
from harnesslib.check_evidence import validate_report
from harnesslib.stages import retirement
from harnesslib.validation_binding import LOGIC_INPUTS, bound_plan
from harnesslib.workflow import finish_task, start_task
from harnesslib.version_control import install_hooks, checkpoint
from harnesslib.validation_registry import source_inventory


class AlphaStageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        environment = patch.dict(os.environ, {'PATH': os.environ['PATH']}, clear=True)
        environment.start(); self.addCleanup(environment.stop)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Alpha tool fixture')
        self.git('config', 'user.email', 'tool@example.invalid')
        for name in LOGIC_INPUTS:
            self.copy(name)
        for pattern in ('scripts/harnesslib/*.py', 'harness/*.toml'):
            for path in ROOT.glob(pattern):
                self.copy(path.relative_to(ROOT).as_posix())
        for name in ('Cargo.toml', 'crates/guradb/Cargo.toml', 'harness/alpha-retired.json'):
            self.copy(name)
        self.write('crates/guradb/src/main.rs', 'fn main() {}\n')
        self.write('tests/harness/test_alpha_stage.py', 'import unittest\nclass Fixture(unittest.TestCase):\n def test_fixture(self): pass\n')
        self.write('scripts/alpha_acceptance.py', "print('toy driver; no product claim')\n")
        self.write('scripts/check_repository.py', "print('toy repository')\n")
        self.write('scripts/cargo.py', "print('toy Rust command; no compiler claim')\n")
        self.write('.gitignore', 'artifacts/\n__pycache__/\n')
        self.write('README.md', '# Tool fixture\n')
        policy = self.root/'harness/policy.toml'
        lines = []
        for line in policy.read_text().splitlines():
            if line.startswith('commands = [['):
                line = 'commands = '+json.dumps([['{python}', '-c', "print('toy command; not a database test')"]])
            lines.append(line)
        policy.write_text('\n'.join(lines)+'\n')
        (self.root/'.githooks/pre-commit').chmod(0o755)
        self.git('add', '.')
        self.git('commit', '-m', 'tool baseline')
        self.config = load(self.root)
        self.started = start_task(self.root, 'alpha-fixture', 'tool protocol only', self.config, 'core', 'simple-alpha')
        self.write('crates/guradb/src/main.rs', 'fn main() { let _ = 1; }\n')
        self.git('add', '.')
        self.git('commit', '-m', 'tool change')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL).decode().strip()

    def write(self, name, text):
        path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)

    def copy(self, name):
        target = self.root/name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT/name, target)

    def report(self):
        report, path = check(self.root, 'change', 'auto', self.config, 'auto')
        self.assertTrue(report['passed'], report['results'])
        return report, path

    def test_normal_hook_and_post_commit_finish_preserve_bounded_claim(self):
        install_hooks(self.root)
        self.write('crates/guradb/src/main.rs', 'fn main() { let _ = 2; }\n')
        self.git('add', '.')
        self.git('commit', '-m', 'normal hooked tool change')
        report, path = self.report()
        self.assertEqual(validate_report(self.root, path, self.config), report)
        done = finish_task(self.root, path, 'tool commands only, no product claim', self.config)
        self.assertEqual(done['base_commit'], self.started['base_commit'])
        self.assertEqual(done['validation']['core_flow'], 'simple-alpha')
        self.assertEqual(done['validation']['level'], 'core-limited')

    def test_core_profile_keeps_real_rust_and_driver_and_retirement(self):
        profile = bound_plan(ROOT, ['crates/guradb/src/main.rs'], *load(ROOT)[:3],
                             stage='core', core_flow='simple-alpha')['profile']
        self.assertEqual(list(profile['suites']), ['repository', 'policy', 'harness-tests', 'python', 'rust', 'functional'])
        self.assertEqual(len(profile['suites']['rust']['commands']), 3)
        self.assertIn('scripts/alpha_acceptance.py', profile['command_inputs'])
        self.assertEqual(set(profile['source_closure']), {p.relative_to(ROOT).as_posix()
                         for p in (ROOT/'crates/guradb/src').rglob('*.rs')})
        self.assertNotIn('threshold_percent', profile['denominator'])
        self.assertIn('retirement_manifest_sha256', profile['suites']['repository'])

    def test_offline_text_preparer_keeps_full_core_and_other_scripts_reject(self):
        profile = bound_plan(ROOT, ['scripts/prepare_text_corpus.py'], *load(ROOT)[:3],
                             stage='core', core_flow='simple-alpha')['profile']
        self.assertEqual(list(profile['suites']), ['repository', 'policy', 'harness-tests', 'python', 'rust', 'functional'])
        self.assertEqual(len(profile['suites']['rust']['commands']), 3)
        self.assertIn('scripts/alpha_acceptance.py', profile['command_inputs'])
        with self.assertRaisesRegex(HarnessError, 'unmapped changes'):
            bound_plan(ROOT, ['scripts/unknown_prepare.py'], *load(ROOT)[:3],
                       stage='core', core_flow='simple-alpha')

    def test_fixed_offline_clip_recipe_keeps_all_core_obligations(self):
        for path in ('scripts/prepare_clip_features.py', 'requirements-clip-macos-arm64.lock', 'docs/user/clip-queries.json'):
            profile = bound_plan(ROOT, [path], *load(ROOT)[:3], stage='core', core_flow='simple-alpha')['profile']
            self.assertEqual(list(profile['suites']), ['repository', 'policy', 'harness-tests', 'python', 'rust', 'functional'])
            self.assertEqual(len(profile['suites']['rust']['commands']), 3)
            self.assertIn('scripts/alpha_acceptance.py', profile['command_inputs'])
        for path in ('scripts/prepare_other_model.py', 'requirements-other-model.lock', 'docs/user/unregistered-model.json'):
            with self.assertRaisesRegex(HarnessError, 'unmapped changes'):
                bound_plan(ROOT, [path], *load(ROOT)[:3], stage='core', core_flow='simple-alpha')

    def test_torch_consumer_has_exact_mapping_and_full_rust_core(self):
        profile = bound_plan(ROOT, ['scripts/sample_torch_client.py'], *load(ROOT)[:3],
                             stage='core', core_flow='simple-alpha')['profile']
        self.assertEqual(list(profile['suites']), ['repository', 'policy', 'harness-tests', 'python', 'rust', 'functional'])
        self.assertEqual(len(profile['suites']['rust']['commands']), 3)
        with self.assertRaisesRegex(HarnessError, 'unmapped changes'):
            bound_plan(ROOT, ['scripts/unknown_torch_consumer.py'], *load(ROOT)[:3], stage='core', core_flow='simple-alpha')

    def test_m1_offline_composition_exact_mapping_preserves_all_core_suites(self):
        for path in ('scripts/m1_preview.py', 'scripts/m1_reference.py', 'scripts/m1_compare.py', 'docs/user/m1-inputs.json'):
            profile = bound_plan(ROOT, [path], *load(ROOT)[:3], stage='core', core_flow='simple-alpha')['profile']
            self.assertEqual(list(profile['suites']), ['repository', 'policy', 'harness-tests', 'python', 'rust', 'functional'])
            self.assertEqual(len(profile['suites']['rust']['commands']), 3)
        with self.assertRaisesRegex(HarnessError, 'unmapped changes'):
            bound_plan(ROOT, ['scripts/m1_unknown.py'], *load(ROOT)[:3], stage='core', core_flow='simple-alpha')

    def test_retired_runtime_reappearance_unknown_change_and_wrong_flow_reject(self):
        self.write('modules/index/server.py', 'pass\n')
        with self.assertRaisesRegex(HarnessError, 'retired path still present|Python online'):
            bound_plan(self.root, ['crates/guradb/src/main.rs'], *self.config[:3])
        (self.root/'modules/index/server.py').unlink()
        for paths, options in ((['unowned/other.rs'], {}), (['crates/guradb/src/main.rs'],
            {'stage': 'core', 'core_flow': 'fixed-read'})):
            with self.assertRaises(HarnessError):
                bound_plan(self.root, paths, *self.config[:3], **options)

    def test_failures_missing_logs_and_rehashed_changed_inputs_cannot_finish(self):
        report, path = self.report()
        for source in ('crates/guradb/src/main.rs', 'scripts/alpha_acceptance.py',
                       'scripts/harnesslib/stages.py', 'tests/harness/test_alpha_stage.py'):
            original = (self.root/source).read_text()
            self.write(source, original+'\n# input changed\n')
            value = copy.deepcopy(report); value['checkout_digest'] = checkout_digest(self.root, self.config[0])
            path.write_text(json.dumps(value))
            with self.assertRaises(HarnessError): validate_report(self.root, path, self.config)
            self.write(source, original)
        path.write_text(json.dumps(report))
        (self.root/report['results'][-1]['commands'][0]['log']).unlink()
        with self.assertRaises(HarnessError): checkpoint(self.root, 'missing-log', self.config[0], path, self.config)
        self.config[0]['suites']['functional']['commands'] = [['{python}', '-c', 'raise SystemExit(7)']]
        report, path = check(self.root, 'change', 'auto', self.config, 'auto')
        self.assertFalse(report['passed'])
        with self.assertRaises(HarnessError): finish_task(self.root, path, 'failure must reject', self.config)

    def test_documentation_only_and_release_obligations_stay_distinct(self):
        docs = bound_plan(ROOT, ['README.md'], *load(ROOT)[:3], stage='hardening')['profile']
        self.assertEqual(list(docs['suites']), ['repository'])
        release = bound_plan(ROOT, ['README.md'], *load(ROOT)[:3], stage='hardening', level='release')['profile']
        for suite in ('unit-coverage', 'performance', 'stability', 'soak'):
            self.assertEqual(release['suites'][suite]['state'], 'planned')

    def test_retirement_paths_are_canonical_unique_and_actually_absent(self):
        path = self.root/'harness/alpha-retired.json'
        original = json.loads(path.read_text())
        for entry in ({'path':'../outside','reason':'bad','category':'tool fixture'}, {'path': 'README.md', 'reason':'present','category':'tool fixture'}):
            value = copy.deepcopy(original); value['files'].append(entry); path.write_text(json.dumps(value))
            with self.assertRaises(HarnessError): retirement(self.root)

    def test_deleted_retired_owner_does_not_hide_live_unowned_sources(self):
        name = 'modules/old/source.py'
        self.write(name, 'pass\n')
        self.git('add', name)
        self.git('commit', '-m', 'historical owner fixture')
        with self.assertRaisesRegex(HarnessError, 'unowned production'):
            source_inventory(self.root, *self.config[:2], ['alpha'])
        (self.root/name).unlink()
        actual = source_inventory(self.root, *self.config[:2], ['alpha'])
        self.assertEqual(set(actual), {'crates/guradb/src/main.rs'})

    def test_official_mcp_client_lock_keeps_all_core_and_other_locks_reject(self):
        profile = bound_plan(ROOT, ['docs/user/mcp-client-requirements.lock'], *load(ROOT)[:3],
                             stage='core', core_flow='simple-alpha')['profile']
        self.assertEqual(list(profile['suites']), ['repository', 'policy', 'harness-tests', 'python', 'rust', 'functional'])
        self.assertEqual(len(profile['suites']['rust']['commands']), 3)
        with self.assertRaisesRegex(HarnessError, 'unmapped changes'):
            bound_plan(ROOT, ['docs/user/unregistered-client.lock'], *load(ROOT)[:3],
                       stage='core', core_flow='simple-alpha')


if __name__ == '__main__':
    unittest.main()
