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
            commands = []

            def execute(command, **kwargs):
                commands.append(command)
                if command[:2] == ['docker', 'build']:
                    Path(command[command.index('--iidfile')+1]).write_bytes(b'sha256:'+b'a'*64+b'\n')
                    return subprocess.CompletedProcess(command, 0)
                self.assertEqual(records(directory)[-1]['phase'], 'rust_collect_test_json')
                self.assertEqual(records(directory)[-2]['event'], 'started')
                self.assertEqual(records(directory)[-1]['event'], 'tool_invocation')
                self.assertEqual(records(directory)[-1]['argv'], command)
                raise subprocess.CalledProcessError(23, command)

            with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=execute), \
                    patch.object(gate.subprocess, 'check_output', return_value=b'sha256:'+b'a'*64), \
                    patch.object(gate, 'rust_summary') as summary:
                with self.assertRaises(subprocess.CalledProcessError):
                    gate.rust_coverage(directory, evidence)
                summary.assert_not_called()
            self.assertEqual(len(commands), 2)
            persisted = records(directory)
            self.assertEqual([row['phase'] for row in persisted if row['event'] == 'started'],
                             ['docker_image_build', 'docker_image_identity', 'rust_collect_test_json'])
            self.assertEqual(persisted[-1]['event'], 'failed')
            self.assertEqual(persisted[-1]['exception_type'], 'CalledProcessError')
            tool = next(row for row in persisted if row['event'] == 'tool_identity')
            self.assertEqual(tool['image_id'], 'sha256:'+'a'*64)
            self.assertEqual(tool['observation'], 'after_image_build')

    def test_retag_cannot_replace_captured_collect_or_export_identity(self):
        first, second = 'sha256:'+'a'*64, 'sha256:'+'b'*64
        for with_evidence in (False, True):
            with self.subTest(evidence=with_evidence), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = root/'run'
                directory.mkdir()
                evidence = gate.PhaseEvidence(directory) if with_evidence else None
                tag = {'current': first}
                calls = []

                def execute(argv, **kwargs):
                    calls.append(list(argv))
                    if argv[:2] == ['docker', 'build']:
                        Path(argv[argv.index('--iidfile')+1]).write_text(first+'\n')
                        tag['current'] = second  # Another build won the shared tag.
                    else:
                        self.assertEqual(argv[argv.index('cargo')-1], first)
                        self.assertEqual(tag['current'], second)
                        self.assertIn('--locked', argv)
                    return subprocess.CompletedProcess(argv, 0)

                def inspect(argv, **kwargs):
                    self.assertEqual(argv[-1], first)
                    self.assertEqual(tag['current'], second)
                    return first.encode()+b'\n'

                with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=execute), \
                        patch.object(gate.subprocess, 'check_output', side_effect=inspect), \
                        patch.object(gate, 'rust_summary', return_value=True) as summary:
                    self.assertTrue(gate.rust_coverage(directory, evidence))
                    summary.assert_called_once()
                self.assertEqual(len(calls), 3)
                self.assertIn('--workspace', calls[1])
                self.assertIn('--json', calls[1])
                self.assertIn('--lcov', calls[2])
                self.assertEqual(calls[1][calls[1].index('--ignore-filename-regex')+1], '(^|/)tests/')
                if with_evidence:
                    invokes = [row for row in records(directory) if row['event'] == 'tool_invocation']
                    self.assertEqual([row['phase'] for row in invokes],
                                     ['docker_image_build', 'docker_image_identity', 'rust_collect_test_json', 'rust_lcov_export'])
                    self.assertEqual([row['image_id'] for row in invokes[1:]], [first]*3)
                    starts = {row['phase']: row['phase_id'] for row in records(directory) if row['event'] == 'started'}
                    self.assertTrue(all(row['phase_id'] == starts[row['phase']] for row in invokes))
                    self.assertEqual(invokes[2]['argv'], calls[1])
                    self.assertEqual(invokes[3]['argv'], calls[2])

    def test_each_failed_tool_stops_later_phases_and_preserves_other_run(self):
        for failure in ('build', 'inspect', 'collect', 'export', 'interrupt'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = root/'run-a'
                directory.mkdir()
                other = root/'run-b'
                other.mkdir()
                (other/'result.json').write_bytes(b'independent evidence')
                evidence = gate.PhaseEvidence(directory)
                invoked = []

                def execute(argv, **kwargs):
                    stage = 'build' if argv[1] == 'build' else 'export' if '--lcov' in argv else 'collect'
                    invoked.append(stage)
                    if failure == stage:
                        raise subprocess.CalledProcessError(23, argv)
                    if failure == 'interrupt' and stage == 'collect':
                        raise KeyboardInterrupt()
                    if stage == 'build':
                        Path(argv[argv.index('--iidfile')+1]).write_bytes(b'sha256:'+b'a'*64)
                    return subprocess.CompletedProcess(argv, 0)

                def inspect(argv, **kwargs):
                    invoked.append('inspect')
                    if failure == 'inspect':
                        raise subprocess.CalledProcessError(23, argv)
                    return b'sha256:'+b'a'*64

                with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=execute), \
                        patch.object(gate.subprocess, 'check_output', side_effect=inspect), \
                        patch.object(gate, 'rust_summary') as summary:
                    with self.assertRaises(KeyboardInterrupt if failure == 'interrupt' else subprocess.CalledProcessError):
                        gate.rust_coverage(directory, evidence)
                    summary.assert_not_called()
                expected = ['build', 'inspect', 'collect', 'export']
                last = 'collect' if failure == 'interrupt' else failure
                self.assertEqual(invoked, expected[:expected.index(last)+1])
                self.assertEqual(records(directory)[-1]['event'], 'failed')
                self.assertEqual((other/'result.json').read_bytes(), b'independent evidence')
                self.assertFalse((directory/'result.json').exists())

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
