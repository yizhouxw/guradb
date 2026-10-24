"""Coverage phase evidence survives interruption without inventing success."""
import hashlib
import json
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
import unit_coverage as gate


def records(directory):
    return [json.loads(line) for line in (directory/'phases.jsonl').read_text().splitlines()]


class ImageFixture:
    """Independent daemon catalog: a shared tag moves, a run reference stays."""
    first, second = 'sha256:'+'a'*64, 'sha256:'+'b'*64

    def __init__(self, failure=None):
        self.failure = failure
        self.commands = []
        self.stages = []
        self.inspects = []
        self.shared = self.first
        self.retained = None
        self.owner = None

    def run(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[:3] == ['docker', 'image', 'inspect']:
            return subprocess.CompletedProcess(argv, 1, b'', (
                'Error response from daemon: No such image: '+argv[-1]+'\n').encode())
        stage = 'build' if argv[1] == 'build' else 'export' if '--lcov' in argv else 'collect'
        self.stages.append(stage)
        if self.failure == stage:
            raise subprocess.CalledProcessError(23, argv)
        if self.failure == 'interrupt' and stage == 'collect':
            raise KeyboardInterrupt()
        if stage == 'build':
            Path(argv[argv.index('--iidfile')+1]).write_text(self.first+'\n')
            self.retained = argv[argv.index('-t')+1]
            self.owner = argv[argv.index('--label')+1].split('=', 1)[1]
            self.shared = self.second
        elif argv[argv.index('cargo')-1] != self.first:
            raise AssertionError('execution followed the shared tag instead of captured IID')
        if self.failure == 'lost_after_collect' and stage == 'collect':
            self.retained = None
        return subprocess.CompletedProcess(argv, 0)

    def inspect(self, argv, **kwargs):
        self.inspects.append(list(argv))
        if self.failure == 'inspect':
            raise subprocess.CalledProcessError(23, argv)
        if argv[-1] == self.first:
            return self.first.encode()+b'\n'
        if argv[-1] != self.retained:
            raise subprocess.CalledProcessError(1, argv)
        return (self.first+' '+self.owner+'\n').encode()


class CoveragePhaseEvidenceTests(unittest.TestCase):
    def test_external_kill_retains_only_the_durable_started_boundary(self):
        # The handshake is inside the operation: observing it proves the phase
        # record was flushed before work began. No timing race or sleep is used.
        script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from unit_coverage import PhaseEvidence
def blocked():
    print('phase-started', flush=True)
    sys.stdin.buffer.read(1)
PhaseEvidence(Path(sys.argv[2])).run('blocked_tool', blocked)
"""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            process = subprocess.Popen([sys.executable, '-c', script, str(ROOT/'scripts'), str(directory)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(timeout=5), 'child did not reach the operation')
                self.assertEqual(process.stdout.readline(), b'phase-started\n')
                self.assertIsNone(process.poll())
                self.assertEqual([row['event'] for row in records(directory)], ['run_started', 'started'])
                process.kill()
                process.communicate(timeout=5)
                self.assertNotEqual(process.returncode, 0)
                persisted = records(directory)
                self.assertEqual([row['event'] for row in persisted], ['run_started', 'started'])
                self.assertEqual(persisted[-1]['phase'], 'blocked_tool')
                self.assertNotIn('duration_seconds', persisted[-1])
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_exception_records_failure_and_preserves_the_original_exception(self):
        for error in (subprocess.TimeoutExpired(['private-argument'], 1), RuntimeError('private-message'),
                      KeyboardInterrupt()):
            with self.subTest(kind=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                evidence = gate.PhaseEvidence(directory)

                def fail():
                    self.assertEqual(records(directory)[-1]['event'], 'started')
                    raise error

                with self.assertRaises(type(error)) as caught:
                    evidence.run('tool', fail)
                self.assertIs(caught.exception, error)
                persisted = records(directory)
                self.assertEqual([row['event'] for row in persisted], ['run_started', 'started', 'failed'])
                self.assertEqual(persisted[-1]['exception_type'], type(error).__name__)
                self.assertGreaterEqual(persisted[-1]['duration_seconds'], 0)
                self.assertNotIn('private-', (directory/'phases.jsonl').read_text())

    def test_rejected_gate_never_records_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            evidence = gate.PhaseEvidence(directory)
            self.assertFalse(evidence.run('coverage', lambda: False))
            self.assertEqual(records(directory)[-1]['event'], 'failed')
            self.assertEqual(records(directory)[-1]['outcome'], 'rejected')
            self.assertNotIn('finished', [row['event'] for row in records(directory)])

    def test_completed_phase_has_matching_identity_and_monotonic_duration(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(gate.time, 'monotonic_ns', return_value=10) as clock:
            directory = Path(temporary)
            evidence = gate.PhaseEvidence(directory)

            def complete():
                clock.return_value += 2_000_000_000
                return 'result'

            self.assertEqual(evidence.run('summary', complete), 'result')
            started, finished = records(directory)[-2:]
            self.assertEqual(started['phase_id'], finished['phase_id'])
            self.assertEqual(finished['event'], 'finished')
            self.assertEqual(finished['duration_seconds'], 2)
            self.assertEqual(finished['monotonic_ns']-started['monotonic_ns'], 2_000_000_000)
            original = (directory/'phases.jsonl').read_bytes()
            with self.assertRaises(FileExistsError):
                gate.PhaseEvidence(directory)
            self.assertEqual((directory/'phases.jsonl').read_bytes(), original)

    def test_rust_collect_failure_prevents_lcov_and_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root/'run'
            directory.mkdir()
            evidence = gate.PhaseEvidence(directory)
            fixture = ImageFixture('collect')
            with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=fixture.run), \
                    patch.object(gate.subprocess, 'check_output', side_effect=fixture.inspect), \
                    patch.object(gate, 'rust_summary') as summary:
                with self.assertRaises(subprocess.CalledProcessError):
                    gate.rust_coverage(directory, evidence)
                summary.assert_not_called()
            self.assertEqual(fixture.stages, ['build', 'collect'])
            persisted = records(directory)
            self.assertEqual([row['phase'] for row in persisted if row['event'] == 'started'],
                             ['docker_image_build', 'docker_image_identity', 'rust_collect_test_json'])
            self.assertEqual(persisted[-1]['event'], 'failed')
            self.assertEqual(persisted[-1]['exception_type'], 'CalledProcessError')
            tool = next(row for row in persisted if row['event'] == 'tool_identity')
            self.assertEqual(tool['image_id'], fixture.first)
            self.assertEqual(tool['observation'], 'after_image_build')
            self.assertTrue((directory/'coverage-image-owner.json').is_file())

    def test_retag_cannot_replace_captured_collect_or_export_identity(self):
        for with_evidence in (False, True):
            with self.subTest(evidence=with_evidence), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = root/'run'
                directory.mkdir()
                evidence = gate.PhaseEvidence(directory) if with_evidence else None
                fixture = ImageFixture()
                with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=fixture.run), \
                        patch.object(gate.subprocess, 'check_output', side_effect=fixture.inspect), \
                        patch.object(gate, 'rust_summary', return_value=True) as summary:
                    self.assertTrue(gate.rust_coverage(directory, evidence))
                    summary.assert_called_once()
                self.assertEqual(fixture.stages, ['build', 'collect', 'export'])
                self.assertEqual(fixture.shared, fixture.second)
                runs = [argv for argv in fixture.commands if argv[1] == 'run']
                self.assertEqual([argv[argv.index('cargo')-1] for argv in runs], [fixture.first]*2)
                self.assertIn('--workspace', runs[0])
                self.assertIn('--locked', runs[0])
                self.assertIn('--json', runs[0])
                self.assertIn('--lcov', runs[1])
                self.assertEqual(runs[0][runs[0].index('--ignore-filename-regex')+1], '(^|/)tests/')
                intent = json.loads((directory/'coverage-image-owner.json').read_text())
                self.assertEqual(intent['retained_ref'], fixture.retained)
                self.assertTrue(all(argv[-1] in (fixture.first, fixture.retained) for argv in fixture.inspects))
                if with_evidence:
                    invokes = [row for row in records(directory) if row['event'] == 'tool_invocation']
                    actual = [row for row in invokes if row['argv'][1] == 'run']
                    self.assertEqual([row['argv'] for row in actual], runs)
                    self.assertEqual([row['image_id'] for row in actual], [fixture.first]*2)
                    starts = {row['phase']: row['phase_id'] for row in records(directory) if row['event'] == 'started'}
                    self.assertTrue(all(row['phase_id'] == starts[row['phase']] for row in invokes))
                    self.assertEqual(records(directory)[-1]['phase'], 'docker_image_retained')
                    self.assertEqual(records(directory)[-1]['event'], 'finished')

    def test_each_failed_tool_stops_later_phases_and_preserves_other_run(self):
        for failure in ('build', 'inspect', 'collect', 'export', 'interrupt', 'lost_after_collect'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = root/'run-a'
                directory.mkdir()
                other = root/'run-b'
                other.mkdir()
                (other/'result.json').write_bytes(b'independent evidence')
                evidence = gate.PhaseEvidence(directory)
                fixture = ImageFixture(failure)
                with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=fixture.run), \
                        patch.object(gate.subprocess, 'check_output', side_effect=fixture.inspect), \
                        patch.object(gate, 'rust_summary') as summary:
                    with self.assertRaises(KeyboardInterrupt if failure == 'interrupt' else subprocess.CalledProcessError):
                        gate.rust_coverage(directory, evidence)
                    summary.assert_not_called()
                last = 'collect' if failure in ('interrupt', 'lost_after_collect') else 'build' if failure == 'inspect' else failure
                expected = ['build', 'collect', 'export']
                self.assertEqual(fixture.stages, expected[:expected.index(last)+1])
                self.assertEqual(records(directory)[-1]['event'], 'failed')
                self.assertEqual((other/'result.json').read_bytes(), b'independent evidence')
                self.assertFalse((directory/'result.json').exists())
                self.assertTrue((directory/'coverage-image-owner.json').is_file())

    def test_missing_reference_after_summary_cannot_return_success(self):
        for summary_result in (False, True):
            with self.subTest(summary=summary_result), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = root/'run'
                directory.mkdir()
                fixture = ImageFixture()
                evidence = gate.PhaseEvidence(directory)

                def summarize(*args):
                    fixture.retained = None
                    return summary_result

                with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=fixture.run), \
                        patch.object(gate.subprocess, 'check_output', side_effect=fixture.inspect), \
                        patch.object(gate, 'rust_summary', side_effect=summarize):
                    if summary_result:
                        with self.assertRaises(subprocess.CalledProcessError):
                            gate.rust_coverage(directory, evidence)
                    else:
                        self.assertFalse(gate.rust_coverage(directory, evidence))
                self.assertEqual(records(directory)[-1]['event'], 'failed')
                self.assertTrue((directory/'coverage-image-owner.json').is_file())

    def test_source_identity_contains_exact_input_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = ['Cargo.lock', 'rust-toolchain.toml', '.coveragerc', 'harness/coverage-exclusions.json',
                     'tools/test-coverage/Dockerfile', 'scripts/unit_coverage.py', 'requirements-dev.lock',
                     'scripts/coverage_scope.py', 'scripts/coverage_policy.py', 'scripts/harnesslib/validation_registry.py',
                     'harness/architecture.toml', 'harness/policy.toml', 'harness/validation.toml']
            for path in paths:
                target = root/path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(path+'\n')
            with patch.object(gate, 'ROOT', root):
                hashes = gate.evidence_inputs()
            self.assertEqual(hashes, {path: hashlib.sha256((path+'\n').encode()).hexdigest() for path in paths})

    def test_main_persists_driver_exception_as_failed_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory = root/'run'
            with patch.object(gate, 'ROOT', root), patch.object(gate, 'identity', return_value={'checkout_digest': 'fixed'}), \
                    patch.object(gate, 'evidence_inputs', return_value={'Cargo.lock': 'fixed'}), \
                    patch.object(gate, 'python_coverage', side_effect=RuntimeError('private-message')), \
                    patch.object(gate.traceback, 'print_exc'), \
                    patch.object(sys, 'argv', ['unit_coverage.py', '--language', 'python', '--run-dir', str(directory)]):
                self.assertEqual(gate.main(), 1)
            outcome = json.loads((directory/'result.json').read_text())
            self.assertFalse(outcome['python'])
            self.assertTrue(outcome['unchanged_source'])
            phases = [row for row in records(directory) if row.get('phase') == 'python']
            self.assertEqual([row['event'] for row in phases], ['started', 'failed'])
            identity = next(row for row in records(directory) if row['event'] == 'source_identity')
            self.assertEqual(identity['inputs'], {'Cargo.lock': 'fixed'})
