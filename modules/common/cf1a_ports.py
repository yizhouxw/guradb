"""Dependency-inverted CF1-A ports. Implementations must fail closed.

Callable bundles avoid importing any catalog, source, index or cloud client.
Contracts express obligations; these fields are not trusted authorization proofs.
"""
from dataclasses import dataclass
from typing import Callable
from modules.common.cf1a_wire import Contract
from modules.common.cf1a_primitives import require
from modules.common.cf1a_read import validate_access


@dataclass(frozen=True)
class CatalogReadPort:
    """bind atomically authorizes/pins; each output reauthorizes current epoch.

    register/publish take immutable ReadDescriptors plus intent and MutationAuth,
    implement durable CAS+fence+idempotency; on unknown results
    reconcile the same intent before retrying. Pin is never authorization.
    release_pin targets the exact pin lease; catalog checks authenticated owner
    or trusted cleanup identity, including after read authorization expiry.
    """
    bind: Callable[[Contract], Contract]
    reauthorize: Callable[[Contract], int]
    register: Callable[[Contract, Contract, Contract], Contract]
    publish: Callable[[Contract, Contract, Contract], Contract]
    release_pin: Callable[[Contract], None]
    reconcile: Callable[[Contract, Contract], Contract]


@dataclass(frozen=True)
class ObjectReadPort:
    """Verify proof against backend/bucket/key/version/size/block table digest.

    A proof_ref is untrusted until verified by storage's trusted authority.
    Whole-hash partial reads are rejected; charge all attempts to the budget.
    """
    verify_proof: Callable[[dict], None]
    read: Callable[[Contract, dict, int, int], bytes]


@dataclass(frozen=True)
class SourceReadPort:
    """No latest rebinding; batches bind to one validated context digest."""
    read_batch: Callable[[Contract, int], Contract]


@dataclass(frozen=True)
class ArtifactReadPort:
    """A consumes fixed artifacts; CandidateBatch freezes finite binary64 scores, ID/version and locator.

    No undeclared floating score encoding or independent context is permitted.
    """
    candidates: Callable[[Contract, Contract], Contract]
    read_artifact: Callable[[Contract, str], bytes]


def reauthorize_read(catalog, binding, now_unix_ms):
    require(binding.kind == 'read_binding', 'expected read binding')
    epoch = catalog.reauthorize(binding)
    validate_access(binding.value, now_unix_ms, epoch)


def release_bound_pin(catalog, binding):
    require(binding.kind == 'read_binding', 'expected read binding')
    catalog.release_pin(binding)
