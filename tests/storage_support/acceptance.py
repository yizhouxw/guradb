"""Real backend and independently injected faults; never production truth code."""
import resource
import re
import sys
import threading
import time
import uuid

from botocore.exceptions import ClientError

from modules.common.cf1a_primitives import ContractFailure
from modules.storage.fixed_cache import VerifiedCache
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_proofs import ProofAuthority
from modules.storage.fixed_scope import ReadScope
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
from tests.storage_support.fault_server import FaultServer, Response
from tests.storage_support.fixtures import TINY, binding, object_ref, payload
from tests.storage_support.recording_proxy import RecordingProxy


class FixturePutFailure(Exception):
    """Keep only bounded diagnostics; never retain an SDK response or message."""
    def __init__(self, case_id, error):
        super().__init__('fixture PUT failed')
        cases = {'space', 'unicode-percent-plus', 'repeated-separator', 'dot-segment'}
        self.case_id = case_id if case_id in cases else 'unknown'
        response = error.response if type(error.response) is dict else {}
        detail = response.get('Error', {})
        metadata = response.get('ResponseMetadata', {})
        code = detail.get('Code') if type(detail) is dict else None
        status = metadata.get('HTTPStatusCode') if type(metadata) is dict else None
        self.backend_code = code if type(code) is str and re.fullmatch(r'[A-Za-z0-9]{1,64}', code) else 'unknown'
        self.backend_status = status if type(status) is int and 100 <= status <= 599 else None

    def diagnostics(self):
        return {'case_id': self.case_id, 'stage': 'fixture_put',
                'backend_error_code': self.backend_code, 'http_status': self.backend_status}


def special_fixture_put(client, case_id, key):
    """Return a fixed version or the one certified negative-only PUT outcome."""
    try:
        version = client.put_object(Bucket='m0-data', Key=key, Body=TINY).get('VersionId')
    except ClientError as error:
        failure = FixturePutFailure(case_id, error)
        if not (case_id == 'dot-segment' and failure.backend_code == 'SignatureDoesNotMatch'
                and failure.backend_status == 403):
            raise failure from None
        return failure
    assert case_id != 'dot-segment', 'uncertified dot-segment PUT unexpectedly succeeded'
    assert version and version != 'null'
    return version


def rss_bytes():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == 'darwin' else peak * 1024


def instance(endpoint, ref, *, cache=None, cancelled=lambda: False, timeout=30000,
             credentials=None, authorize=lambda _: 1, budget=None):
    scope = ReadScope(binding(ref, timeout_ms=timeout, budget=budget), cancelled)
    backend = FixedBackend('local_s3', 'm0-data', endpoint,
                           credentials or CredentialSnapshot('m0-test-key', 'm0-test-secret'), True)
    authority = ProofAuthority({ref['integrity']['proof_ref']: ref}) if ref['integrity']['block_size'] else None
    return FixedObjects(scope, {'local_s3': backend}, authorize, cache=cache, proofs=authority)


def expect(code, operation):
    try:
        operation()
    except ContractFailure as error:
        assert error.code == code, (error.code, code)
        return
    raise AssertionError('fixed read unexpectedly returned success')


def scope_snapshot(scope, observed_return_monotonic):
    """Only fixed numeric fields; no binding, key, credentials, headers or errors."""
    assert scope.wire_bytes == scope.header_bytes + scope.object_bytes
    now = scope.monotonic()
    assert scope.started <= observed_return_monotonic <= now
    return {'bound_at_unix_ms': scope.context['bound_at_unix_ms'],
            'deadline_unix_ms': scope.context['deadline_unix_ms'],
            'remaining_ttl_ms': scope.context['remaining_ttl_ms'],
            'started_monotonic_s': scope.started, 'deadline_monotonic_s': scope.deadline,
            'original_ttl_upper_monotonic_s': scope.started + scope.context['remaining_ttl_ms'] / 1000,
            'snapshot_monotonic_s': now,
            'remaining_deadline_ms_at_snapshot': max(0, (scope.deadline - now) * 1000),
            'received_header_bytes': scope.header_bytes, 'received_body_bytes': scope.object_bytes,
            'received_wire_bytes': scope.wire_bytes, 'verified_bytes': scope.verified_bytes,
            'memory_current_bytes': scope.memory_current, 'memory_peak_bytes': scope.memory_peak,
            'trace_dropped': scope.trace_dropped,
            'last_header_positive_receive_elapsed_us': scope.last_header_positive_receive_elapsed_us,
            'last_body_positive_receive_elapsed_us': scope.last_body_positive_receive_elapsed_us,
            'last_socket_close_elapsed_us': scope.last_socket_close_elapsed_us,
            'observed_return_elapsed_us': max(0, int((observed_return_monotonic - scope.started) * 1_000_000))}


