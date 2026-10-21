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
        self._lock = threading.Lock()

    def allow(self, target):
        require(target.kind == 'read_descriptors', 'expected complete protected target')
        key = digest(target.value)
        with self._lock:
            require(key in self._approved or len(self._approved) < 256, 'fixture authority capacity reached', 'resource_limit')
            self._approved.add(key)

    def withdraw(self, target):
        require(target.kind == 'read_descriptors', 'expected complete protected target')
        with self._lock:
            self._approved.discard(digest(target.value))

    def verify(self, target, now_unix_ms, required_until_unix_ms):
        require(target.kind == 'read_descriptors', 'expected complete protected target')
        validate_shape(now_unix_ms, 'positive')
        validate_shape(required_until_unix_ms, 'positive')
        require(now_unix_ms <= required_until_unix_ms, 'invalid protection deadline')
        value = target.value
        with self._lock:
            require(digest(value) in self._approved, 'fixed input protection revoked', 'revoked')
            require(all(source['protected_until_unix_ms'] >= required_until_unix_ms
                        for source in value['revision']['sources']), 'fixed source protection expired', 'expired_context')
