"""Trusted embedded identity and explicit local fixture protection authority.

Neither a wire authorization object nor a pin authenticates a caller. This
first component has no bearer verifier or real source/artifact certification.
"""
from dataclasses import dataclass
import threading

from modules.common.cf1a_primitives import digest, require, validate_shape


@dataclass(frozen=True)
class TrustedPrincipal:
    tenant_id: str
    subject_id: str
    delegation_ref: str
    administrator: bool = False
    cleanup: bool = False

    def __post_init__(self):
        for value in (self.tenant_id, self.subject_id, self.delegation_ref):
            validate_shape(value, 'id')
        require(type(self.administrator) is bool and type(self.cleanup) is bool, 'invalid trusted principal role')


class FixedInputAuthority:
    """An operator-owned, bounded fixture allowlist; no remote I/O or proof claim."""

    def __init__(self):
        self._approved = set()
        self._fixture_sha256 = {}
        self._lock = threading.Lock()

    def allow(self, target):
        require(target.kind == 'read_descriptors', 'expected complete protected target')
        key = digest(target.value)
        with self._lock:
            require(key in self._approved or len(self._approved) + len(self._fixture_sha256) < 256,
                    'fixture authority capacity reached', 'resource_limit')
            self._approved.add(key)

    def allow_fixture_target_sha256(self, canonical_sha256, protected_until_unix_ms):
        """Trusted operator imports one whole-Contract digest, never a PG lookup.

        This is the same bounded local fixture allowlist, not I1 certification.
        The inherited private config establishes trust; a request cannot add its
        own digest, replace a protection deadline or extend an existing entry.
        """
        require(type(canonical_sha256) is str and len(canonical_sha256) == 64
                and all(char in '0123456789abcdef' for char in canonical_sha256)
                and canonical_sha256 != '0' * 64, 'invalid fixture canonical digest')
        require(type(protected_until_unix_ms) is int and 0 < protected_until_unix_ms < 1 << 53,
                'invalid imported fixture protection deadline')
        with self._lock:
            old = self._fixture_sha256.get(canonical_sha256)
            require(old is None or old == protected_until_unix_ms,
                    'fixture digest deadline cannot change', 'conflict')
            require(old is not None or len(self._approved) + len(self._fixture_sha256) < 256,
                    'fixture authority capacity reached', 'resource_limit')
            self._fixture_sha256[canonical_sha256] = protected_until_unix_ms

    def withdraw(self, target):
        require(target.kind == 'read_descriptors', 'expected complete protected target')
        with self._lock:
            self._approved.discard(digest(target.value))
            self._fixture_sha256.pop(target.sha256, None)

    def verify(self, target, now_unix_ms, required_until_unix_ms):
        require(target.kind == 'read_descriptors', 'expected complete protected target')
        validate_shape(now_unix_ms, 'positive')
        validate_shape(required_until_unix_ms, 'positive')
        require(now_unix_ms <= required_until_unix_ms, 'invalid protection deadline')
        value = target.value
        with self._lock:
            if digest(value) not in self._approved:
                imported = self._fixture_sha256.get(target.sha256)
                require(imported is not None, 'fixed input protection revoked', 'revoked')
                require(required_until_unix_ms <= imported, 'imported fixture protection expired', 'expired_context')
            require(all(source['protected_until_unix_ms'] >= required_until_unix_ms
                        for source in value['revision']['sources']), 'fixed source protection expired', 'expired_context')