def real_backend(lab, suite):
    lab.s3()
    client = lab.client
    client.put_bucket_versioning(Bucket='m0-data', VersioningConfiguration={'Status': 'Enabled'})
    assert client.get_bucket_versioning(Bucket='m0-data').get('Status') == 'Enabled'
    prefix = 'p03-' + uuid.uuid4().hex
    large = payload()
    versions = {}
    for name, data in (('tiny', TINY), ('large', large)):
        key = prefix + '/' + name
        first = client.put_object(Bucket='m0-data', Key=key, Body=data).get('VersionId')
        second = client.put_object(Bucket='m0-data', Key=key, Body=b'overwritten') .get('VersionId')
        assert first and second and first != second and first != 'null' and second != 'null'
        versions[name] = (key, first)
    with RecordingProxy(client.meta.endpoint_url) as proxy:
        if suite == 'functional':
            return functional(proxy, client, versions, large, prefix)
        return performance(proxy, versions, large)


def functional(proxy, client, versions, large, prefix):
    results = []
    for name, data in (('tiny', TINY), ('large', large)):
        key, version = versions[name]
        ref = object_ref(data, key=key, version=version)
        reader = instance(proxy.endpoint, ref)
        before = proxy.requests
        assert reader.read(reader.scope.binding, ref, 0, len(data)) == data
        returned = time.monotonic()
        assert reader.scope.object_bytes == len(data)
        assert proxy.requests - before == 1
        assert proxy.wait_idle()
        results.append({'case': name + '-old-whole', 'usage': reader.scope.usage(),
                        'scope_io': scope_snapshot(reader.scope, returned)})
        width = 4 if name == 'tiny' else 65536
        ref = object_ref(data, key=key, version=version, block_size=width)
        reader = instance(proxy.endpoint, ref)
        ranges = [(width, width), (0, width * 2), (len(data) - (len(data) % width or width), len(data) % width or width)]
        for offset, length in ranges:
            assert reader.read(reader.scope.binding, ref, offset, length) == data[offset:offset + length]
        returned = time.monotonic()
        results.append({'case': name + '-aligned-ranges', 'usage': reader.scope.usage(),
                        'scope_io': scope_snapshot(reader.scope, returned)})
    ref = object_ref(TINY, key=versions['tiny'][0], version=versions['tiny'][1])
    denied = instance(proxy.endpoint, ref, authorize=lambda _: 2)
    before = proxy.requests
    expect('revoked', lambda: denied.read(denied.scope.binding, ref, 0, 16))
    returned = time.monotonic()
    assert proxy.requests == before
    results.append({'case': 'catalog-revoked', 'usage': denied.scope.usage(),
                    'scope_io': scope_snapshot(denied.scope, returned)})
    for case_id, credentials in (('invalid-access-key', CredentialSnapshot('wrong-key', 'm0-test-secret')),
                                ('invalid-secret-key', CredentialSnapshot('m0-test-key', 'wrong-secret'))):
        denied = instance(proxy.endpoint, ref, credentials=credentials)
        expect('unauthorized', lambda: denied.read(denied.scope.binding, ref, 0, 16))
        returned = time.monotonic()
        results.append({'case': case_id, 'usage': denied.scope.usage(),
                        'scope_io': scope_snapshot(denied.scope, returned)})
    for case_id, key_suffix in (('space', 'with space'), ('unicode-percent-plus', '资料%+'),
                                ('repeated-separator', 'repeated//path'), ('dot-segment', 'dot/../path')):
        key = prefix + '/' + key_suffix
        outcome = special_fixture_put(client, case_id, key)
        if isinstance(outcome, FixturePutFailure):
            # This placeholder is exclusively a local rejection input, never an S3 version claim.
            negative = object_ref(TINY, key=key, version='negative-only-no-backend-version')
            rejected = instance(proxy.endpoint, negative)
            before = proxy.requests
            expect('unsupported_capability', lambda: rejected.read(rejected.scope.binding, negative, 0, 16))
            returned = time.monotonic()
            assert proxy.requests == before and rejected.scope.object_requests == 0
            assert rejected.scope.output_bytes == 0
            results.append({'case': 'dot-segment-backend-put-rejected', 'fixture': outcome.diagnostics(),
                            'module_input': 'negative-only; not a backend version',
                            'actual_gets': 0, 'usage': rejected.scope.usage(),
                            'scope_io': scope_snapshot(rejected.scope, returned)})
            continue
        version = outcome
        encoded_ref = object_ref(TINY, key=key, version=version)
        reader = instance(proxy.endpoint, encoded_ref)
        assert reader.read(reader.scope.binding, encoded_ref, 0, 16) == TINY
        returned = time.monotonic()
        results.append({'case': case_id + '-fixed-get', 'usage': reader.scope.usage(),
                        'scope_io': scope_snapshot(reader.scope, returned)})
    client.delete_object(Bucket='m0-data', Key=ref['key'], VersionId=ref['version'])
    missing = instance(proxy.endpoint, ref)
    expect('missing_object', lambda: missing.read(missing.scope.binding, ref, 0, 16))
    returned = time.monotonic()
    assert proxy.wait_idle()
    results.append({'case': 'fixed-version-missing', 'usage': missing.scope.usage(),
                    'scope_io': scope_snapshot(missing.scope, returned)})
    return {'passed': True, 'scope': 'P03 module-only real Seaweed fixed reads; local auth callback',
            'samples': results, 'backend': proxy.snapshot(), 'missing': ['PG/P04/I1', 'TLS/real cloud/multihost', 'STS credential refresh']}


