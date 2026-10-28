//! RC-B/A/F/R value contracts. Providers authenticate and persist effects.
use super::read_control::*;
use super::{Budget, Contract, Payload};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExactLease {
    pub pin_id: Id,
    pub lease_id: Id,
    pub read_view_id: Id,
    pub data_revision_id: Id,
    pub binding_sha256: Sha256,
}
#[derive(Clone, Debug)]
pub struct BoundRead { pub read_binding: Contract, pub key: ReadRequestKey }
impl BoundRead {
    pub fn new(read_binding: Contract, key: ReadRequestKey) -> ControlResult<Self> {
        let value = Self { read_binding, key };
        value.exact_lease()?;
        Ok(value)
    }
    pub fn exact_lease(&self) -> ControlResult<ExactLease> {
        let value = match &self.read_binding.envelope().payload {
            Payload::ReadBinding(value) => value,
            _ => return Err(ReadFailure::invalid()),
        };
        let c = &value.context;
        let p = &self.key.principal;
        if c.tenant_id != self.key.tenant_id.as_str() || c.dataset_id != self.key.dataset_id.as_str()
            || c.query_id != self.key.query_id.as_str() || c.request_id != self.key.request_id.as_str()
            || c.auth.tenant_id != p.tenant_id.as_str() || c.auth.subject_id != p.subject_id.as_str()
            || c.auth.delegation_ref != p.delegation_ref.as_str() {
            return Err(ReadFailure::new(ErrorCode::Conflict, ReadPhase::Validate));
        }
        Ok(ExactLease { pin_id: Id::new(c.pin.pin_id.clone())?, lease_id: Id::new(c.pin.lease_id.clone())?,
            read_view_id: Id::new(c.read_view_id.clone())?, data_revision_id: Id::new(c.data_revision_id.clone())?,
            binding_sha256: Sha256::of(self.read_binding.encoded()) })
    }
    pub fn require_lease(&self, key: &ReadRequestKey, lease: &ExactLease) -> ControlResult<()> {
        self.key.require_same(key)?;
        if self.exact_lease()? == *lease { Ok(()) }
        else { Err(ReadFailure::new(ErrorCode::Conflict, ReadPhase::Validate)) }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CustodyState { Reserved, Active, ReconcilePending, Closed }
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CustodyTicket { pub key: ReadRequestKey, pub record_version: u64, pub state: CustodyState }
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CleanupState {
    NotRequired, Bound(ExactLease), ReleasedConfirmed(ExactLease), NotBoundConfirmed, CleanupUnconfirmed,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RequestState { NotAttempted, InFlight, Settled, OutcomeUnknown }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LocalIoState { NotStarted, Active, Stopped, Unconfirmed }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PgAttemptState { NotStarted, Active, StoppedConfirmed, Unconfirmed }
/// Merely a reference to external proof; common does not verify its authority.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PgStopProof {
    pub session_id: Id,
    pub backend_pid: u64,
    pub backend_start_unix_ms: u64,
    pub transaction_id: Id,
    pub proof_ref: Id,
    pub no_queued_work: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StopEvidence {
    pub local_io: LocalIoState,
    pub pg_attempt: PgAttemptState,
    pub pg_proof: Option<PgStopProof>,
}
impl StopEvidence {
    pub fn not_started() -> Self {
        Self { local_io: LocalIoState::NotStarted, pg_attempt: PgAttemptState::NotStarted, pg_proof: None }
    }
    pub fn validate(&self) -> ControlResult<()> {
        if self.pg_attempt == PgAttemptState::StoppedConfirmed {
            let proof = self.pg_proof.as_ref().ok_or_else(ReadFailure::invalid)?;
            if proof.backend_pid == 0 || proof.backend_start_unix_ms == 0 || !proof.no_queued_work {
                return Err(ReadFailure::invalid());
            }
        }
        Ok(())
    }
    pub fn is_settled(&self) -> bool {
        matches!(self.local_io, LocalIoState::NotStarted | LocalIoState::Stopped)
            && matches!(self.pg_attempt, PgAttemptState::NotStarted | PgAttemptState::StoppedConfirmed)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KnownUsage {
    pub pg_connect_attempts: u64,
    pub pg_sql_attempts: u64,
    pub pg_commit_attempts: u64,
    pub object_requests: u64,
    pub object_bytes: u64,
    pub output_bytes: u64,
    pub host_logical_live_bytes: u64,
    pub host_logical_peak_bytes: u64,
    pub elapsed_ns: u64,
}
impl KnownUsage {
    fn counters(&self) -> [u64; 6] {
        [self.pg_connect_attempts, self.pg_sql_attempts, self.pg_commit_attempts,
         self.object_requests, self.object_bytes, self.output_bytes]
    }
    pub fn validate(&self) -> ControlResult<()> {
        if self.host_logical_live_bytes > self.host_logical_peak_bytes { Err(ReadFailure::invalid()) }
        else { Ok(()) }
    }
}
#[derive(Clone, Debug)]
pub struct UsageEvidence {
    pub sequence: u64,
    pub delta: KnownUsage,
    pub cumulative: KnownUsage,
    pub unknown_dimensions: BTreeSet<Id>,
    pub retained_reservations: Budget,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UsageTransition { New, Replay }
impl UsageEvidence {
    pub fn validate(&self) -> ControlResult<()> {
        self.delta.validate()?;
        self.cumulative.validate()?;
        if self.delta.counters().iter().zip(self.cumulative.counters()).any(|(d, c)| *d > c)
            || self.delta.elapsed_ns > self.cumulative.elapsed_ns
            || self.delta.host_logical_peak_bytes > self.cumulative.host_logical_peak_bytes {
            return Err(ReadFailure::invalid());
        }
        Ok(())
    }
    /// Per original key/attempt, supplied by Q. No global ledger or retry loop.
    /// Live/peak and parent elapsed are observations, never summed subperiods.
    pub(crate) fn transition(&self, previous: &Self) -> ControlResult<UsageTransition> {
        self.validate()?;
        previous.validate()?;
        let same = self.delta == previous.delta && self.cumulative == previous.cumulative
            && self.unknown_dimensions == previous.unknown_dimensions
            && budget_values(&self.retained_reservations) == budget_values(&previous.retained_reservations);
        if self.sequence == previous.sequence && same { return Ok(UsageTransition::Replay); }
        let before = previous.cumulative.counters();
        let delta = self.delta.counters();
        let after = self.cumulative.counters();
        let additive = (0..6).all(|i| before[i].checked_add(delta[i]) == Some(after[i]));
        let reservations_kept = previous.unknown_dimensions.is_empty()
            || budget_values(&self.retained_reservations).iter()
                .zip(budget_values(&previous.retained_reservations)).all(|(a, b)| *a >= b);
        if self.sequence <= previous.sequence || !additive || !reservations_kept
            || !previous.unknown_dimensions.is_subset(&self.unknown_dimensions)
            || self.cumulative.elapsed_ns < previous.cumulative.elapsed_ns
            || self.cumulative.host_logical_peak_bytes < previous.cumulative.host_logical_peak_bytes {
            return Err(ReadFailure::new(ErrorCode::Conflict, ReadPhase::Return));
        }
        Ok(UsageTransition::New)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MethodId { RcBind, RcReauthorize, RcFinish, RcReconcile, RqAdmit, RqFinish }
impl MethodId {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::RcBind => "RC-B", Self::RcReauthorize => "RC-A", Self::RcFinish => "RC-F",
            Self::RcReconcile => "RC-R", Self::RqAdmit => "RQ-1", Self::RqFinish => "RQ-2",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProtectionLevel { FixtureOnly }
#[derive(Clone, Debug)]
pub struct CallReceipt {
    pub key: ReadRequestKey,
    pub attempt_id: Id,
    pub method_id: MethodId,
    pub phase: ReadPhase,
    pub observed_ns: u64,
    pub request_state: RequestState,
    pub usage: UsageEvidence,
    pub stop: StopEvidence,
    pub cleanup: CleanupState,
    pub custody: Option<CustodyTicket>,
    pub protection_level: ProtectionLevel,
}
impl CallReceipt {
    pub fn validate(&self) -> ControlResult<()> {
        self.usage.validate()?;
        self.stop.validate()?;
        if let Some(custody) = &self.custody {
            self.key.require_same(&custody.key)?;
            validate_closure(custody, &self.cleanup, &self.stop)?;
            if custody.state == CustodyState::Closed && self.request_state == RequestState::InFlight {
                return Err(ReadFailure::invalid());
            }
        }
        if self.request_state == RequestState::OutcomeUnknown
            && (self.custody.is_none() || self.custody.as_ref().is_some_and(|c| c.state == CustodyState::Closed)) {
            return Err(ReadFailure::invalid());
        }
        Ok(())
    }
    pub fn usage_after(&self, previous: &Self) -> ControlResult<UsageTransition> {
        self.validate()?;
        previous.validate()?;
        self.key.require_same(&previous.key)?;
        if self.attempt_id != previous.attempt_id || self.method_id != previous.method_id
            || self.observed_ns < previous.observed_ns
            || (self.usage.sequence == previous.usage.sequence
                && (self.phase != previous.phase || self.request_state != previous.request_state
                    || self.observed_ns != previous.observed_ns || self.stop != previous.stop
                    || self.cleanup != previous.cleanup || self.custody != previous.custody)) {
            return Err(ReadFailure::new(ErrorCode::Conflict, ReadPhase::Return));
        }
        self.usage.transition(&previous.usage)
    }
}
fn validate_closure(custody: &CustodyTicket, cleanup: &CleanupState, stop: &StopEvidence) -> ControlResult<()> {
    if custody.state == CustodyState::Closed
        && (!matches!(cleanup, CleanupState::ReleasedConfirmed(_) | CleanupState::NotBoundConfirmed)
            || !stop.is_settled()) {
        return Err(ReadFailure::invalid());
    }
    Ok(())
}
#[derive(Clone, Debug)]
pub struct ReadCall<T> { pub result: Result<T, ReadFailure>, pub receipt: CallReceipt }
impl<T> ReadCall<T> {
    pub fn new(result: Result<T, ReadFailure>, receipt: CallReceipt) -> ControlResult<Self> {
        let value = Self { result, receipt };
        value.validate()?;
        Ok(value)
    }
    pub fn validate(&self) -> ControlResult<()> {
        let result = &self.result;
        let receipt = &self.receipt;
        receipt.validate()?;
        if receipt.request_state == RequestState::OutcomeUnknown && result.is_ok() {
            return Err(ReadFailure::invalid());
        }
        if let Err(error) = result {
            if error.phase != receipt.phase
                || (receipt.request_state == RequestState::OutcomeUnknown && error.code != ErrorCode::OutcomeUnknown) {
                return Err(ReadFailure::invalid());
            }
            if error.code == ErrorCode::OutcomeUnknown
                && (receipt.custody.is_none() || receipt.custody.as_ref().is_some_and(|c| c.state == CustodyState::Closed)) {
                return Err(ReadFailure::invalid());
            }
        }
        Ok(())
    }
    pub fn require_key(&self, key: &ReadRequestKey) -> ControlResult<()> {
        self.validate()?;
        self.receipt.key.require_same(key)
    }
}

#[derive(Clone, Debug)]
pub struct BindInput {
    pub principal: HostPrincipal,
    pub request: R1QueryRequest,
    pub key: ReadRequestKey,
}
impl BindInput {
    pub fn validate(&self, read: &ReadControl) -> ControlResult<()> {
        self.key.require_same(&ReadRequestKey::new(&self.request, self.principal.clone())?)?;
        self.key.require_same(read.key())
    }
}
#[derive(Clone, Debug)]
pub struct AuthEpoch {
    pub policy_epoch: u64,
    pub checked_unix_ms: u64,
    pub binding_sha256: Sha256,
}
#[derive(Clone, Debug)]
pub struct ReadResolution {
    pub key: ReadRequestKey,
    pub custody: CustodyTicket,
    pub cleanup: CleanupState,
    pub stop: StopEvidence,
}
impl ReadResolution {
    pub fn validate(&self) -> ControlResult<()> {
        self.key.require_same(&self.custody.key)?;
        self.stop.validate()?;
        validate_closure(&self.custody, &self.cleanup, &self.stop)
    }
    pub fn require_original(&self, key: &ReadRequestKey, lease: Option<&ExactLease>) -> ControlResult<()> {
        self.validate()?;
        self.key.require_same(key)?;
        if self.cleanup == CleanupState::NotBoundConfirmed && lease.is_some() {
            return Err(ReadFailure::new(ErrorCode::Conflict, ReadPhase::Reconcile));
        }
        if let CleanupState::ReleasedConfirmed(actual) | CleanupState::Bound(actual) = &self.cleanup {
            // None means the caller has not learned the original lease yet.
            // The returned identity remains provider evidence, not its own expectation.
            if lease.is_some_and(|expected| expected != actual) {
                return Err(ReadFailure::new(ErrorCode::Conflict, ReadPhase::Reconcile));
            }
        }
        Ok(())
    }
}

/// C binds a trusted principal/configuration when constructing its instance.
/// These signatures never authenticate caller data or perform PG operations.
pub trait ControlledCatalogRead {
    fn bind(&mut self, input: &BindInput, read: &mut ReadControl) -> ReadCall<BoundRead>;
    fn reauthorize(&mut self, bound: &BoundRead, read: &mut ReadControl) -> ReadCall<AuthEpoch>;
    fn finish(&mut self, key: &ReadRequestKey, lease: Option<&ExactLease>, cleanup: &mut CleanupControl) -> ReadCall<ReadResolution>;
    fn reconcile_read(&mut self, key: &ReadRequestKey, cleanup: &mut CleanupControl) -> ReadCall<ReadResolution>;
}
