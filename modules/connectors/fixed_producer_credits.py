"""Local trusted grant tokens and bounded producer suballocations.

These are not an IPC authentication mechanism or a native allocator meter.
The caller has already charged the grant once in its parent ledger.
"""
from dataclasses import dataclass
import threading
import uuid

from modules.common.cf1a_primitives import require


@dataclass(frozen=True)
class PreparedPermit:
    """Trusted composition attestation; this module does not validate SQL."""
    session: str
    binding_sha256: str
    generation: int


class ProducerGrant:
    def __init__(self, prepared, amount):
        require(type(prepared) is PreparedPermit and type(prepared.session) is str
                and 0 < len(prepared.session) <= 128
                and type(prepared.binding_sha256) is str
                and len(prepared.binding_sha256) == 64
                and type(prepared.generation) is int and 0 < prepared.generation < 1 << 53,
                'invalid trusted prepared permit')
        require(type(amount) is int and 0 < amount <= 8 << 20,
                'invalid producer grant', 'resource_limit')
        self.prepared, self.amount = prepared, amount
        self.identifier = uuid.uuid4().hex
        self._claimed = False
        self._owner = None
        self._closed = False
        self._leases = {}
        self._next = 0
        self._lock = threading.Lock()
        self.current = self.peak = 0

    def claim(self, binding_sha256, budget, *, owner=None):
        with self._lock:
            require(not self._claimed and not self._closed, 'grant already consumed', 'expired_context')
            self._claimed = True
            self._owner = object() if owner is None else owner
            require(binding_sha256 == self.prepared.binding_sha256,
                    'grant binding differs', 'unauthorized')
            require(self.amount <= budget, 'grant exceeds issued memory', 'resource_limit')

    def owned_by(self, owner):
        with self._lock:
            return self._claimed and self._owner is owner

    def reserve(self, size, *, kind='resident'):
        require(type(size) is int and size >= 0 and kind in ('resident', 'output', 'control'),
                'invalid producer suballocation')
        with self._lock:
            require(self._claimed and not self._closed, 'producer grant is inactive', 'expired_context')
            require(len(self._leases) < 1024, 'producer lease table full', 'resource_limit')
            require(size + 128 <= self.amount - self.current, 'producer credit exhausted', 'resource_limit')
            self._next += 1
            lease = ProducerLease(self, self._next, size, kind)
            self._leases[lease.identifier] = lease
            self.current += size + 128
            self.peak = max(self.peak, self.current)
            return lease

    def _shrink(self, lease, size):
        with self._lock:
            require(self._leases.get(lease.identifier) is lease and not lease.released
                    and type(size) is int and 0 <= size <= lease.size,
                    'invalid producer lease transition')
            self.current -= lease.size - size
            lease.size = size

    def _release(self, lease):
        with self._lock:
            require(type(lease) is ProducerLease and lease.grant is self,
                    'foreign producer lease', 'unauthorized')
            if lease.released:
                return False
            require(self._leases.get(lease.identifier) is lease,
                    'foreign producer lease', 'unauthorized')
            self.current -= lease.size + 128
            lease.released = True
            del self._leases[lease.identifier]
            return True

    def close_resident(self):
        """Caller first destroys resident references; output leases are independent."""
        with self._lock:
            self._closed = True
            resident = [lease for lease in self._leases.values() if lease.kind != 'output']
        for lease in resident:
            lease.release()

    def snapshot(self):
        with self._lock:
            return {'grant_id': self.identifier, 'live_bytes': self.current,
                    'peak_bytes': self.peak, 'live_leases': len(self._leases),
                    'closed': self._closed}


class ProducerLease:
    def __init__(self, grant, identifier, size, kind):
        self.grant, self.identifier = grant, identifier
        self.size, self.kind, self.released = size, kind, False

    def shrink(self, size):
        self.grant._shrink(self, size)
        return self

    def release(self):
        return self.grant._release(self)
