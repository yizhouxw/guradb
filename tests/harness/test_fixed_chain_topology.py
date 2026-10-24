"""Failure ownership cases; no Docker or network calls in these tests."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[2] / 'scripts/m0lib/fixed-chain-topology.py'
SPEC = importlib.util.spec_from_file_location('fixed_chain_topology_tested', PATH)
TOPOLOGY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOPOLOGY)


class TopologyOwnershipTests(unittest.TestCase):
    def lab(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return TOPOLOGY.OwnedLab(Path(temporary.name))

    def resource(self, lab, owned=True):
        return {'Id': 'a' * 64, 'Image': TOPOLOGY.PG,
                'Config': {'Labels': {'gura.owner': 'fixed-chain-runtime',
                                     'gura.run': lab.nonce if owned else 'foreign'}}}

    def test_foreign_container_never_removed(self):
        lab = self.lab()
        lab.containers = [{'name': 'candidate', 'id': 'a' * 64, 'image': TOPOLOGY.PG}]
        with patch.object(lab, 'inspect', return_value=self.resource(lab, False)), \
                patch.object(lab, 'run') as commands:
            lab.close()
        commands.assert_not_called()
        self.assertTrue(lab.cleanup_errors)

    def test_same_nonce_different_cid_never_removed(self):
        lab = self.lab()
        lab.containers = [{'name': 'candidate', 'id': 'b' * 64, 'image': TOPOLOGY.PG}]
        with patch.object(lab, 'inspect', return_value=self.resource(lab)), \
                patch.object(lab, 'run') as commands:
            lab.close()
        commands.assert_not_called()
        self.assertTrue(lab.cleanup_errors)

    def test_owned_cleanup_keeps_prior_ambiguity(self):
        lab = self.lab()
        lab.ambiguous = True
        lab.containers = [{'name': 'candidate', 'id': 'a' * 64, 'image': TOPOLOGY.PG}]
        with patch.object(lab, 'inspect', side_effect=[self.resource(lab), None]), \
                patch.object(lab, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as commands:
            lab.close()
        self.assertEqual(commands.call_args_list[-1].args[0], ['rm', '-f', '-v', 'a' * 64])
        self.assertTrue(lab.ambiguous)
        self.assertEqual(lab.cleanup_errors, [])

    def test_foreign_or_nonempty_network_never_removed(self):
        for labels, containers in [({}, {}), ({'gura.owner': 'fixed-chain-runtime'}, {})]:
            lab = self.lab()
            lab.network_attempted = True
            with patch.object(lab, 'inspect', return_value={'Id': 'n', 'Labels': labels,
                                                         'Containers': containers}), \
                    patch.object(lab, 'run') as commands:
                lab.close()
            commands.assert_not_called()
            self.assertTrue(lab.cleanup_errors)
        lab = self.lab()
        lab.network_attempted = True
        with patch.object(lab, 'inspect', return_value={'Id': 'n', 'Containers': {'foreign': {}},
                         'Labels': {'gura.owner': 'fixed-chain-runtime', 'gura.run': lab.nonce}}), \
                patch.object(lab, 'run') as commands:
            lab.close()
        commands.assert_not_called()
        self.assertTrue(lab.cleanup_errors)

    def test_reject_unpinned_image_before_mkdir_or_docker(self):
        lab = self.lab()
        destination = lab.directory / 'new-run'
        with patch.object(TOPOLOGY, 'OwnedLab') as create:
            with self.assertRaises(ValueError):
                TOPOLOGY.execute(destination, 'runtime:latest')
        create.assert_not_called()
        self.assertFalse(destination.exists())

    def test_ownership_registered_before_create_mutation(self):
        lab = self.lab()

        def fail(args, **kwargs):
            self.assertEqual(lab.containers[0]['name'], 'candidate')
            self.assertTrue((lab.directory / 'owned-resources.json').exists())
            raise RuntimeError('create outcome unknown')

        with patch.object(lab, 'inspect', return_value=None), patch.object(lab, 'run', side_effect=fail):
            with self.assertRaises(RuntimeError):
                lab.create('candidate', TOPOLOGY.PG, [])

    def test_late_success_cannot_extend_startup_deadline(self):
        for seconds, global_remaining, late in [(15, 90, 16), (30, 90, 31), (30, 7, 8)]:
            with self.subTest(seconds=seconds, global_remaining=global_remaining):
                lab = self.lab()
                lab.deadline = global_remaining
                with patch.object(TOPOLOGY.time, 'monotonic', side_effect=[0, 0, late]), \
                        patch.object(TOPOLOGY.time, 'sleep') as sleep:
                    with self.assertRaises(TimeoutError):
                        lab.wait_ready(lambda cutoff: True, seconds=seconds)
                sleep.assert_not_called()

    def test_only_exact_kind_and_name_missing_diagnostic_means_absent(self):
        lab = self.lab()
        texts = {'container': 'Error response from daemon: No such container: candidate',
                 'network': 'Error response from daemon: network candidate not found',
                 'volume': 'Error response from daemon: get candidate: no such volume'}
        for kind, text in texts.items():
            with patch.object(lab, 'run', return_value=subprocess.CompletedProcess([], 1, '[]\n', text)):
                self.assertIsNone(lab.inspect('candidate', kind))
                with self.assertRaises(RuntimeError):
                    lab.inspect('different', kind)
        for text in ['Cannot connect: docker.sock: no such file or directory',
                     'Docker context not found', 'permission denied', texts['network']]:
            with patch.object(lab, 'run', return_value=subprocess.CompletedProcess([], 1, '[]\n', text)):
                with self.assertRaises(RuntimeError):
                    lab.inspect('candidate')

    def test_daemon_unavailable_cleanup_never_claims_absent(self):
        lab = self.lab()
        lab.containers = [{'name': 'candidate', 'id': 'a' * 64, 'image': TOPOLOGY.PG}]
        with patch.object(lab, 'run', return_value=subprocess.CompletedProcess(
                [], 1, '[]\n', 'docker.sock: no such file or directory')) as commands:
            lab.close()
        self.assertTrue(lab.cleanup_errors)
        self.assertEqual(json.loads((lab.directory / 'cleanup.json').read_text())['readbacks'], [])
        self.assertTrue(all(c.args[0][:2] == ['container', 'inspect'] for c in commands.call_args_list))

    def test_anonymous_volume_absence_must_be_confirmed_and_shared_is_preserved(self):
        for leftover in [None, {'Name': 'original-volume'}]:
            lab = self.lab()
            item = self.resource(lab)
            item['Mounts'] = [{'Type': 'volume', 'Name': 'original-volume'},
                              {'Type': 'bind', 'Source': '/user/config'}]
            lab.containers = [{'name': 'candidate', 'id': 'a' * 64, 'image': TOPOLOGY.PG,
                               'volumes': ['original-volume']}]
            with patch.object(lab, 'inspect', side_effect=[item, None, leftover]), \
                    patch.object(lab, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as commands:
                lab.close()
            self.assertEqual(bool(lab.cleanup_errors), leftover is not None)
            self.assertFalse(any(c.args[0][:2] == ['volume', 'rm'] for c in commands.call_args_list))
            readbacks = json.loads((lab.directory / 'cleanup.json').read_text())['readbacks']
            self.assertEqual(any('volume' in r for r in readbacks), leftover is None)

    def test_spawn_failure_before_child_is_durable(self):
        lab = self.lab()
        with patch.object(TOPOLOGY.subprocess, 'Popen', side_effect=OSError('spawn refused')):
            with self.assertRaisesRegex(OSError, 'spawn refused'):
                lab.run(['create', 'candidate'], mutation=True)
        record = json.loads((lab.directory / 'command-000.result.json').read_text())
        self.assertFalse(record['client_reaped'])
        self.assertNotIn('pid', record)
        self.assertFalse(lab.ambiguous)
        self.assertIn('spawn refused', record['primary_error'])
        self.assertTrue((lab.directory / 'command-000.intent.json').exists())

    def test_post_spawn_failure_reaps_only_owned_session_and_preserves_primary(self):
        class Client:
            pid = 424242
            returncode = None

            def __init__(self, results):
                self.results = results

            def poll(self):
                return self.returncode

            def wait(self, timeout):
                value = self.results.pop(0)
                if isinstance(value, BaseException):
                    raise value
                self.returncode = value
                return value

        for fault in ['getpgid', 'started-journal', 'timeout-exited-group', 'wait']:
            lab = self.lab()
            initial = (subprocess.TimeoutExpired(['docker'], 1) if fault == 'timeout-exited-group'
                       else RuntimeError('wait failed'))
            client = Client([initial, 0] if fault in ('timeout-exited-group', 'wait') else [0])
            original_write = TOPOLOGY.write

            def journal(path, value):
                if fault == 'started-journal' and path.name.endswith('.started.json'):
                    raise OSError('started journal failed')
                original_write(path, value)

            with patch.object(TOPOLOGY.subprocess, 'Popen', return_value=client), \
                    patch.object(TOPOLOGY.os, 'getpgid', side_effect=OSError('pgid failed')
                                 if fault == 'getpgid' else None, return_value=client.pid), \
                    patch.object(TOPOLOGY.os, 'killpg', side_effect=ProcessLookupError()
                                 if fault == 'timeout-exited-group' else None) as kill, \
                    patch.object(TOPOLOGY, 'write', side_effect=journal):
                with self.assertRaises(Exception):
                    lab.run(['create', 'candidate'], mutation=True)
            self.assertIsNotNone(client.returncode)
            self.assertTrue(lab.ambiguous)
            self.assertTrue(all(c.args[0] == client.pid for c in kill.call_args_list))
            record = json.loads((lab.directory / 'command-000.result.json').read_text())
            self.assertTrue(record['client_reaped'])
            self.assertIn('primary_error', record)

    def test_unreaped_client_blocks_resource_cleanup(self):
        lab = self.lab()
        client = SimpleNamespace(pid=424242, returncode=None)
        with patch.object(TOPOLOGY.subprocess, 'Popen', return_value=client), \
                patch.object(TOPOLOGY.os, 'getpgid', side_effect=OSError('pgid failed')), \
                patch.object(lab, 'reap', side_effect=RuntimeError('reap blocked')), \
                patch.object(lab, 'inspect') as inspect:
            with self.assertRaisesRegex(OSError, 'pgid failed'):
                lab.run(['create', 'candidate'], mutation=True)
            lab.close()
        inspect.assert_not_called()
        self.assertEqual(lab.pending_clients, [client])
        self.assertTrue(lab.ambiguous)
        self.assertTrue(lab.cleanup_errors)
        record = json.loads((lab.directory / 'command-000.result.json').read_text())
        self.assertIn('pgid failed', record['primary_error'])
        self.assertTrue(record['secondary_errors'])

    def test_success_inspect_requires_one_valid_kind_identity(self):
        lab = self.lab()
        valid = {
            'container': {'Id': 'a' * 64, 'Name': '/candidate', 'Image': TOPOLOGY.PG,
                          'Config': {'Labels': None}, 'Mounts': []},
            'network': {'Id': 'a' * 64, 'Name': 'candidate', 'Labels': {}, 'Containers': {}},
            'volume': {'Name': 'candidate', 'Driver': 'local', 'Mountpoint': '/owned-volume'},
        }
        for kind, item in valid.items():
            with patch.object(lab, 'run', return_value=subprocess.CompletedProcess(
                    [], 0, json.dumps([item]), '')):
                self.assertEqual(lab.inspect('candidate', kind), item)
                with self.assertRaises(RuntimeError):
                    lab.inspect('different', kind)
            for payload in [[None], [], [item, item], {}, [False], [{'Name': 'candidate'}]]:
                with patch.object(lab, 'run', return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps(payload), '')):
                    with self.assertRaises(RuntimeError):
                        lab.inspect('candidate', kind)

    def test_success_null_inspect_is_cleanup_hold_not_absence(self):
        lab = self.lab()
        lab.containers = [{'name': 'candidate', 'id': 'a' * 64, 'image': TOPOLOGY.PG}]
        with patch.object(lab, 'run', return_value=subprocess.CompletedProcess([], 0, '[null]', '')) as commands:
            lab.close()
        record = json.loads((lab.directory / 'cleanup.json').read_text())
        self.assertEqual(record['readbacks'], [])
        self.assertTrue(record['errors'])
        self.assertTrue(all(c.args[0][:2] == ['container', 'inspect'] for c in commands.call_args_list))
