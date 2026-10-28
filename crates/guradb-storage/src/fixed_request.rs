//! Pure CF1-A request planning. A plan never grants access or authenticates proof.
use guradb_common::cf1a::{
    ports::PortResult, read::validate_range, Contract, ContractFailure, ObjectRef, Payload,
};

/// An owned structural snapshot, not an authorization or a verified byte buffer.
#[derive(Clone, Debug)]
pub struct FixedRequest {
    binding_sha256: String,
    reference: ObjectRef,
    offset: u64,
    length: u64,
}

impl FixedRequest {
    pub fn binding_sha256(&self) -> &str {
        &self.binding_sha256
    }

    pub fn reference(&self) -> &ObjectRef {
        &self.reference
    }

    pub fn offset(&self) -> u64 {
        self.offset
    }

    pub fn length(&self) -> u64 {
        self.length
    }
}

fn same_reference(left: &ObjectRef, right: &ObjectRef) -> bool {
    left.immutable_locator() == right.immutable_locator()
        && left.size_bytes == right.size_bytes
        && left.sha256 == right.sha256
        && left.integrity.mode == right.integrity.mode
        && left.integrity.block_size == right.integrity.block_size
        && left.integrity.block_sha256 == right.integrity.block_sha256
        && left.integrity.proof_ref == right.integrity.proof_ref
}

/// Validate a request against an already decoded binding, without doing I/O.
///
/// Common validates shape and range before storage checks its fixed-version
/// subset and complete descriptor membership. Even a matching proof_ref still
/// needs a trusted proof authority in a future provider. Current authorization,
/// cancellation, deadlines and cumulative accounting are deliberately absent.
pub fn plan_fixed_request(
    binding: &Contract,
    reference: &ObjectRef,
    offset: u64,
    length: u64,
) -> PortResult<FixedRequest> {
    let Payload::ReadBinding(value) = &binding.envelope().payload else {
        return Err(ContractFailure {
            code: "invalid_contract",
            message: "expected fixed read binding",
        });
    };
    validate_range(reference, offset, length)?;
    if matches!(reference.version.as_str(), "null" | "latest") {
        return Err(ContractFailure {
            code: "unsupported_capability",
            message: "request requires a fixed nonnull object version",
        });
    }
    let member = value
        .revision
        .sources
        .iter()
        .map(|source| &source.metadata)
        .chain(value.revision.objects.iter())
        .chain(value.indexes.iter().flat_map(|index| index.shards.iter()))
        .any(|candidate| same_reference(candidate, reference));
    if !member {
        return Err(ContractFailure {
            code: "unauthorized",
            message: "object reference is outside fixed binding",
        });
    }
    Ok(FixedRequest {
        binding_sha256: binding.sha256(),
        reference: reference.clone(),
        offset,
        length,
    })
}
