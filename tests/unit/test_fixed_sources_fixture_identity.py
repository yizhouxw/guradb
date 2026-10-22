"""Fixture metadata/prevalidation only; no SDK client, service or image is run."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests.source_support import fixed_backend_cases as backend


IMAGE = 'chrislusf/seaweedfs:3.97@sha256:' + 'b' * 64
SDK = {'sdk_versions': backend.SDK_VERSIONS,
       'sdk_init_sha256': {name: 'c' * 64 for name in backend.SDK_VERSIONS}}


def fixture(architecture='arm64'):
    cert = {'requested_image': IMAGE, 'image_id': 'sha256:' + 'a' * 64,
            'container_image_id': 'sha256:' + 'a' * 64, 'os': 'linux',
            'architecture': architecture, 'repo_digests': ['chrislusf/seaweedfs@' + IMAGE.split('@')[1]]}
    return SimpleNamespace(s3_certification=cert,
                           client=SimpleNamespace(meta=SimpleNamespace(config=SimpleNamespace(proxies={}))))


class FixedSourceFixtureIdentityTests(unittest.TestCase):
    def test_direct_request_precedes_safe_certificate_and_no_p04_upload(self):
        lab = fixture()
        lab.s3 = Mock()
        lab.client.put_object = Mock()
        with tempfile.TemporaryDirectory() as temporary, \
                patch('scripts.m0lib.kit.S3', IMAGE), patch.object(backend, 'sdk_identity', return_value=SDK):
            directory = Path(temporary)
            client, result = backend.start_fixture(lab, directory)
            lab.s3.assert_called_once_with(direct=True)
            self.assertIs(client, lab.client)
            self.assertEqual(json.loads((directory/'fixture-certification.json').read_text()), result)
            self.assertEqual(result['image_id'], lab.s3_certification['image_id'])
            self.assertEqual(result['repo_digests'], lab.s3_certification['repo_digests'])
            self.assertFalse(result['proxy_enabled'])
            lab.client.put_object.assert_not_called()

    def test_observed_platform_is_not_pinned_to_one_host(self):
        with patch.object(backend, 'sdk_identity', return_value=SDK):
            for architecture in ('arm64', 'amd64'):
                with self.subTest(architecture=architecture):
                    lab = fixture(architecture)
                    result = backend.certify_fixture(lab, IMAGE)
                    self.assertEqual(result['architecture'], architecture)
                    self.assertEqual(result['container_image_id'], result['image_id'])
                    result['repo_digests'].clear()
                    self.assertTrue(lab.s3_certification['repo_digests'])

    def test_unknown_fields_and_proxy_values_never_become_safe_evidence(self):
        with patch.object(backend, 'sdk_identity', return_value=SDK) as identity:
            for field, value in (('Config.Env', ['CANARY-SECRET']), ('endpoint', 'CANARY-SECRET')):
                lab = fixture()
                lab.s3_certification[field] = value
                with self.assertRaises(AssertionError):
                    backend.certify_fixture(lab, IMAGE)
            for proxies in (None, {'http': 'CANARY-SECRET'}):
                lab = fixture()
                lab.client.meta.config.proxies = proxies
                with self.assertRaises(AssertionError):
                    backend.certify_fixture(lab, IMAGE)
            identity.assert_not_called()

    def test_wrong_image_identity_and_malformed_platform_fail_before_sdk_identity(self):
        values = [('requested_image', IMAGE.replace('3.97', '3.96')),
                  ('container_image_id', 'sha256:' + 'd' * 64),
                  ('image_id', 'CANARY-SECRET'), ('os', 'darwin'),
                  ('architecture', 'CANARY-SECRET/path'),
                  ('repo_digests', ['chrislusf/seaweedfs@sha256:' + 'e' * 64])]
        with patch.object(backend, 'sdk_identity', return_value=SDK) as identity:
            for field, value in values:
                with self.subTest(field=field):
                    lab = fixture()
                    lab.s3_certification[field] = value
                    with self.assertRaises(AssertionError):
                        backend.certify_fixture(lab, IMAGE)
            identity.assert_not_called()

    def test_actual_sdk_versions_and_module_bytes_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'module.py'
            path.write_bytes(b'unit-sdk-module\n')
            modules = {name: SimpleNamespace(__version__=version, __file__=str(path))
                       for name, version in backend.SDK_VERSIONS.items()}
            with patch.object(backend, 'import_module', side_effect=modules.__getitem__), \
                    patch.object(backend, 'package_version', side_effect=backend.SDK_VERSIONS.__getitem__):
                self.assertEqual(backend.sdk_identity(), {
                    'sdk_versions': backend.SDK_VERSIONS,
                    'sdk_init_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                        for name in backend.SDK_VERSIONS}})
                modules['botocore'].__version__ = '0.0.0'
                with self.assertRaises(AssertionError):
                    backend.sdk_identity()

    def test_invalid_certificate_is_not_persisted_or_followed_by_upload(self):
        lab = fixture()
        lab.s3 = Mock()
        lab.s3_certification['container_image_id'] = 'sha256:' + 'd' * 64
        lab.client.put_object = Mock()
        with tempfile.TemporaryDirectory() as temporary, patch('scripts.m0lib.kit.S3', IMAGE):
            directory = Path(temporary)
            with self.assertRaises(AssertionError):
                backend.start_fixture(lab, directory)
            self.assertFalse((directory/'fixture-certification.json').exists())
            lab.client.put_object.assert_not_called()


if __name__ == '__main__':
    unittest.main()