def performance(proxy, versions, large):
    key, version = versions['large']
    ref = object_ref(large, key=key, version=version, block_size=65536)
    cache = VerifiedCache(256 << 10)
    full = [(start, min(65536, len(large) - start)) for start in range(0, len(large), 65536)]
    fit = full[:3]
    samples = []
    for mode, ranges in (('cold-fit', fit), ('warm-fit', fit), ('over-cache-full', full), ('over-cache-repeat', full)):
        reader = instance(proxy.endpoint, ref, cache=cache, budget={'object_requests': 128})
        before = proxy.snapshot()
        start = time.monotonic()
        for offset, length in ranges:
            assert reader.read(reader.scope.binding, ref, offset, length) == large[offset:offset + length]
        returned = time.monotonic()
        elapsed_ms = (returned - start) * 1000
        assert proxy.wait_idle()
        delta_gets = proxy.requests - before['requests']
        delta_body = proxy.sent_body - before['sent_body_bytes']
        assert delta_gets == reader.scope.object_requests
        assert delta_body == reader.scope.object_bytes
        assert reader.scope.verified_bytes == sum(length for _, length in ranges)
        assert reader.scope.output_bytes == sum(length for _, length in ranges)
        assert mode != 'warm-fit' or delta_gets == 0
        assert elapsed_ms <= 10000 and rss_bytes() <= 512 << 20
        samples.append({'mode': mode, 'ranges': len(ranges), 'logical_output': sum(length for _, length in ranges),
                        'latency_ms': elapsed_ms, 'rss_peak_bytes': rss_bytes(), 'actual_gets': delta_gets,
                        'usage': reader.scope.usage(), 'verified_bytes': reader.scope.verified_bytes,
                        'scope_io': scope_snapshot(reader.scope, returned),
                        'proxy_sent_header_bytes': proxy.sent_header - before['sent_header_bytes'],
                        'proxy_sent_body_bytes': delta_body})
    return {'passed': True, 'scope': 'P03 synthetic component costs, not a product baseline',
            'samples': samples, 'budgets': {'cohort_latency_ms': 10000, 'process_rss_bytes': 512 << 20,
                                           'cache_bytes': 256 << 10}, 'cache_evictions': cache.evictions}


