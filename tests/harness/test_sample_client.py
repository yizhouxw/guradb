"""External client ownership/argument tests, not framework or Rust truth."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('sample_client', ROOT/'scripts/sample_torch_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class SampleClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_bad_batch_limits_reject_without_creating_output(self):
        with patch.object(client, 'ROOT', self.root), patch.object(client.subprocess, 'Popen') as spawn:
            for size in (0, -1, 9):
                with self.assertRaisesRegex(ValueError, 'batch size'):
                    client.run(self.root/'cfg', self.root/'selection', Path('artifacts/output'), size)
            spawn.assert_not_called()
        self.assertFalse((self.root/'artifacts').exists())

    def test_existing_output_and_outside_paths_are_untouched(self):
        existing = self.root/'artifacts/existing'; existing.mkdir(parents=True)
        (existing/'keep').write_text('sentinel')
        with patch.object(client, 'ROOT', self.root), patch.object(client.subprocess, 'Popen') as spawn:
            for path in (Path('artifacts/existing'), Path('../outside'), Path('artifacts'), self.root/'absolute'):
                with self.assertRaises((ValueError, FileExistsError)):
                    client.run(self.root/'cfg', self.root/'selection', path, 4)
            spawn.assert_not_called()
        self.assertEqual((existing/'keep').read_text(), 'sentinel')

    def test_spawn_failure_cleans_owned_output_only(self):
        with patch.object(client, 'ROOT', self.root), patch.object(client.subprocess, 'Popen', side_effect=OSError('injected spawn failure')):
            with self.assertRaisesRegex(OSError, 'injected'):
                client.run(self.root/'cfg', self.root/'selection', Path('artifacts/new'), 4)
        self.assertFalse((self.root/'artifacts/new').exists())
        self.assertTrue(self.root.exists())

    def test_call_error_always_removes_the_exact_owned_container(self):
        cli = object.__new__(client.RustCLI)
        cli.config, cli.selection, cli.image = self.root/'config.json', self.root/'selection.json', 'sha256:fixture'
        cli.binary = self.root/'guradb'
        cli.calls, cli.counter, cli.current = [], 0, None
        with patch.object(client.subprocess, 'run') as run:
            run.side_effect = [OSError('injected Rust transport'), object()]
            with self.assertRaisesRegex(OSError, 'injected'):
                cli.call('sample', ['--selection', '/selection/selection.json'])
        first = run.call_args_list[0].args[0]
        cleanup = run.call_args_list[1].args[0]
        self.assertIn('guradb.sample.owner=', ' '.join(first))
        self.assertEqual(cleanup[:3], ['docker', 'rm', '-f'])
        self.assertEqual(cleanup[3], first[first.index('--name')+1])
        self.assertIsNone(cli.current)

    def test_invalid_host_mount_inputs_reject_before_docker_or_directory_creation(self):
        (self.root/'target/debug').mkdir(parents=True)
        (self.root/'target/debug/guradb').write_bytes(b'transport fixture, never executed')
        config, selection = self.root/'config.json', self.root/'selection.json'
        config.write_text('{}'); selection.write_text('{}')
        with patch.object(client, 'ROOT', self.root), patch.object(client.subprocess, 'check_output') as docker:
            for cfg, selected in ((self.root/'missing/config.json', selection), (config, self.root/'absent/selection.json'), (self.root, selection)):
                with self.assertRaises((ValueError, OSError)):
                    client.RustCLI(cfg, selected)
            config.write_bytes(b'x'*16385)
            with self.assertRaises(ValueError):
                client.RustCLI(config, selection)
            config.write_text('{}'); selection.write_bytes(b'x'*65537)
            with self.assertRaises(ValueError):
                client.RustCLI(config, selection)
            docker.assert_not_called()
        self.assertFalse((self.root/'missing').exists())
        self.assertFalse((self.root/'absent').exists())


if __name__ == '__main__':
    unittest.main()
