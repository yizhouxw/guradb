//! Private rc2 values and checked host control. No I/O or authority provider.
use super::{canonical, Budget, Cell, Contract, Payload};
use serde::Serialize;
use serde_json::json;
use std::collections::BTreeSet;
use std::sync::{atomic::{AtomicBool, Ordering}, Arc};

pub const READ_CONTROL_VERSION: &str = "read-control/1.0.0-rc2";
pub const READ_CONTROL_PROFILE: &str = "r1-local-service";
const NS_PER_MS: u64 = 1_000_000;

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct Id(String);
impl Id {
    pub fn new(value: impl Into<String>) -> ControlResult<Self> {
        let value = value.into();
        super::wire::validate_named(&json!(value), "FixedId").map_err(|_| ReadFailure::invalid())?;
        Ok(Self(value))
    }
    pub fn as_str(&self) -> &str { &self.0 }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Sha256(pub [u8; 32]);
impl Sha256 {
    pub fn from_hex(value: &str) -> ControlResult<Self> {
        if value.len() != 64 || !value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
            return Err(ReadFailure::invalid());
        }
        let mut bytes = [0; 32];
        hex::decode_to_slice(value, &mut bytes).map_err(|_| ReadFailure::invalid())?;
        Ok(Self(bytes))
    }
    pub fn hex(&self) -> String { hex::encode(self.0) }
    pub fn of(bytes: &[u8]) -> Self {
        use sha2::{Digest, Sha256 as Hasher};
        Self(Hasher::digest(bytes).into())
    }
}
impl Serialize for Sha256 {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.hex())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ErrorCode {
    InvalidContract, UnsupportedVersion, Unauthorized, Revoked, ExpiredContext,
    Conflict, ResourceLimit, Deadline, Cancelled, BackendUnavailable,
    ExecutionFailed, Unsupported, InvalidParameter, OutcomeUnknown,
}
impl ErrorCode {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::InvalidContract => "invalid_contract", Self::UnsupportedVersion => "unsupported_version",
            Self::Unauthorized => "unauthorized", Self::Revoked => "revoked", Self::ExpiredContext => "expired_context",
            Self::Conflict => "conflict", Self::ResourceLimit => "resource_limit", Self::Deadline => "deadline",
            Self::Cancelled => "cancelled", Self::BackendUnavailable => "backend_unavailable",
            Self::ExecutionFailed => "execution_failed", Self::Unsupported => "unsupported",
            Self::InvalidParameter => "invalid_parameter", Self::OutcomeUnknown => "outcome_unknown",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReadPhase {
    Validate, Reserve, Connect, Authorize, BindCommit, Prepare, Reauthorize,
    ReleaseCommit, Reconcile, Return,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadFailure {
    pub code: ErrorCode,
    pub trigger_code: Option<ErrorCode>,
    pub phase: ReadPhase,
    pub diagnostic_id: Id,
}
pub type ControlResult<T> = Result<T, ReadFailure>;
impl ReadFailure {
    pub fn new(code: ErrorCode, phase: ReadPhase) -> Self {
        Self { code, trigger_code: None, phase, diagnostic_id: Id("read-control".into()) }
    }
    pub fn invalid() -> Self { Self::new(ErrorCode::InvalidContract, ReadPhase::Validate) }
    pub fn unknown(trigger: ErrorCode, phase: ReadPhase) -> Self {
        Self { trigger_code: Some(trigger), ..Self::new(ErrorCode::OutcomeUnknown, phase) }
    }
}

/// A value binding; its construction does not authenticate its issuer.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct HostPrincipal {
    pub issuer_id: Id,
    pub config_sha256: Sha256,
    pub tenant_id: Id,
    pub subject_id: Id,
    pub delegation_ref: Id,
}
#[derive(Clone, Debug)]
pub struct R1QueryRequest {
    pub bind_request: Contract,
    pub sql: String,
    pub params: Vec<Cell>,
}
impl R1QueryRequest {
    pub fn validate(&self) -> ControlResult<()> {
        self.bind()?;
        if self.sql.len() > 16 * 1024 || self.params.len() > 64 {
            return Err(ReadFailure::invalid());
        }
        for cell in &self.params {
            match cell {
                Cell::Text(value) if value.chars().count() > 4096 => return Err(ReadFailure::invalid()),
                Cell::Int8(value) if value.parse::<i64>().ok().map(|n| n.to_string()).as_ref() != Some(value) => {
                    return Err(ReadFailure::invalid());
                }
                _ => {}
            }
        }
        if canonical(&json!({"sql": self.sql, "params": self.params})).len() > 64 * 1024 {
            return Err(ReadFailure::new(ErrorCode::ResourceLimit, ReadPhase::Validate));
        }
        Ok(())
    }
    pub fn bind(&self) -> ControlResult<&super::BindRequest> {
        match &self.bind_request.envelope().payload {
            Payload::BindRequest(value) => Ok(value),
            _ => Err(ReadFailure::invalid()),
        }
    }
    pub fn execution_sha256(&self, principal: &HostPrincipal) -> ControlResult<Sha256> {
        self.validate()?;
        Ok(Sha256::of(&canonical(&json!({
            "profile": READ_CONTROL_PROFILE, "principal": principal,
            "bind_request": self.bind_request.document(), "sql": self.sql, "params": self.params
        }))))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadRequestKey {
    pub tenant_id: Id,
    pub dataset_id: Id,
    pub query_id: Id,
    pub request_id: Id,
    pub principal: HostPrincipal,
    pub bind_sha256: Sha256,
    pub execution_sha256: Sha256,
}
impl ReadRequestKey {
    pub fn new(request: &R1QueryRequest, principal: HostPrincipal) -> ControlResult<Self> {
        request.validate()?;
        let value = request.bind()?;
        if value.tenant_id != principal.tenant_id.as_str()
            || value.subject_id != principal.subject_id.as_str()
            || value.delegation_ref != principal.delegation_ref.as_str() {
            return Err(ReadFailure::new(ErrorCode::Unauthorized, ReadPhase::Validate));
        }
        Ok(Self {
            tenant_id: Id::new(value.tenant_id.clone())?, dataset_id: Id::new(value.dataset_id.clone())?,
            query_id: Id::new(value.query_id.clone())?, request_id: Id::new(value.request_id.clone())?,
            bind_sha256: Sha256::of(request.bind_request.encoded()),
            execution_sha256: request.execution_sha256(&principal)?, principal,
        })
    }
    pub fn require_same(&self, other: &Self) -> ControlResult<()> {
        if self == other { Ok(()) } else { Err(ReadFailure::new(ErrorCode::Conflict, ReadPhase::Validate)) }
    }
}

pub fn budget_values(value: &Budget) -> [u64; 9] {
    [value.memory_bytes, value.object_requests, value.object_bytes, value.candidates,
     value.top_k, value.graph_edges, value.output_bytes, value.concurrency, value.temp_bytes]
}
pub fn budget_from(v: [u64; 9]) -> Budget {
    Budget { memory_bytes: v[0], object_requests: v[1], object_bytes: v[2], candidates: v[3],
             top_k: v[4], graph_edges: v[5], output_bytes: v[6], concurrency: v[7], temp_bytes: v[8] }
}
pub fn narrow_budget(parent: &Budget, cap: &Budget) -> Budget {
    let p = budget_values(parent);
    let c = budget_values(cap);
    budget_from(std::array::from_fn(|i| p[i].min(c[i])))
}
/// Q supplies the current snapshot; this is not an executing/accounting backend.
#[derive(Clone, Debug)]
pub struct ReadLedger {
    pub consumed: Budget,
    pub retained_reservations: Budget,
    pub unknown_dimensions: BTreeSet<Id>,
}
impl Default for ReadLedger {
    fn default() -> Self {
        Self { consumed: budget_from([0; 9]), retained_reservations: budget_from([0; 9]), unknown_dimensions: BTreeSet::new() }
    }
}
impl ReadLedger {
    fn require_progress(&self, old: &Self) -> ControlResult<()> {
        let used = budget_values(&self.consumed);
        let prior = budget_values(&old.consumed);
        let retained = budget_values(&self.retained_reservations);
        let prior_retained = budget_values(&old.retained_reservations);
        if [1, 2, 3, 5, 6].iter().any(|&i| used[i] < prior[i])
            || !old.unknown_dimensions.is_subset(&self.unknown_dimensions)
            || (!old.unknown_dimensions.is_empty() && (0..9).any(|i| retained[i] < prior_retained[i])) {
            return Err(ReadFailure::new(ErrorCode::Conflict, ReadPhase::Reserve));
        }
        Ok(())
    }
    pub fn remaining(&self, cap: &Budget) -> ControlResult<Budget> {
        let c = budget_values(cap);
        let used = budget_values(&self.consumed);
        let held = budget_values(&self.retained_reservations);
        let mut left = [0; 9];
        for i in 0..9 {
            left[i] = used[i].checked_add(held[i]).and_then(|n| c[i].checked_sub(n))
                .ok_or_else(|| ReadFailure::new(ErrorCode::ResourceLimit, ReadPhase::Reserve))?;
        }
        Ok(budget_from(left))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ClockSample { pub monotonic_ns: u64, pub unix_ms: u64 }
/// Trusted same-host clock injection; sample must be fresh and perform no I/O.
pub trait ControlClock: Send + Sync { fn sample(&self) -> ClockSample; }
#[derive(Clone, Debug, Default)]
pub struct CancelHandle(Arc<AtomicBool>);
impl CancelHandle {
    pub fn cancel(&self) { self.0.store(true, Ordering::SeqCst); }
    pub fn is_cancelled(&self) -> bool { self.0.load(Ordering::SeqCst) }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Guarantee { HostLogicalQuota, ExplicitUnknown, PgNativeHardBound, ProductionSourceProtection }
pub type GuaranteeSet = BTreeSet<Guarantee>;
#[derive(Clone, Debug)]
pub struct Remaining { pub remaining_ns: u64, pub budget: Budget }
impl Remaining {
    pub fn wait_ms(&self) -> ControlResult<u64> {
        let ms = self.remaining_ns / NS_PER_MS;
        if ms == 0 { Err(ReadFailure::new(ErrorCode::Deadline, ReadPhase::Reserve)) } else { Ok(ms) }
    }
}

/// Shared only for this key. The trusted owner must reuse it for cleanup.
#[derive(Clone, Debug)]
pub struct CallGate { key: ReadRequestKey, occupied: Arc<AtomicBool> }
#[must_use = "hold the permit for the entire local controlled call"]
pub struct CallPermit(Arc<AtomicBool>);
impl Drop for CallPermit { fn drop(&mut self) { self.0.store(false, Ordering::SeqCst); } }
impl CallGate {
    pub fn new(key: ReadRequestKey) -> Self { Self { key, occupied: Arc::new(AtomicBool::new(false)) } }
    pub fn enter(&self, key: &ReadRequestKey) -> ControlResult<CallPermit> {
        self.key.require_same(key)?;
        self.occupied.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| ReadFailure::new(ErrorCode::ResourceLimit, ReadPhase::Reserve))?;
        Ok(CallPermit(self.occupied.clone()))
    }
}

pub struct ReadControlSpec {
    pub version: String,
    pub profile: String,
    pub owner_id: Id,
    pub control_id: Id,
    pub key: ReadRequestKey,
    pub started: ClockSample,
    pub host_cap_ms: u64,
    pub budget: Budget,
    pub required_guarantees: GuaranteeSet,
}
/// Deliberately neither Clone nor Deserialize. Only Q creates a parent.
pub struct ReadControl {
    spec: ReadControlSpec,
    deadline_ns: u64,
    last: ClockSample,
    wall_expiry_ms: Option<u64>,
    clock: Arc<dyn ControlClock>,
    cancel: CancelHandle,
    gate: CallGate,
    ledger: ReadLedger,
}
impl ReadControl {
    pub fn new(spec: ReadControlSpec, request: &R1QueryRequest, clock: Arc<dyn ControlClock>) -> ControlResult<Self> {
        if spec.version != READ_CONTROL_VERSION || spec.profile != READ_CONTROL_PROFILE {
            return Err(ReadFailure::new(ErrorCode::UnsupportedVersion, ReadPhase::Validate));
        }
        if spec.required_guarantees.iter().any(|v| matches!(v, Guarantee::PgNativeHardBound | Guarantee::ProductionSourceProtection)) {
            return Err(ReadFailure::new(ErrorCode::Unsupported, ReadPhase::Validate));
        }
        spec.key.require_same(&ReadRequestKey::new(request, spec.key.principal.clone())?)?;
        let bind = request.bind()?;
        super::wire::validate_named(&json!(spec.budget), "Budget").map_err(|_| ReadFailure::invalid())?;
        if spec.host_cap_ms == 0 || spec.host_cap_ms > 10_000
            || budget_values(&spec.budget).iter().zip(budget_values(&bind.budget)).any(|(a, b)| *a > b) {
            return Err(ReadFailure::invalid());
        }
        let duration = spec.host_cap_ms.min(bind.timeout_ms).checked_mul(NS_PER_MS).ok_or_else(ReadFailure::invalid)?;
        let deadline_ns = spec.started.monotonic_ns.checked_add(duration).ok_or_else(ReadFailure::invalid)?;
        let gate = CallGate::new(spec.key.clone());
        let last = spec.started;
        let mut value = Self { spec, deadline_ns, last, wall_expiry_ms: None, clock,
            cancel: CancelHandle::default(), gate, ledger: ReadLedger::default() };
        value.checkpoint()?;
        Ok(value)
    }
    pub fn key(&self) -> &ReadRequestKey { &self.spec.key }
    pub fn owner_id(&self) -> &Id { &self.spec.owner_id }
    pub fn control_id(&self) -> &Id { &self.spec.control_id }
    pub fn t0_ns(&self) -> u64 { self.spec.started.monotonic_ns }
    pub fn deadline_ns(&self) -> u64 { self.deadline_ns }
    pub fn cancel_handle(&self) -> CancelHandle { self.cancel.clone() }
    pub fn call_gate(&self) -> CallGate { self.gate.clone() }
    pub fn enter(&self) -> ControlResult<CallPermit> { self.gate.enter(self.key()) }
    pub fn replace_ledger(&mut self, value: ReadLedger) -> ControlResult<()> {
        value.remaining(&self.spec.budget)?;
        value.require_progress(&self.ledger)?;
        self.ledger = value;
        Ok(())
    }
    pub fn ledger(&self) -> &ReadLedger { &self.ledger }
    fn fresh(&mut self) -> ControlResult<ClockSample> {
        let now = self.clock.sample();
        if now.monotonic_ns < self.last.monotonic_ns || now.unix_ms < self.last.unix_ms {
            return Err(ReadFailure::invalid());
        }
        self.last = now;
        Ok(now)
    }
    pub fn tighten_wall_deadline(&mut self, expiry_unix_ms: u64) -> ControlResult<()> {
        self.wall_expiry_ms = Some(self.wall_expiry_ms.map_or(expiry_unix_ms, |old| old.min(expiry_unix_ms)));
        self.checkpoint().map(|_| ())
    }
    pub fn checkpoint(&mut self) -> ControlResult<Remaining> {
        let now = self.fresh()?;
        if let Some(expiry) = self.wall_expiry_ms {
            let ms = expiry.checked_sub(now.unix_ms)
                .ok_or_else(|| ReadFailure::new(ErrorCode::Deadline, ReadPhase::Reserve))?;
            let ns = ms.checked_mul(NS_PER_MS).and_then(|v| now.monotonic_ns.checked_add(v))
                .ok_or_else(ReadFailure::invalid)?;
            self.deadline_ns = self.deadline_ns.min(ns);
        }
        if self.cancel.is_cancelled() {
            return Err(ReadFailure::new(ErrorCode::Cancelled, ReadPhase::Reserve));
        }
        let remaining_ns = self.deadline_ns.checked_sub(now.monotonic_ns)
            .ok_or_else(|| ReadFailure::new(ErrorCode::Deadline, ReadPhase::Reserve))?;
        let value = Remaining { remaining_ns, budget: self.ledger.remaining(&self.spec.budget)? };
        value.wait_ms()?;
        Ok(value)
    }
}

pub struct CleanupControlSpec {
    pub version: String,
    pub owner_id: Id,
    pub original_key: ReadRequestKey,
    pub cleanup_attempt_id: Id,
    pub started: ClockSample,
    pub timeout_ms: u64,
    pub budget: Budget,
    pub maintenance_cap: Budget,
}
/// Cleanup has its own deadline, never a read cancel token or renewed read.
pub struct CleanupControl {
    spec: CleanupControlSpec,
    deadline_ns: u64,
    last: ClockSample,
    clock: Arc<dyn ControlClock>,
    gate: CallGate,
    ledger: ReadLedger,
}
impl CleanupControl {
    pub fn new(spec: CleanupControlSpec, clock: Arc<dyn ControlClock>, gate: CallGate) -> ControlResult<Self> {
        if spec.version != READ_CONTROL_VERSION {
            return Err(ReadFailure::new(ErrorCode::UnsupportedVersion, ReadPhase::Validate));
        }
        gate.key.require_same(&spec.original_key)?;
        super::wire::validate_named(&json!(spec.budget), "Budget").map_err(|_| ReadFailure::invalid())?;
        if spec.timeout_ms == 0 || spec.timeout_ms > 5_000
            || budget_values(&spec.budget).iter().zip(budget_values(&spec.maintenance_cap)).any(|(a, b)| *a > b) {
            return Err(ReadFailure::invalid());
        }
        let deadline_ns = spec.timeout_ms.checked_mul(NS_PER_MS)
            .and_then(|v| spec.started.monotonic_ns.checked_add(v)).ok_or_else(ReadFailure::invalid)?;
        let last = spec.started;
        let mut value = Self { spec, deadline_ns, last, clock, gate, ledger: ReadLedger::default() };
        value.checkpoint()?;
        Ok(value)
    }
    pub fn key(&self) -> &ReadRequestKey { &self.spec.original_key }
    pub fn owner_id(&self) -> &Id { &self.spec.owner_id }
    pub fn attempt_id(&self) -> &Id { &self.spec.cleanup_attempt_id }
    pub fn deadline_ns(&self) -> u64 { self.deadline_ns }
    pub fn enter(&self) -> ControlResult<CallPermit> { self.gate.enter(self.key()) }
    pub fn replace_ledger(&mut self, value: ReadLedger) -> ControlResult<()> {
        value.remaining(&self.spec.budget)?;
        value.require_progress(&self.ledger)?;
        self.ledger = value;
        Ok(())
    }
    pub fn checkpoint(&mut self) -> ControlResult<Remaining> {
        let now = self.clock.sample();
        if now.monotonic_ns < self.last.monotonic_ns || now.unix_ms < self.last.unix_ms {
            return Err(ReadFailure::invalid());
        }
        self.last = now;
        let remaining_ns = self.deadline_ns.checked_sub(now.monotonic_ns)
            .ok_or_else(|| ReadFailure::new(ErrorCode::Deadline, ReadPhase::Reconcile))?;
        let value = Remaining { remaining_ns, budget: self.ledger.remaining(&self.spec.budget)? };
        value.wait_ms()?;
        Ok(value)
    }
}
