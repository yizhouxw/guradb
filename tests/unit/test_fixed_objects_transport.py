"""Actual loopback transport negatives; faults are separate from real S3 auth."""
import asyncio
from copy import deepcopy
import io
import logging
import socket
import threading
import time
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.storage.fixed_http import response_headers, validate_response
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_proofs import ProofAuthority
from modules.storage.fixed_scope import ReadScope
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
from modules.storage.fixed_transport import _receive, fetch
from tests.storage_support.fault_server import FaultServer, Response
from tests.storage_support.fixtures import TINY, binding, object_ref
from tests.storage_support.fixtures import sha
from tests.storage_support.acceptance import scope_snapshot


class FixedTransportTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger('botocore.auth')
        previous = self.logger.disabled
        self.logger.disabled = True
        self.addCleanup(setattr, self.logger, 'disabled', previous)

    def backend(self, endpoint, **values):
        config = {'backend_id': 'local_s3', 'bucket': 'm0-data', 'endpoint': endpoint,
                  'credentials': CredentialSnapshot('test-key', 'test-secret'), 'versioning_certified': True}
        config.update(values)
        return FixedBackend(**config)

    def instance(self, server, ref=None, *, timeout=3000, cancel=lambda: False):
        ref = object_ref() if ref is None else ref
        scope = ReadScope(binding(ref, timeout_ms=timeout), cancel)
        authority = ProofAuthority({ref['integrity']['proof_ref']: ref}) if ref['integrity']['block_size'] else None
        return FixedObjects(scope, {'local_s3': self.backend(server.endpoint)}, lambda _: 1, proofs=authority)

    def failure(self, code, call):
        with self.assertRaises(ContractFailure) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_real_socket_whole_range_and_exact_accounting(self):
        for partial in (False, True):
            ref = object_ref(block_size=4 if partial else 0)
            response = Response(body=b'4567', extra_headers=(('Content-Range', 'bytes 4-7/16'),), status=206) if partial else Response()
            with FaultServer([response]) as server:
                instance = self.instance(server, ref)
                actual = instance.read(instance.scope.binding, ref, 4 if partial else 0, 4 if partial else 16)
                returned = instance.scope.monotonic()
                self.assertEqual(actual, b'4567' if partial else TINY)
                self.assertEqual(instance.scope.object_requests, server.requests)
                self.assertEqual(instance.scope.object_bytes, len(actual))
                self.assertTrue(server.wait_idle())
                self.assertEqual(instance.scope.header_bytes, server.sent_header)
                self.assertEqual(instance.scope.wire_bytes, server.sent_header + len(actual))
                self.assertIn('socket_closed', [event['event'] for event in instance.scope.trace])
                measured = scope_snapshot(instance.scope, returned)
                self.assertEqual(measured['received_header_bytes'], server.sent_header)
                self.assertEqual(measured['received_body_bytes'], len(actual))
                self.assertEqual(measured['received_wire_bytes'], measured['received_header_bytes'] + len(actual))
                self.assertEqual(measured['verified_bytes'], len(actual))
                self.assertLessEqual(measured['last_header_positive_receive_elapsed_us'],
                                     measured['last_body_positive_receive_elapsed_us'])
                self.assertLessEqual(measured['last_body_positive_receive_elapsed_us'],
                                     measured['last_socket_close_elapsed_us'])
                self.assertLessEqual(measured['last_socket_close_elapsed_us'], measured['observed_return_elapsed_us'])

    def test_headers_status_framing_and_integrity_fail_closed(self):
        responses = [
            (Response(status=403), 'unauthorized'), (Response(status=404), 'missing_object'),
            (Response(status=302), 'unsupported_capability'), (Response(status=100), 'unsupported_capability'),
            (Response(version='wrong'), 'corrupt_object'), (Response(declared_length=15), 'corrupt_object'),
            (Response(extra_headers=(('Content-Length', '16'),)), 'corrupt_object'),
            (Response(extra_headers=(('Transfer-Encoding', 'chunked'),)), 'unsupported_capability'),
            (Response(extra_headers=(('Content-Encoding', 'gzip'),)), 'unsupported_capability'),
            (Response(extra_headers=(('x-amz-delete-marker', 'true'),)), 'missing_object'),
            (Response(body=b'bad!' * 4), 'corrupt_object'),
            (Response(body=TINY[:-1], declared_length=16), 'corrupt_object'),
            (Response(body=TINY + b'x', declared_length=16), 'corrupt_object'),
            (Response(status=206), 'corrupt_object'),
        ]
        for response, code in responses:
            with self.subTest(response=response, code=code), FaultServer([response]) as server:
                instance = self.instance(server)
                self.failure(code, lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
                self.assertEqual(instance.scope.output_bytes, 0)
                self.assertEqual(instance.scope.object_requests, 1)
        malformed = [b'HTTP/1.1 200 OK\r\n\xff\r\n\r\n', b'HTTP/1.0 200 OK\r\n\r\n',
                     b'HTTP/1.1 200 OK\r\n bad: folded\r\n\r\n',
                     b'HTTP/1.1 200 OK\r\nX: bad\nvalue\r\n\r\n',
                     b'HTTP/1.1 200 OK\r\n' + b'X: v\r\n' * 65 + b'\r\n',
                     b'HTTP/1.1 200 OK\r\nX: ' + b'a' * 8192 + b'\r\n\r\n']
        for raw in malformed:
            self.failure('corrupt_object', lambda: response_headers(raw))
        self.failure('corrupt_object', lambda: response_headers(b'incomplete'))
        with FaultServer([Response(raw_headers=b'x' * 32768)]) as server:
            instance = self.instance(server)
            self.failure('corrupt_object', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
        with FaultServer([Response(raw_headers=b'HTTP/1.1 200 OK\r\n', body=b'')]) as server:
            instance = self.instance(server)
            self.failure('corrupt_object', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))

    def test_retry_statuses_count_actual_gets_and_stop(self):
        with FaultServer([Response(status=429), Response(status=503), Response()]) as server:
            instance = self.instance(server)
            self.assertEqual(instance.read(instance.scope.binding, object_ref(), 0, 16), TINY)
            self.assertEqual(instance.scope.object_requests, 3)
            self.assertEqual(server.requests, 3)
        with FaultServer([Response(status=503)]) as server:
            instance = self.instance(server)
            self.failure('backend_unavailable', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
            self.assertEqual(server.requests, 3)
        ref = object_ref()
        scope = ReadScope(binding(ref))
        original_socket = socket.socket
        def fail_owned_socket(family=socket.AF_INET, *args, **kwargs):
            if family == socket.AF_INET:
                raise OSError('injected owned socket allocation failure')
            return original_socket(family, *args, **kwargs)
        with patch('modules.storage.fixed_transport.socket.socket', side_effect=fail_owned_socket):
            self.failure('backend_unavailable', lambda: fetch(scope, self.backend('http://127.0.0.1:1'), ref, 0, 16))
        self.assertEqual(scope.object_requests, 1)

    def test_absolute_deadline_covers_header_and_body_dribble_and_eof(self):
        for response in (Response(header_delay=2), Response(header_chunk=1, header_interval=.015),
                         Response(body_delay=2), Response(body_chunk=1, body_interval=.15),
                         Response(eof_delay=2)):
            with self.subTest(response=response), FaultServer([response]) as server:
                instance = self.instance(server, timeout=700)
                started = time.monotonic()
                self.failure('deadline', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
                self.assertLess(time.monotonic() - started, .700)
                self.assertTrue(server.wait_idle(.100))
                self.assertEqual(instance.scope.output_bytes, 0)
        with FaultServer() as server:
            instance = self.instance(server, timeout=100)
            self.failure('deadline', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
            self.assertEqual(server.requests, 0)

    def test_external_cancellation_closes_io_and_no_later_attempt(self):
        for response in (Response(header_delay=2), Response(body_delay=2), Response(eof_delay=2)):
            event = threading.Event()
            with FaultServer([response]) as server:
                instance = self.instance(server, cancel=event.is_set)
                timer = threading.Timer(.080, event.set)
                timer.start()
                try:
                    self.failure('cancelled', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
                finally:
                    timer.join()
                self.assertTrue(server.wait_idle(.100))
                self.assertEqual(server.requests, 1)
                self.assertEqual(instance.scope.output_bytes, 0)
        async def before_start():
            scope = ReadScope(binding(object_ref()), cancelled=lambda: True)
            self.failure_async = _receive(scope, ('127.0.0.1', 1), b'', object_ref(), 0, 16)
            with self.assertRaises(ContractFailure):
                await self.failure_async
        asyncio.run(before_start())
        with FaultServer([Response(header_delay=2)]) as server:
            scope = ReadScope(binding(object_ref()))
            async def cancel_task():
                task = asyncio.create_task(_receive(scope, self.backend(server.endpoint).address,
                    self.backend(server.endpoint).request(object_ref(), 0, 16, scope.context['deadline_unix_ms']), object_ref(), 0, 16))
                await asyncio.sleep(.025)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            asyncio.run(cancel_task())
            self.assertTrue(server.wait_idle(.100))

    def test_backend_limits_signature_encoding_and_log_precondition(self):
        for endpoint in ('https://127.0.0.1:1', 'http://localhost:1', 'http://192.0.2.1:1',
                         'http://127.0.0.1:1/', 'http://127.0.0.1:1?key=secret',
                         'http://key:secret@127.0.0.1:1', 'http://127.0.0.1:bad',
                         'http://127.0.0.1:0', 'http://[', 'http://127.0.0.1:1?',
                         'http://127.0.0.1:1#', 'http://127.0.0.1:01', 'http://127.0.0.1:99999',
                         None, 123):
            self.failure('unsupported_capability', lambda: self.backend(endpoint))
        for values, code in (({'bucket': 'bad bucket'}, 'unsupported_capability'),
                             ({'bucket': 'other-valid-bucket'}, 'unsupported_capability'),
                             ({'region': 'other-region'}, 'unsupported_capability'),
                             ({'backend_id': None}, 'unsupported_capability'),
                             ({'versioning_certified': 1}, 'invalid_contract'),
                             ({'credentials': None}, 'unauthorized')):
            self.failure(code, lambda: self.backend('http://127.0.0.1:1', **values))
        backend = self.backend('http://127.0.0.1:1')
        ref = object_ref(version='opaque+/=', key='a b/中文/%/+//%2E/file')
        request = backend.request(ref, 0, 16, 1000)
        self.assertTrue(request.startswith(b'GET /m0-data/a%20b/%E4%B8%AD%E6%96%87/%25/%2B//%252E/file?versionId=opaque%2B%2F%3D HTTP/1.1\r\n'))
        self.assertIn(b'X-Amz-Content-SHA256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', request)
        self.assertIn(b'Range: bytes=4-7', backend.request(object_ref(), 4, 4, 1000))
        self.failure('unsupported_capability', lambda: self.backend('http://127.0.0.1:1', versioning_certified=False).request(ref, 0, 16, 1000))
        self.failure('unsupported_capability', lambda: backend.request(object_ref(version='null'), 0, 16, 1000))
        self.failure('resource_limit', lambda: backend.request(object_ref(key='文' * 4096), 0, 16, 1000))
        previous_level = self.logger.level
        self.logger.disabled = False
        self.logger.setLevel(logging.DEBUG)
        try:
            self.failure('unsupported_capability', lambda: backend.request(ref, 0, 16, 1000))
        finally:
            self.logger.setLevel(previous_level)
            self.logger.disabled = True
        for credentials in (CredentialSnapshot('', 'secret'), CredentialSnapshot('key', 'secret\n'),
                            CredentialSnapshot('key', 'secret', token='bad\r'),
                            CredentialSnapshot('key', 'secret', expires_unix_ms=999)):
            self.failure('unauthorized', lambda: credentials.frozen(1000))

    def test_session_token_debug_capture_and_signed_target_in_memory_only(self):
        output = io.StringIO()
        root = logging.getLogger()
        previous = root.level
        handler = logging.StreamHandler(output)
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        canaries = ('P03-ACCESS-CANARY', 'P03-SECRET-CANARY', 'P03-TOKEN-CANARY')
        try:
            credentials = CredentialSnapshot(*canaries)
            backend = self.backend('http://127.0.0.1:1', credentials=credentials)
            request = backend.request(object_ref(key='api_key=URL-CANARY'), 0, 16, 1000)
            self.assertIn(b'X-Amz-Security-Token: P03-TOKEN-CANARY', request)
            signature = request.split(b'Signature=', 1)[1].split(b'\r\n', 1)[0].decode()
            for secret in (*canaries, signature, 'URL-CANARY', 'Authorization'):
                self.assertNotIn(secret, output.getvalue())
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
            handler.close()

    def test_response_range_metadata_missing_and_noncanonical_length(self):
        headers = {'content-length': '4', 'x-amz-version-id': 'v1'}
        self.failure('corrupt_object', lambda: validate_response(206, headers, object_ref(), 4, 4))
        for length in ('04', '', '16,16'):
            changed = {'content-length': length, 'x-amz-version-id': 'v1'}
            self.failure('corrupt_object', lambda: validate_response(200, changed, object_ref(), 0, 16))
        headers = {'content-length': '16', 'x-amz-version-id': 'v1', 'content-range': 'bytes 0-15/16'}
        self.failure('corrupt_object', lambda: validate_response(200, headers, object_ref(), 0, 16))
        # A simulated signer producing an upload must not reach any socket.
        backend = self.backend('http://127.0.0.1:1')
        with patch('modules.storage.fixed_signing.S3SigV4Auth'), patch('modules.storage.fixed_signing.AWSRequest.prepare') as prepare:
            prepare.return_value.url = 'changed'
            self.failure('unsupported_capability', lambda: backend.request(object_ref(), 0, 16, 1000))

    def test_cancel_callback_exception_mid_io_is_sanitized_and_reaped(self):
        event = threading.Event()
        private = 'P03-CANCEL-PRIVATE-CANARY'
        def cancellation():
            if event.is_set():
                raise RuntimeError(private)
            return False
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        root = logging.getLogger()
        previous = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        try:
            with FaultServer([Response(body_delay=2)]) as server:
                instance = self.instance(server, cancel=cancellation)
                timer = threading.Timer(.080, event.set)
                timer.start()
                try:
                    self.failure('cancelled', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
                finally:
                    timer.join()
                self.assertTrue(server.wait_idle(.100))
                self.assertEqual(instance.scope.output_bytes, 0)
                self.assertEqual(server.requests, 1)
            self.assertNotIn(private, output.getvalue())
            self.assertNotIn('Exception in callback', output.getvalue())
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
            handler.close()

    def test_live_caller_ref_rewrite_during_body_wait_cannot_accept_bad_bytes(self):
        for block in (False, True):
            ref = object_ref(block_size=4 if block else 0)
            original = deepcopy(ref)
            bad = b'bad!' * 4
            with FaultServer([Response(body=bad, body_delay=.150)]) as server:
                instance = self.instance(server, ref)
                def rewrite():
                    ref.update(key='changed-mid-io', version='changed-mid-io', sha256=sha(bad))
                    if block:
                        ref['integrity']['block_sha256'][:] = [sha(b'bad!')] * 4
                timer = threading.Timer(.040, rewrite)
                timer.start()
                try:
                    self.failure('corrupt_object', lambda: instance.read(instance.scope.binding, ref, 0, 16))
                finally:
                    timer.join()
                self.assertTrue(server.wait_idle(.100))
                self.assertEqual(instance.scope.object_bytes, 16)
                self.assertEqual(instance.scope.output_bytes, 0)
                self.assertIsNone(instance.cache.get(instance.cache.key(original, 0, 16)))