def faults():
    large = payload()
    ref = object_ref(large)
    samples = []
    cases = [('header-stall', Response(body=large, header_delay=2)),
             ('header-dribble', Response(body=large, header_chunk=1, header_interval=.015)),
             ('body-stall', Response(body=large, body_delay=2)),
             ('body-dribble', Response(body=large, body_chunk=1, body_interval=.010)),
             ('missing-eof', Response(body=large, eof_delay=2))]
    for name, response in cases:
        with FaultServer([response]) as server:
            reader = instance(server.endpoint, ref, timeout=700)
            start = time.monotonic()
            expect('deadline', lambda: reader.read(reader.scope.binding, ref, 0, len(large)))
            returned = time.monotonic()
            assert server.wait_idle(.100)
            elapsed = (time.monotonic() - start) * 1000
            assert elapsed < 700
            assert reader.scope.output_bytes == 0
            samples.append({'case': name, 'elapsed_ms': elapsed, 'usage': reader.scope.usage(),
                            'injection': server.snapshot(), 'trace': reader.scope.trace,
                            'scope_io': scope_snapshot(reader.scope, returned)})
    for name, response in [('cancel-header', Response(body=large, header_delay=2)),
                           ('cancel-body', Response(body=large, body_delay=2)),
                           ('cancel-eof', Response(body=large, eof_delay=2))]:
        event = threading.Event()
        times = []
        with FaultServer([response]) as server:
            reader = instance(server.endpoint, ref, cancelled=event.is_set)
            def cancel():
                times.append(time.monotonic())
                event.set()
            timer = threading.Timer(.080, cancel)
            timer.start()
            try:
                expect('cancelled', lambda: reader.read(reader.scope.binding, ref, 0, len(large)))
                returned = time.monotonic()
            finally:
                timer.join()
            remaining = max(0, .100 - (time.monotonic() - times[0]))
            assert server.wait_idle(remaining)
            cleanup_ms = (time.monotonic() - times[0]) * 1000
            assert cleanup_ms <= 100
            assert reader.scope.output_bytes == 0 and server.requests == 1
            samples.append({'case': name, 'cancel_to_return_ms': cleanup_ms,
                            'usage': reader.scope.usage(), 'injection': server.snapshot(), 'trace': reader.scope.trace,
                            'scope_io': scope_snapshot(reader.scope, returned)})
    for response, code in [(Response(body=large, status=429), 'backend_unavailable'),
                           (Response(body=large, status=503), 'backend_unavailable'),
                           (Response(body=large, version='wrong'), 'corrupt_object'),
                           (Response(body=large[:-1], declared_length=len(large)), 'corrupt_object')]:
        with FaultServer([response]) as server:
            reader = instance(server.endpoint, ref)
            expect(code, lambda: reader.read(reader.scope.binding, ref, 0, len(large)))
            returned = time.monotonic()
            assert server.wait_idle()
            assert server.requests == (3 if code == 'backend_unavailable' else 1)
            samples.append({'case': code, 'usage': reader.scope.usage(), 'injection': server.snapshot(),
                            'scope_io': scope_snapshot(reader.scope, returned)})
    return {'passed': True, 'scope': 'P03 explicit local fault server; not Seaweed native fault semantics',
            'samples': samples, 'budgets': {'deadline_ms': 700, 'io_reserve_ms': 200, 'cancel_cleanup_ms': 100}}
