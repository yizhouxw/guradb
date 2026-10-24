"""CF1-A fixed object port. Module-only; trusted composition supplies authority."""
import json

from modules.common.cf1a_ports import ObjectReadPort
from modules.common.cf1a_primitives import ContractFailure, canonical, require, validate_shape
from modules.common.cf1a_read import validate_access, validate_range
from modules.storage.fixed_cache import VerifiedCache
from modules.storage.fixed_proofs import ProofAuthority, verify_bytes
from modules.storage.fixed_signing import FixedBackend, validate_key
from modules.storage.fixed_transport import fetch

MAX_OBJECT_BYTES = 8 << 20
TRANSIENT_FIXED_BYTES = 128 << 10


class FixedObjects:
    """One caller-owned cumulative scope; no catalog or cloud SDK leaks upward."""
    def __init__(self, scope, backends, reauthorize, *, proofs=None, cache=None):
        require(type(backends) is dict and len(backends) == 1,
                'exactly one explicit backend is certified', 'unsupported_capability')
        name, backend = next(iter(backends.items()))
        require(type(backend) is FixedBackend and name == backend.backend_id,
                'backend key must match an explicit fixed configuration', 'unsupported_capability')
        self.scope = scope
        self._backend = backend
        self.reauthorize = reauthorize
        self.proofs = proofs if proofs is not None else ProofAuthority()
        self.cache = cache if cache is not None else VerifiedCache()
        require(type(self.cache) is VerifiedCache and self.cache.capacity <= 256 << 10,
                'cache configuration exceeds certified scope', 'unsupported_capability')
        binding = scope.binding.value
        refs = [source['metadata'] for source in binding['revision']['sources']]
        refs += binding['revision']['objects']
        refs += [ref for index in binding['indexes'] for ref in index['shards']]
        self._members = {canonical(ref) for ref in refs}
        self._binding = binding
        # Charge resident descriptor/proof/cache capacity during every operation.
        self._resident = (len(scope.binding.encoded) * 32 + sum(len(ref) for ref in self._members) * 4
                          + self.proofs.memory_bytes * 4 + self.cache.capacity + 16384)
        self.port = ObjectReadPort(verify_proof=self.proofs.verify, read=self.read)

    def _authorize(self):
        self.scope.check()
        try:
            epoch = self.reauthorize(self.scope.binding)
        except ContractFailure:
            raise
        except Exception:
            raise ContractFailure('unauthorized', 'current authorization unavailable') from None
        validate_access(self._binding, self.scope.wall_ms(), epoch)
        self.scope.check()

    def read(self, binding, ref, offset, length):
        scope = self.scope
        with scope.operation():
            require(binding.encoded == scope.binding.encoded, 'fixed read scope binding mismatch')
            validate_shape(ref, 'ObjectRef')
            try:
                encoded_ref = canonical(ref)
                ref = json.loads(encoded_ref)
            except (TypeError, ValueError):
                raise ContractFailure('invalid_contract', 'invalid object reference encoding') from None
            validate_range(ref, offset, length)
            require(encoded_ref in self._members, 'object is outside authorized binding', 'unauthorized')
            validate_key(ref['key'])
            require(ref['size_bytes'] <= MAX_OBJECT_BYTES, 'object size exceeds certified limit', 'resource_limit')
            backend = self._backend
            require(ref['backend_id'] == backend.backend_id, 'object backend is not configured', 'unsupported_capability')
            require(backend.versioning_certified and ref['bucket'] == backend.bucket and ref['version'] != 'null',
                    'immutable backend version is not certified', 'unsupported_capability')
            self._authorize()
            # Cache hits obey the same declared credential-expiry contract as GETs.
            backend.credentials.frozen(scope.context['deadline_unix_ms'])
            scope.output(length)
            # Includes transient body/bytes conversion and retained earlier outputs.
            with scope.reserve(self._resident + TRANSIENT_FIXED_BYTES + 2 * length) as memory:
                self.proofs.verify(ref)
                key = self.cache.key(ref, offset, length)
                data = self.cache.get(key)
                if data is None:
                    data = self._download(backend, ref, offset, length)
                else:
                    scope.event('cache_hit')
                require(len(data) == length, 'cached or backend length mismatch', 'corrupt_object')
                verify_bytes(ref, offset, data, scope)
                self._authorize()
                self.cache.put(key, data)
                scope.delivered(length)
                memory.keep(length + 64)
                return data

    def _download(self, backend, ref, offset, length):
        remaining = 3
        while True:
            remaining -= 1
            self._authorize()
            try:
                return fetch(self.scope, backend, ref, offset, length)
            except ContractFailure as error:
                self.scope.event('attempt_failed')
                self.scope.check()
                if error.code != 'backend_unavailable' or remaining == 0:
                    raise
                self.scope.event('retry')
