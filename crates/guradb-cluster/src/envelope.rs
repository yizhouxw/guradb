//! Borrowed context and cap comparisons; validation never allocates resources.
use guradb_common::cf1a::{Budget, QueryContext};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TaskIdentity {
    pub task_id: String,
    pub attempt_id: String,
    pub query_id: String,
    pub shard: u8,
}

#[derive(Debug)]
pub struct TaskSpec {
    pub identity: TaskIdentity,
    pub payload_sha256: String,
    pub child_cap: Budget,
}

#[derive(Debug)]
pub struct TaskEnvelope<'a> {
    identity: TaskIdentity,
    payload_sha256: String,
    parent: &'a QueryContext,
    child_cap: Budget,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EnvelopeError {
    Identity,
    Fingerprint,
    DuplicateTask,
    Shards,
    RemainingExceedsParent,
    ChildExceedsRemaining,
    AggregateExceedsRemaining,
    Overflow,
}

pub(crate) fn fingerprint(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

// Preserve the dimensions of the existing A Budget. This is no second ledger.
fn dimensions(value: &Budget) -> [u64; 9] {
    [
        value.memory_bytes,
        value.object_requests,
        value.object_bytes,
        value.candidates,
        value.top_k,
        value.graph_edges,
        value.output_bytes,
        value.concurrency,
        value.temp_bytes,
    ]
}

pub fn validate_envelopes<'a>(
    specs: [TaskSpec; 3],
    parent: &'a QueryContext,
    remaining: &Budget,
) -> Result<[TaskEnvelope<'a>; 3], EnvelopeError> {
    let available = dimensions(remaining);
    if available
        .iter()
        .zip(dimensions(&parent.budget))
        .any(|(left, right)| *left > right)
    {
        return Err(EnvelopeError::RemainingExceedsParent);
    }
    let mut shards = [false; 3];
    let mut total = [0_u64; 9];
    for (index, spec) in specs.iter().enumerate() {
        let identity = &spec.identity;
        if identity.task_id.is_empty()
            || identity.attempt_id.is_empty()
            || identity.query_id.is_empty()
            || identity.query_id != parent.query_id
        {
            return Err(EnvelopeError::Identity);
        }
        if !fingerprint(&spec.payload_sha256) {
            return Err(EnvelopeError::Fingerprint);
        }
        let shard = usize::from(identity.shard);
        if shard >= 3 || shards[shard] {
            return Err(EnvelopeError::Shards);
        }
        shards[shard] = true;
        if specs[..index]
            .iter()
            .any(|other| other.identity.task_id == identity.task_id)
        {
            return Err(EnvelopeError::DuplicateTask);
        }
        for (dimension, cap) in dimensions(&spec.child_cap).into_iter().enumerate() {
            if cap > available[dimension] {
                return Err(EnvelopeError::ChildExceedsRemaining);
            }
            total[dimension] = total[dimension]
                .checked_add(cap)
                .ok_or(EnvelopeError::Overflow)?;
        }
    }
    if total.iter().zip(available).any(|(sum, cap)| *sum > cap) {
        return Err(EnvelopeError::AggregateExceedsRemaining);
    }
    // One borrowed parent for the entire set rules out mixed parent references.
    Ok(specs.map(|spec| TaskEnvelope {
        identity: spec.identity,
        payload_sha256: spec.payload_sha256,
        parent,
        child_cap: spec.child_cap,
    }))
}

impl<'a> TaskEnvelope<'a> {
    pub fn identity(&self) -> &TaskIdentity {
        &self.identity
    }

    pub fn payload_sha256(&self) -> &str {
        &self.payload_sha256
    }

    pub fn parent(&self) -> &'a QueryContext {
        self.parent
    }

    pub fn child_cap(&self) -> &Budget {
        &self.child_cap
    }
}
