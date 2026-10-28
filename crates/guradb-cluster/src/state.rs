//! Facts supplied by a caller, never a claim that this model stopped a backend.
use crate::envelope::{fingerprint, TaskEnvelope, TaskIdentity};
use guradb_common::cf1a::QueryContext;

#[derive(Clone, Copy, Debug)]
struct ParentRef<'a>(&'a QueryContext);

impl PartialEq for ParentRef<'_> {
    fn eq(&self, other: &Self) -> bool {
        std::ptr::eq(self.0, other.0)
    }
}

impl Eq for ParentRef<'_> {}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Start {
    NotStarted,
    Started,
    Failed(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ResultObservation {
    None,
    Candidate(String),
    Failure(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EventKind {
    Started,
    StartFailed(String),
    CancelRequested,
    DeadlineObserved,
    SuccessCandidate(String),
    FailureObserved(String),
    ExitObserved(i32),
    Reaped,
    OutcomeUnknown,
    CleanupFailed,
}

#[derive(Debug)]
pub struct Event {
    pub identity: TaskIdentity,
    pub payload_sha256: String,
    pub kind: EventKind,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ModelError {
    Identity,
    InvalidEvidence,
    Order,
    Conflict,
    LateResult,
    AlreadyTerminal,
    TaskSet,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Outcome {
    Pending,
    Failed,
    Unknown,
    Success,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TaskState<'a> {
    parent: ParentRef<'a>,
    identity: TaskIdentity,
    payload_sha256: String,
    pub(crate) start: Start,
    pub(crate) cancel_requested: bool,
    pub(crate) deadline_expired: bool,
    pub(crate) result: ResultObservation,
    pub(crate) exit: Option<i32>,
    pub(crate) reaped: bool,
    pub(crate) unknown: bool,
    pub(crate) cleanup_failed: bool,
}

/// Read-only observations: references are shared, scalar fields are copies.
/// Modifying this view cannot mutate the underlying TaskState.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TaskSnapshot<'a> {
    pub identity: &'a TaskIdentity,
    pub payload_sha256: &'a str,
    pub start: &'a Start,
    pub cancel_requested: bool,
    pub deadline_expired: bool,
    pub result: &'a ResultObservation,
    pub exit: Option<i32>,
    pub reaped: bool,
    pub unknown: bool,
    pub cleanup_failed: bool,
}

impl<'a> TaskState<'a> {
    pub fn new(envelope: &TaskEnvelope<'a>) -> Self {
        Self {
            parent: ParentRef(envelope.parent()),
            identity: envelope.identity().clone(),
            payload_sha256: envelope.payload_sha256().to_owned(),
            start: Start::NotStarted,
            cancel_requested: false,
            deadline_expired: false,
            result: ResultObservation::None,
            exit: None,
            reaped: false,
            unknown: false,
            cleanup_failed: false,
        }
    }

    pub fn snapshot(&self) -> TaskSnapshot<'_> {
        TaskSnapshot {
            identity: &self.identity,
            payload_sha256: &self.payload_sha256,
            start: &self.start,
            cancel_requested: self.cancel_requested,
            deadline_expired: self.deadline_expired,
            result: &self.result,
            exit: self.exit,
            reaped: self.reaped,
            unknown: self.unknown,
            cleanup_failed: self.cleanup_failed,
        }
    }

    pub fn outcome(&self) -> Outcome {
        if self.unknown {
            Outcome::Unknown
        } else if matches!(self.start, Start::Failed(_))
            || self.cancel_requested
            || self.deadline_expired
            || matches!(self.result, ResultObservation::Failure(_))
            || self.exit.is_some_and(|code| code != 0)
            || self.cleanup_failed
        {
            Outcome::Failed
        } else if self.start == Start::Started
            && matches!(self.result, ResultObservation::Candidate(_))
            && self.exit == Some(0)
            && self.reaped
        {
            Outcome::Success
        } else {
            Outcome::Pending
        }
    }

    fn exact_terminal_replay(&self, kind: &EventKind) -> bool {
        match kind {
            EventKind::SuccessCandidate(digest) => {
                self.result == ResultObservation::Candidate(digest.clone())
            }
            EventKind::ExitObserved(code) => self.exit == Some(*code),
            EventKind::Reaped => self.reaped,
            _ => false,
        }
    }

    /// Err leaves this immutable snapshot unchanged. Callers must consume Err.
    pub fn reduce(&self, event: &Event) -> Result<Self, ModelError> {
        if self.identity != event.identity || self.payload_sha256 != event.payload_sha256 {
            return Err(ModelError::Identity);
        }
        if self.outcome() == Outcome::Success {
            return if self.exact_terminal_replay(&event.kind) {
                Ok(self.clone())
            } else if matches!(
                event.kind,
                EventKind::CancelRequested | EventKind::DeadlineObserved
            ) {
                Err(ModelError::AlreadyTerminal)
            } else {
                Err(ModelError::Conflict)
            };
        }
        let mut next = self.clone();
        match &event.kind {
            EventKind::Started => {
                if self.start != Start::Started {
                    if self.start != Start::NotStarted || self.outcome() != Outcome::Pending {
                        return Err(ModelError::Order);
                    }
                    next.start = Start::Started;
                }
            }
            EventKind::StartFailed(code) => {
                if code.is_empty() {
                    return Err(ModelError::InvalidEvidence);
                }
                match &self.start {
                    Start::NotStarted => next.start = Start::Failed(code.clone()),
                    Start::Failed(previous) if previous == code => (),
                    _ => return Err(ModelError::Conflict),
                }
            }
            EventKind::CancelRequested => next.cancel_requested = true,
            EventKind::DeadlineObserved => next.deadline_expired = true,
            EventKind::SuccessCandidate(digest) => {
                if !fingerprint(digest) {
                    return Err(ModelError::InvalidEvidence);
                }
                if self.outcome() != Outcome::Pending {
                    return Err(ModelError::LateResult);
                }
                if self.start != Start::Started {
                    return Err(ModelError::Order);
                }
                match &self.result {
                    ResultObservation::None => {
                        next.result = ResultObservation::Candidate(digest.clone());
                    }
                    ResultObservation::Candidate(previous) if previous == digest => (),
                    _ => return Err(ModelError::Conflict),
                }
            }
            EventKind::FailureObserved(code) => {
                if code.is_empty() {
                    return Err(ModelError::InvalidEvidence);
                }
                match &self.result {
                    ResultObservation::Failure(previous) if previous != code => {
                        return Err(ModelError::Conflict);
                    }
                    _ => next.result = ResultObservation::Failure(code.clone()),
                }
            }
            EventKind::ExitObserved(code) => {
                if self.start != Start::Started {
                    return Err(ModelError::Order);
                }
                if self.exit.is_some_and(|previous| previous != *code) {
                    return Err(ModelError::Conflict);
                }
                next.exit = Some(*code);
            }
            EventKind::Reaped => {
                if self.exit.is_none() {
                    return Err(ModelError::Order);
                }
                next.reaped = true;
            }
            EventKind::OutcomeUnknown => next.unknown = true,
            EventKind::CleanupFailed => next.cleanup_failed = true,
        }
        Ok(next)
    }
}

/// Bind snapshots to this validated task set; pending is never success.
pub fn aggregate(
    envelopes: &[TaskEnvelope<'_>; 3],
    states: &[&TaskState<'_>],
) -> Result<Outcome, ModelError> {
    if states.len() != 3 {
        return Err(ModelError::TaskSet);
    }
    for envelope in envelopes {
        if states
            .iter()
            .filter(|state| {
                std::ptr::eq(state.parent.0, envelope.parent())
                    && state.identity == *envelope.identity()
                    && state.payload_sha256 == envelope.payload_sha256()
            })
            .count()
            != 1
        {
            return Err(ModelError::TaskSet);
        }
    }
    if states.iter().any(|state| state.outcome() == Outcome::Unknown) {
        Ok(Outcome::Unknown)
    } else if states.iter().any(|state| state.outcome() == Outcome::Failed) {
        Ok(Outcome::Failed)
    } else if states.iter().all(|state| state.outcome() == Outcome::Success) {
        Ok(Outcome::Success)
    } else {
        Ok(Outcome::Pending)
    }
}
