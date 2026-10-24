"""Exercise real ClientError classification before the driver's safe failure artifact."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from tests.storage_support.acceptance import FixturePutFailure, special_fixture_put


CANARY = 'P03-FIXTURE-CLASSIFICATION-SECRET-CANARY'
KEY = 'fixture-only/key'


def failed_client(code, status):
    response = {'Error': {'Code': code, 'Message': CANARY, 'Resource': CANARY},
                'ResponseMetadata': {'HTTPStatusCode': status,
                                     'HTTPHeaders': {'Authorization': CANARY}},
                'credentials': CANARY}
    client = Mock()
    client.put_object.side_effect = ClientError(response, CANARY)
    return client


class FixturePutClassificationTests(unittest.TestCase):
    def assert_put_called_once(self, client):
        client.put_object.assert_called_once_with(Bucket='m0-data', Key=KEY, Body=b'0123456789abcdef')

    def assert_driver_failure(self, case, client, expected_fixture=None):
        root = Path(__file__).resolve().parents[2]
        with patch.object(sys, 'path', [str(root/'scripts'), *sys.path]):
            from scripts import fixed_objects_acceptance as driver
        with tempfile.TemporaryDirectory(dir=root/'artifacts') as temporary:
            directory = Path(temporary)/'run'
            stdout, stderr = io.StringIO(), io.StringIO()

            def actual_classification(_lab, _suite):
                return special_fixture_put(client, case, KEY)

            with patch.object(sys, 'argv', ['fixed_objects_acceptance.py', '--suite', 'functional',
                                           '--run-dir', str(directory)]), \
                    patch.object(driver, 'identity', return_value={'fixture_test': 'source-only-mock'}), \
                    patch.object(driver, 'laboratory'), \
                    patch.object(driver, 'real_backend', side_effect=actual_classification), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(driver.main(), 1)
            self.assertFalse((directory/'result.json').exists())
            raw = (directory/'failure.json').read_text()
            public = raw + stdout.getvalue() + stderr.getvalue()
            for forbidden in (CANARY, 'https://secret.invalid/', 'Authorization', 'credentials'):
                self.assertNotIn(forbidden, public)
            artifact = json.loads(raw)
            self.assertIs(artifact['passed'], False)
            self.assertEqual(artifact['suite'], 'functional')
            self.assertEqual(artifact['code'], 'driver_assertion')
            self.assertTrue(any(item['function'] == 'special_fixture_put' for item in artifact['trace']))
            if expected_fixture is None:
                self.assertEqual(artifact['error_class'], 'AssertionError')
                self.assertNotIn('fixture', artifact)
            else:
                self.assertEqual(artifact['error_class'], 'FixturePutFailure')
                self.assertEqual(artifact['fixture'], expected_fixture)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIs(json.loads(stdout.getvalue())['passed'], False)
        self.assert_put_called_once(client)

    def expected(self, case, code, status):
        return {'case_id': case, 'stage': 'fixture_put',
                'backend_error_code': code, 'http_status': status}

    def test_three_supported_keys_preserve_successful_fixed_versions(self):
        for case in ('space', 'unicode-percent-plus', 'repeated-separator'):
            with self.subTest(case=case):
                client = Mock()
                client.put_object.return_value = {'VersionId': 'immutable-fixture-version'}
                self.assertEqual(special_fixture_put(client, case, KEY), 'immutable-fixture-version')
                self.assert_put_called_once(client)

    def test_exact_dot_403_is_only_a_negative_classification_not_a_backend_version(self):
        client = failed_client('SignatureDoesNotMatch', 403)
        outcome = special_fixture_put(client, 'dot-segment', KEY)
        self.assertIsInstance(outcome, FixturePutFailure)
        self.assertNotIsInstance(outcome, str)
        self.assertEqual(outcome.diagnostics(), self.expected('dot-segment', 'SignatureDoesNotMatch', 403))
        self.assertFalse(hasattr(outcome, 'response'))
        self.assert_put_called_once(client)

    def test_unexpected_dot_errors_reach_outer_failure_artifact(self):
        for code, status in (('InvalidArgument', 400), ('NoSuchKey', 404),
                             ('AccessDenied', 403), ('SignatureDoesNotMatch', 404)):
            with self.subTest(code=code, status=status):
                self.assert_driver_failure('dot-segment', failed_client(code, status),
                                           self.expected('dot-segment', code, status))

    def test_other_three_keys_cannot_accept_even_the_exact_dot_error(self):
        for case in ('space', 'unicode-percent-plus', 'repeated-separator'):
            with self.subTest(case=case):
                self.assert_driver_failure(case, failed_client('SignatureDoesNotMatch', 403),
                                           self.expected(case, 'SignatureDoesNotMatch', 403))

    def test_malicious_sdk_fields_are_sanitized_after_actual_classification(self):
        for code, status, expected_code, expected_status in (
                ('https://secret.invalid/' + CANARY, CANARY, 'unknown', None),
                ('A' * 65, True, 'unknown', None),
                ('InvalidArgument', 400, 'InvalidArgument', 400)):
            with self.subTest(expected_code=expected_code, expected_status=expected_status):
                self.assert_driver_failure('dot-segment', failed_client(code, status),
                                           self.expected('dot-segment', expected_code, expected_status))

    def test_unexpected_dot_success_still_fails_in_the_same_helper(self):
        client = Mock()
        client.put_object.return_value = {'VersionId': 'unexpected-dot-version'}
        self.assert_driver_failure('dot-segment', client)

    def test_supported_key_without_immutable_version_still_rejects(self):
        for version in (None, 'null'):
            with self.subTest(version=version):
                client = Mock()
                client.put_object.return_value = {'VersionId': version}
                with self.assertRaises(AssertionError):
                    special_fixture_put(client, 'space', KEY)
                self.assert_put_called_once(client)
