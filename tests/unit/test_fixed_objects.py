"""Fixed bytes, authorization and cumulative costs against independent inputs."""
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError

from modules.common.cf1a_primitives import ContractFailure
from modules.storage.fixed_cache import VerifiedCache
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_proofs import ProofAuthority
from modules.storage.fixed_scope import ReadScope
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
from tests.storage_support.fixtures import TINY, binding, object_ref, sha
from tests.storage_support.acceptance import FixturePutFailure, scope_snapshot


def reader(ref=None, *, cache=None, proofs=None, budget=None, cancelled=lambda: False,
           reauthorize=lambda _: 1, endpoint='http://127.0.0.1:1', timeout=3000):
    ref = object_ref() if ref is None else ref
    scope = ReadScope(binding(ref, budget=budget, timeout_ms=timeout), cancelled)
    backend = FixedBackend('local_s3', 'm0-data', endpoint,
                           CredentialSnapshot('test-key', 'test-secret'), True)
    return FixedObjects(scope, {'local_s3': backend}, reauthorize,
                        proofs=proofs, cache=cache)


def downloaded(scope, backend, ref, offset, length):
    scope.request(length)
    result = TINY[offset:offset + length]
    scope.received(len(result))
    return result


class FixedObjectsTests(unittest.TestCase):
    def setUp(self):
        logger = logging.getLogger('botocore.auth')
        self.disabled = logger.disabled
        logger.disabled = True
        self.addCleanup(setattr, logger, 'disabled', self.disabled)

    def assert_code(self, expected, call):
        with self.assertRaises(ContractFailure) as caught:
            call()
        self.assertEqual(caught.exception.code, expected)

    def test_whole_cache_rechecks_bytes_permission_and_scope(self):
        epochs = []
        def authorize(value):
            epochs.append(value.sha256)
            return 1
        instance = reader(reauthorize=authorize)
        ref = object_ref()
        with patch('modules.storage.fixed_objects.fetch', side_effect=downloaded) as fetch:
            for _ in range(2):
                self.assertEqual(instance.port.read(instance.scope.binding, ref, 0, 16), TINY)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(instance.scope.object_requests, 1)
        self.assertEqual(instance.scope.object_bytes, 16)
        self.assertEqual(instance.scope.output_bytes, 32)
        self.assertEqual(instance.scope.verified_bytes, 32)
        self.assertEqual(instance.cache.hits, 1)
        self.assertGreaterEqual(len(epochs), 5)
        self.assertEqual(instance.scope.memory_current, 2 * (16 + 64))

    def test_trusted_blocks_and_short_tail_exact_bytes(self):
        ref = object_ref(block_size=5)
        proofs = ProofAuthority({ref['integrity']['proof_ref']: ref})
        instance = reader(ref, proofs=proofs)
        with patch('modules.storage.fixed_objects.fetch', side_effect=downloaded):
            self.assertEqual(instance.read(instance.scope.binding, ref, 5, 10), b'56789abcde')
            self.assertEqual(instance.read(instance.scope.binding, ref, 15, 1), b'f')
        self.assertEqual(instance.scope.verified_bytes, 11)
        self.assertEqual(instance.scope.object_requests, 2)
        instance.port.verify_proof(ref)
        self.assert_code('invalid_contract', lambda: instance.read(instance.scope.binding, ref, 1, 5))

    def test_untrusted_or_changed_table_and_corrupt_cache_never_output(self):
        ref = object_ref(block_size=4)
        instance = reader(ref)
        self.assert_code('corrupt_object', lambda: instance.read(instance.scope.binding, ref, 4, 4))
        trusted = ProofAuthority({ref['integrity']['proof_ref']: ref})
        changed = deepcopy(ref)
        changed['integrity']['block_sha256'][1] = '0' * 64
        self.assert_code('corrupt_object', lambda: trusted.verify(changed))
        for block in (False, True):
            ref = object_ref(block_size=4 if block else 0)
            authority = ProofAuthority({ref['integrity']['proof_ref']: ref}) if block else None
            instance = reader(ref, proofs=authority)
            instance.cache.put(instance.cache.key(ref, 0, 16), b'bad!' * 4)
            self.assert_code('corrupt_object', lambda: instance.read(instance.scope.binding, ref, 0, 16))
            self.assertEqual(instance.scope.output_bytes, 0)
            self.assertEqual(instance.scope.object_requests, 0)

    def test_whole_partial_scope_member_null_version_and_size_rejected(self):
        instance = reader()
        ref = object_ref()
        self.assert_code('invalid_contract', lambda: instance.read(instance.scope.binding, ref, 4, 4))
        other = object_ref(key='not-a-member')
        self.assert_code('unauthorized', lambda: instance.read(instance.scope.binding, other, 0, 16))
        self.assert_code('invalid_contract', lambda: instance.read(binding(other), ref, 0, 16))
        for changed, code in ((object_ref(version='null'), 'unsupported_capability'),
                              (object_ref(backend='other'), 'unsupported_capability')):
            instance = reader(changed)
            self.assert_code(code, lambda: instance.read(instance.scope.binding, changed, 0, 16))
        large = object_ref()
        large['size_bytes'] = (8 << 20) + 1
        instance = reader(large)
        self.assert_code('resource_limit', lambda: instance.read(instance.scope.binding, large, 0, large['size_bytes']))

    def test_permission_failure_and_revocation_after_network_or_cache(self):
        for failure in (RuntimeError('private diagnostic'), ContractFailure('unauthorized', 'denied')):
            def deny(_):
                raise failure
            instance = reader(reauthorize=deny)
            self.assert_code('unauthorized', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
        revoked = [False]
        instance = reader(reauthorize=lambda _: 2 if revoked[0] else 1)
        def revoke_after_receive(*args):
            result = downloaded(*args)
            revoked[0] = True
            return result
        with patch('modules.storage.fixed_objects.fetch', side_effect=revoke_after_receive):
            self.assert_code('revoked', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
        self.assertEqual(instance.scope.object_bytes, 16)
        self.assertEqual(instance.scope.output_bytes, 0)
        revoked[0] = False
        with patch('modules.storage.fixed_objects.fetch', side_effect=downloaded):
            instance.read(instance.scope.binding, object_ref(), 0, 16)
        revoked[0] = True
        self.assert_code('revoked', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))

    def test_output_memory_request_and_eof_byte_admission(self):
        for budget in ({'output_bytes': 15}, {'memory_bytes': 1}, {'object_bytes': 16}):
            instance = reader(budget=budget)
            with patch('modules.storage.fixed_objects.fetch', side_effect=downloaded):
                self.assert_code('resource_limit', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
            self.assertEqual(instance.scope.output_bytes, 0)
        instance = reader(cache=VerifiedCache(0), budget={'object_requests': 1})
        with patch('modules.storage.fixed_objects.fetch', side_effect=downloaded):
            instance.read(instance.scope.binding, object_ref(), 0, 16)
            self.assert_code('resource_limit', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
        self.assertEqual(instance.scope.object_requests, 1)
        instance = reader()
        with patch('modules.storage.fixed_objects.fetch', return_value=b'short'):
            self.assert_code('corrupt_object', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))

    def test_retry_only_transient_original_scope_and_maximum_three(self):
        for failures in (1, 3):
            instance = reader()
            calls = []
            def attempt(*args):
                calls.append(1)
                args[0].request(16)
                if len(calls) <= failures:
                    raise ContractFailure('backend_unavailable', 'injected transient')
                args[0].received(16)
                return TINY
            with patch('modules.storage.fixed_objects.fetch', side_effect=attempt):
                if failures == 1:
                    self.assertEqual(instance.read(instance.scope.binding, object_ref(), 0, 16), TINY)
                else:
                    self.assert_code('backend_unavailable', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
            self.assertEqual(len(calls), min(3, failures + 1))
        for code in ('unauthorized', 'missing_object', 'corrupt_object'):
            instance = reader()
            with patch('modules.storage.fixed_objects.fetch', side_effect=ContractFailure(code, 'injected')) as fetch:
                self.assert_code(code, lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
            self.assertEqual(fetch.call_count, 1)

    def test_scope_clock_cancel_lock_and_memory_lifecycle(self):
        clock = [0.0, 1000]
        scope = ReadScope(binding(object_ref(), now_ms=1000), monotonic=lambda: clock[0], wall_ms=lambda: clock[1])
        clock[:] = [1.0, 3500]
        scope.check()
        self.assertEqual(scope.deadline, 1.5)
        clock[1] = 2000
        scope.check()
        self.assertEqual(scope.deadline, 1.5)
        clock[0] = 2
        self.assert_code('deadline', scope.check)
        clock[:] = [0, 999]
        self.assert_code('expired_context', scope.check)
        scope = ReadScope(binding(object_ref()), cancelled=lambda: True)
        self.assert_code('cancelled', scope.check)
        instance = reader()
        instance.scope._lock.acquire()
        try:
            self.assert_code('resource_limit', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
        finally:
            instance.scope._lock.release()
        with instance.scope.reserve(100) as memory:
            memory.keep(20)
        self.assertEqual(instance.scope.memory_current, 20)
        with self.assertRaises(RuntimeError):
            with instance.scope.reserve(100):
                raise RuntimeError('abort')
        self.assertEqual(instance.scope.memory_current, 20)
        self.assert_code('invalid_contract', lambda: instance.scope.reserve(-1))
        with instance.scope.reserve(10) as memory:
            self.assert_code('invalid_contract', lambda: memory.keep(11))
        for _ in range(130):
            instance.scope.event('observed')
        self.assertEqual(len(instance.scope.trace), 128)
        self.assertEqual(instance.scope.trace_dropped, 2)
        self.assertEqual(instance.scope.usage()['memory_bytes'], 120)
        async def active_loop():
            self.assert_code('unsupported_capability', lambda: instance.read(instance.scope.binding, object_ref(), 0, 16))
        asyncio.run(active_loop())

    def test_cache_cost_eviction_replacement_and_clear(self):
        cache = VerifiedCache(2100)
        cache.put(('a',), b'a' * 16)
        cache.put(('a',), b'b' * 16)
        cache.put(('b',), b'c' * 16)
        self.assertEqual(cache.get(('a',)), b'b' * 16)
        cache.put(('c',), b'd' * 16)
        self.assertIsNone(cache.get(('b',)))
        self.assertEqual(cache.evictions, 1)
        cache.put(('oversized',), b'x' * 4096)
        self.assertLessEqual(cache.size, cache.capacity)
        self.assert_code('invalid_contract', lambda: cache.put(('bad',), bytearray(b'x')))
        self.assert_code('invalid_contract', lambda: VerifiedCache(-1))
        cache.clear()
        self.assertEqual(cache.size, 0)

    def test_proof_registration_limits_and_unsupported_block_width(self):
        self.assert_code('resource_limit', lambda: ProofAuthority({'x' + str(i): {} for i in range(129)}))
        self.assert_code('invalid_contract', lambda: ProofAuthority({'bad': object_ref()}))
        ref = object_ref(block_size=65537)
        authority = ProofAuthority({ref['integrity']['proof_ref']: ref})
        self.assert_code('unsupported_capability', lambda: authority.verify(ref))

    def test_caller_ref_mutation_by_authorization_cannot_change_fixed_snapshot(self):
        for field in ('key', 'version', 'sha256', 'block_sha256'):
            with self.subTest(field=field):
                ref = object_ref(block_size=4 if field == 'block_sha256' else 0)
                original = deepcopy(ref)
                authority = ProofAuthority({ref['integrity']['proof_ref']: ref}) if field == 'block_sha256' else None
                def authorize(_):
                    if field == 'block_sha256':
                        ref['integrity']['block_sha256'][:] = ['0' * 64] * 4
                    else:
                        ref[field] = '0' * 64 if field == 'sha256' else 'changed-by-callback'
                    return 1
                instance = reader(ref, proofs=authority, reauthorize=authorize)
                def receive(scope, backend, snapshot, offset, length):
                    self.assertEqual(snapshot, original)
                    self.assertIsNot(snapshot, ref)
                    return downloaded(scope, backend, snapshot, offset, length)
                with patch('modules.storage.fixed_objects.fetch', side_effect=receive):
                    self.assertEqual(instance.read(instance.scope.binding, ref, 0, 16), TINY)
                self.assertNotEqual(ref, original)
                self.assertEqual(instance.cache.get(instance.cache.key(original, 0, 16)), TINY)

    def test_mutating_ref_to_match_bad_transport_body_never_poisons_old_cache_key(self):
        for block in (False, True):
            ref = object_ref(block_size=4 if block else 0)
            original = deepcopy(ref)
            authority = ProofAuthority({ref['integrity']['proof_ref']: ref}) if block else None
            instance = reader(ref, proofs=authority)
            def poison(scope, backend, snapshot, offset, length):
                bad = b'bad!' * 4
                ref.update(key='changed', version='changed', sha256=sha(bad))
                if block:
                    ref['integrity']['block_sha256'][:] = [sha(b'bad!')] * 4
                self.assertEqual(snapshot, original)
                scope.request(length)
                scope.received(length)
                return bad
            with patch('modules.storage.fixed_objects.fetch', side_effect=poison):
                self.assert_code('corrupt_object', lambda: instance.read(instance.scope.binding, ref, 0, 16))
            self.assertEqual(instance.scope.output_bytes, 0)
            self.assertIsNone(instance.cache.get(instance.cache.key(original, 0, 16)))
            ref.clear()
            ref.update(deepcopy(original))
            with patch('modules.storage.fixed_objects.fetch', side_effect=downloaded):
                self.assertEqual(instance.read(instance.scope.binding, ref, 0, 16), TINY)

    def test_explicit_single_backend_cache_limit_and_warm_credential_expiry(self):
        original = reader()
        backend = FixedBackend('local_s3', 'm0-data', 'http://127.0.0.1:1',
                               CredentialSnapshot('test-key', 'test-secret'), True)
        for backends in ({}, [], {'other': backend}, {'local_s3': object()},
                         {'local_s3': backend, 'second': backend}):
            self.assert_code('unsupported_capability', lambda: FixedObjects(original.scope, backends, lambda _: 1))
        self.assert_code('unsupported_capability', lambda: reader(cache=VerifiedCache((256 << 10) + 1)))
        self.assert_code('unsupported_capability', lambda: reader(cache=object()))
        for invalid in ({'bad': object()}, {'bad': float('nan')}, object_ref(key='\ud800')):
            self.assert_code('invalid_contract', lambda: original.read(original.scope.binding, invalid, 0, 16))
        with patch('modules.storage.fixed_objects.fetch', side_effect=downloaded):
            original.read(original.scope.binding, object_ref(), 0, 16)
        for expiry in (original.scope.context['bound_at_unix_ms'] - 1,
                       original.scope.context['deadline_unix_ms'] - 1):
            expired_backend = FixedBackend('local_s3', 'm0-data', 'http://127.0.0.1:1',
                CredentialSnapshot('test-key', 'test-secret', expires_unix_ms=expiry), True)
            warm = FixedObjects(original.scope, {'local_s3': expired_backend}, lambda _: 1, cache=original.cache)
            with patch('modules.storage.fixed_objects.fetch') as fetch:
                self.assert_code('unauthorized', lambda: warm.read(warm.scope.binding, object_ref(), 0, 16))
                fetch.assert_not_called()
        self.assertEqual(original.scope.output_bytes, 16)
        self.assertEqual(original.scope.object_requests, 1)

    def test_fixture_failure_artifact_omits_malicious_sdk_fields(self):
        root = Path(__file__).resolve().parents[2]
        with patch.object(sys, 'path', [str(root/'scripts'), *sys.path]):
            from scripts import fixed_objects_acceptance as driver
        canary = 'P03-DIAGNOSTIC-SECRET-CANARY'
        for code, status, expected_code, expected_status in (
                ('InvalidArgument', 400, 'InvalidArgument', 400),
                ('https://secret.invalid/' + canary, canary, 'unknown', None),
                ('A' * 65, True, 'unknown', None)):
            response = {'Error': {'Code': code, 'Message': canary, 'Resource': canary},
                        'ResponseMetadata': {'HTTPStatusCode': status, 'HTTPHeaders': {'secret': canary}},
                        'credentials': canary}
            error = FixturePutFailure('repeated-separator', ClientError(response, canary))
            with tempfile.TemporaryDirectory(dir=root/'artifacts') as temporary:
                directory = Path(temporary)/'run'
                output = io.StringIO()
                with patch.object(sys, 'argv', ['fixed_objects_acceptance.py', '--suite', 'functional',
                                               '--run-dir', str(directory)]), \
                        patch.object(driver, 'identity', return_value={'fixed': 'test'}), \
                        patch.object(driver, 'laboratory'), \
                        patch.object(driver, 'real_backend', side_effect=error), redirect_stdout(output):
                    self.assertEqual(driver.main(), 1)
                raw = (directory/'failure.json').read_text()
                self.assertNotIn(canary, raw + output.getvalue())
                self.assertEqual(json.loads(raw)['fixture'], {'case_id': 'repeated-separator',
                    'stage': 'fixture_put', 'backend_error_code': expected_code, 'http_status': expected_status})

    def test_literal_dot_segments_reject_before_fetch_or_warm_cache_output(self):
        for key in ('.', '..', 'a/./b', 'a/../b'):
            with self.subTest(key=key):
                ref = object_ref(key=key, version='negative-only-no-backend-version')
                cache = VerifiedCache()
                cache.put(cache.key(ref, 0, 16), TINY)
                instance = reader(ref, cache=cache)
                with patch('modules.storage.fixed_objects.fetch') as fetch, \
                        patch.object(cache, 'get', wraps=cache.get) as hit:
                    self.assert_code('unsupported_capability', lambda: instance.read(instance.scope.binding, ref, 0, 16))
                    fetch.assert_not_called()
                    hit.assert_not_called()
                self.assert_code('unsupported_capability', lambda: instance._backend.request(ref, 0, 16, 1000))
                self.assertEqual(instance.scope.object_requests, 0)
                self.assertEqual(instance.scope.output_bytes, 0)
        for key in ('a/%2E/b', 'a/%2e%2e/b', '中文/%/+//b'):
            ref = object_ref(key=key)
            instance = reader(ref)
            with patch('modules.storage.fixed_objects.fetch', side_effect=downloaded):
                self.assertEqual(instance.read(instance.scope.binding, ref, 0, 16), TINY)

    def test_numeric_scope_snapshot_excludes_secrets_and_retains_truncated_close(self):
        canary = 'P03-SNAPSHOT-SECRET-CANARY'
        clock = [100.0, 1000]
        scope = ReadScope(binding(object_ref(key='api_key=' + canary), now_ms=1000),
                          monotonic=lambda: clock[0], wall_ms=lambda: clock[1])
        scope.private_credential_canary = canary
        scope.context['untrusted_diagnostic_text'] = canary
        clock[0] = 100.001
        scope.received(3, header=True)
        clock[0] = 100.002
        scope.received(2)
        last_header = scope.last_header_positive_receive_elapsed_us
        last_body = scope.last_body_positive_receive_elapsed_us
        clock[0] = 100.003
        scope.received(0, header=True)
        scope.received(0)
        for _ in range(130):
            scope.event('fixed_observation')
        clock[0] = 100.004
        scope.event('socket_closed')
        original_deadline = scope.deadline
        clock[:] = [100.005, 1500]
        scope.check()
        clock[0] = 100.007
        measured = scope_snapshot(scope, 100.006)
        self.assertNotIn(canary, json.dumps(measured))
        self.assertTrue(all(type(value) in (int, float) or value is None for value in measured.values()))
        self.assertEqual(measured['received_wire_bytes'], 5)
        self.assertEqual(measured['received_header_bytes'], 3)
        self.assertEqual(measured['received_body_bytes'], 2)
        self.assertEqual(measured['last_header_positive_receive_elapsed_us'], last_header)
        self.assertEqual(measured['last_body_positive_receive_elapsed_us'], last_body)
        self.assertEqual(measured['trace_dropped'], 3)
        self.assertGreater(measured['last_socket_close_elapsed_us'], scope.trace[-1]['elapsed_us'])
        self.assertLess(measured['last_socket_close_elapsed_us'], measured['observed_return_elapsed_us'])
        self.assertLess(measured['deadline_monotonic_s'], original_deadline)
        self.assertEqual(measured['deadline_unix_ms'] - measured['bound_at_unix_ms'], measured['remaining_ttl_ms'])
