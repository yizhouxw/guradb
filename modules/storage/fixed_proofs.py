"""Private trusted block-table registration and independent byte verification."""
import hashlib

from modules.common.cf1a_primitives import canonical, require, validate_shape
from modules.common.cf1a_read import validate_object


class ProofAuthority:
    """Entries come from trusted registration, never from the read request itself."""
    def __init__(self, registered=None):
        require(registered is None or (type(registered) is dict and len(registered) <= 128),
                'trusted proof registration exceeds finite limit', 'resource_limit')
        self._registered = {}
        for name, ref in (registered or {}).items():
            validate_shape(ref, 'ObjectRef')
            validate_object(ref)
            require(ref['integrity']['mode'] == 'block_sha256' and
                    ref['integrity']['proof_ref'] == name, 'invalid trusted block registration')
            self._registered[name] = canonical(ref)
        self.memory_bytes = sum(len(name.encode()) + len(raw) + 1024
                                for name, raw in self._registered.items()) + 1024

    def verify(self, ref):
        validate_shape(ref, 'ObjectRef')
        validate_object(ref)
        integrity = ref['integrity']
        if integrity['mode'] == 'block_sha256':
            require(0 < integrity['block_size'] <= 65536, 'block width not certified', 'unsupported_capability')
            require(self._registered.get(integrity['proof_ref']) == canonical(ref),
                    'block proof is not trusted for this exact object', 'corrupt_object')


def verify_bytes(ref, offset, data, scope):
    """Count every checked byte, including a failed digest and cache hits."""
    integrity = ref['integrity']
    width = integrity['block_size'] if integrity['mode'] == 'block_sha256' else 65536
    whole = hashlib.sha256()
    view = memoryview(data)
    for start in range(0, len(data), width):
        scope.check()
        part = view[start:start + width]
        scope.verified_bytes += len(part)
        if integrity['mode'] == 'whole_sha256':
            whole.update(part)
        else:
            expected = integrity['block_sha256'][(offset + start) // width]
            require(hashlib.sha256(part).hexdigest() == expected, 'fixed block digest mismatch', 'corrupt_object')
    if integrity['mode'] == 'whole_sha256':
        require(whole.hexdigest() == ref['sha256'], 'fixed object digest mismatch', 'corrupt_object')
    scope.check()
