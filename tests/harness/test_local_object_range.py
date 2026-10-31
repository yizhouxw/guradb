"""Contract checks for the explicit local fixture namespace and engineering input."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


launcher = module('local_range_launcher_test', 'scripts/preview_launcher.py')
fixture = module('local_range_fixture_test', 'scripts/local_http_fixture.py')


class LocalNamespaceContract(unittest.TestCase):
    def setUp(self):
        self.cid = 'a' * 64
        self.image = 'sha256:' + 'b' * 64
        self.row = {'Id': self.cid, 'Image': self.image,
                    'State': {'Running': True, 'Paused': False, 'Restarting': False},
                    'HostConfig': {'NetworkMode': 'none', 'PortBindings': {}},
                    'NetworkSettings': {'Networks': {'none': {}}, 'Ports': {}},
                    'Config': {'Labels': {'guradb.local-http-fixture': 'v1'}}}

    def invoke(self, row):
        result = subprocess.CompletedProcess([], 0, json.dumps([row]).encode(), b'')
        with patch.object(launcher.subprocess, 'run', return_value=result) as run:
            value = launcher.local_http_network(['docker', '--host', 'unix:///test.sock'],
                                                {'runtime_image': self.image}, self.cid)
            self.assertEqual(run.call_args.args[0][:3], ['docker', '--host', 'unix:///test.sock'])
            return value

    def test_explicit_none_namespace_uses_exact_id(self):
        self.assertEqual(self.invoke(self.row), 'container:' + self.cid)

    def test_names_or_partial_ids_never_inspect(self):
        with patch.object(launcher.subprocess, 'run') as run:
            for cid in ('fixture-name', 'a' * 12, 'A' * 64, '--network=host'):
                with self.assertRaises(ValueError):
                    launcher.local_http_network(['docker'], {'runtime_image': self.image}, cid)
            run.assert_not_called()

    def test_no_bridge_host_other_network_or_changed_identity(self):
        mutations = [lambda r: r.update(Id='c' * 64), lambda r: r.update(Image='sha256:' + 'c' * 64),
                     lambda r: r['State'].update(Running=False), lambda r: r['State'].update(Paused=True),
                     lambda r: r['State'].update(Restarting=True), lambda r: r['HostConfig'].update(NetworkMode='host'),
                     lambda r: r['HostConfig'].update(NetworkMode='bridge'),
                     lambda r: r['HostConfig'].update(PortBindings={'80/tcp': [{}]}),
                     lambda r: r['NetworkSettings'].update(Networks={'none': {}, 'bridge': {}}),
                     lambda r: r['NetworkSettings'].update(Ports={'80/tcp': [{}]}),
                     lambda r: r['Config'].update(Labels={})]
        for mutation in mutations:
            row = copy.deepcopy(self.row)
            mutation(row)
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.invoke(row)


class FixtureInputContract(unittest.TestCase):
    def test_ordinary_capture_and_key_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'object'
            path.write_bytes(b'fixed-object')
            self.assertEqual(fixture.capture(path), b'fixed-object')
            path.unlink()
            path.symlink_to('/does-not-exist')
            with self.assertRaises(OSError):
                fixture.capture(path)
        self.assertTrue(fixture.valid_key('sintel/v1/silent.avi'))
        for key in ('', '/', '../x', 'a//b', 'a/./b', 'a?x', 'a%2fb', 'a\\b', 'a\r\nb'):
            self.assertFalse(fixture.valid_key(key))

    def test_strong_opaque_etag_quotes_are_single_bytes(self):
        for tag in ['"sintel-silent-v1-20261031"', '"a,b"', '"!:#"']:
            self.assertTrue(fixture.valid_etag(tag), tag)
        for tag in ['', '""', 'W/"weak"', '"a","b"', '"a\\b"', '"a\nb"']:
            self.assertFalse(fixture.valid_etag(tag), tag)

    def test_fifo_refuses_before_blocking(self):
        import os
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'fifo'
            os.mkfifo(path)
            code = ('import runpy,sys; x=runpy.run_path(sys.argv[1]); '
                    'x["capture"](sys.argv[2])')
            result = subprocess.run([sys.executable, '-B', '-c', code,
                                     str(ROOT / 'scripts/local_http_fixture.py'), str(path)],
                                    capture_output=True, timeout=2)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'bounded ordinary object', result.stderr)


if __name__ == '__main__':
    unittest.main()
