//! Ports specify obligations; values alone never authenticate a caller or proof.
use super::{Contract, ContractFailure, ObjectRef};

pub type PortResult<T> = std::result::Result<T, ContractFailure>;

/// bind atomically authorizes and pins. Reauthorize before every output/page.
/// Mutation methods durably enforce CAS, owner fencing and request idempotency.
/// Mutation target is an unbound ReadDescriptors value, with its whole payload
/// digest in the intent. Unknown outcomes reconcile before any new mutation.
/// release_pin checks owner or trusted cleanup identity and exact pin lease;
/// duplicate release is idempotent, stale lease never releases a newer grant.
pub trait CatalogReadPort {
    fn bind(&self, request: &Contract) -> PortResult<Contract>;
    fn reauthorize(&self, binding: &Contract) -> PortResult<u64>;
    fn register(
        &self,
        intent: &Contract,
        authorization: &Contract,
        target: &Contract,
    ) -> PortResult<Contract>;
    fn publish(
        &self,
        intent: &Contract,
        authorization: &Contract,
        target: &Contract,
    ) -> PortResult<Contract>;
    fn release_pin(&self, binding: &Contract) -> PortResult<()>;
    fn reconcile(&self, intent: &Contract, authorization: &Contract) -> PortResult<Contract>;
}

/// Verify proof authority AND binding to backend/bucket/key/version/size/block
/// table digest. Self-declared proof_ref is not trusted. Charge every attempt.
pub trait ObjectReadPort {
    fn verify_proof(&self, reference: &ObjectRef) -> PortResult<()>;
    fn read(
        &self,
        binding: &Contract,
        reference: &ObjectRef,
        offset: u64,
        length: u64,
    ) -> PortResult<Vec<u8>>;
}

/// No latest rebinding; every batch carries the fixed context digest.
pub trait SourceReadPort {
    fn read_batch(&self, binding: &Contract, ordinal: u64) -> PortResult<Contract>;
}

/// IndexQuery and CandidateBatch share the fixed context and explicit binary64
/// score encoding. Providers verify source/object membership; query backfill
/// checks actual record ID/version. Locator is only a hint, never identity.
/// Usage is per-batch delta; the coordinator owns cumulative request accounting.
pub trait ArtifactReadPort {
    fn candidates(&self, binding: &Contract, query: &Contract) -> PortResult<Contract>;
    fn read_artifact(&self, binding: &Contract, artifact_id: &str) -> PortResult<Vec<u8>>;
}

/// Fail closed at each output: obtaining a binding never caches authorization.
pub fn reauthorize_read(
    catalog: &dyn CatalogReadPort,
    binding: &Contract,
    now_unix_ms: u64,
) -> PortResult<()> {
    super::wire::require(binding.kind() == "read_binding", "expected read binding")?;
    let epoch = catalog.reauthorize(binding)?;
    super::read::validate_access(binding, now_unix_ms, epoch)
}

/// Idempotently release only this binding's exact pin lease. Catalog verifies
/// authenticated ownership or trusted cleanup identity, never a bearer claim.
pub fn release_bound_pin(catalog: &dyn CatalogReadPort, binding: &Contract) -> PortResult<()> {
    super::wire::require(binding.kind() == "read_binding", "expected read binding")?;
    catalog.release_pin(binding)
}
