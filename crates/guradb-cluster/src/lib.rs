//! Unpublished internal Rust facade; no wire, runtime, ledger or OS effects.
mod envelope;
mod state;

pub use envelope::{validate_envelopes, EnvelopeError, TaskEnvelope, TaskIdentity, TaskSpec};
pub use state::{
    aggregate, Event, EventKind, ModelError, Outcome, ResultObservation, Start, TaskSnapshot, TaskState,
};

#[cfg(test)]
#[path = "../tests/unit/envelope.rs"]
mod envelope_tests;

#[cfg(test)]
#[path = "../tests/unit/state.rs"]
mod state_tests;
