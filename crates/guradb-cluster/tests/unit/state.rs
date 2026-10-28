//! Handwritten observations/expected states, not a process-stop oracle.
use crate::envelope::TaskEnvelope;
use crate::envelope_tests::{envelopes, parent};
use crate::state::{aggregate, Event, EventKind, ModelError, Outcome, ResultObservation, Start, TaskState};

fn event(envelope: &TaskEnvelope<'_>, kind: EventKind) -> Event {
    Event {
        identity: envelope.identity().clone(),
        payload_sha256: envelope.payload_sha256().into(),
        kind,
    }
}

fn sequence<'a>(envelope: &TaskEnvelope<'a>, kinds: &[EventKind]) -> TaskState<'a> {
    kinds.iter().fold(TaskState::new(envelope), |state, kind| {
        state.reduce(&event(envelope, kind.clone())).unwrap()
    })
}

fn success() -> [EventKind; 4] {
    [EventKind::Started, EventKind::SuccessCandidate("b".repeat(64)), EventKind::ExitObserved(0), EventKind::Reaped]
}

fn rejected(state: &TaskState<'_>, event: Event, expected: ModelError) {
    let before = state.clone();
    assert_eq!(state.reduce(&event), Err(expected));
    assert_eq!(*state, before, "rejection must not mutate the source snapshot");
}

#[test]
fn success_requires_all_independent_axes_and_exact_terminal_replays() {
    let parent = parent();
    let tasks = envelopes(&parent);
    let initial = TaskState::new(&tasks[0]);
    assert_eq!(initial.start, Start::NotStarted);
    assert_eq!(initial.result, ResultObservation::None);
    assert_eq!(initial.exit, None);
    assert!(!initial.reaped);
    for count in 0..4 {
        assert_eq!(sequence(&tasks[0], &success()[..count]).outcome(), Outcome::Pending);
    }
    let done = sequence(&tasks[0], &success());
    assert_eq!(done.outcome(), Outcome::Success);
    assert_eq!(done.start, Start::Started);
    assert_eq!(done.result, ResultObservation::Candidate("b".repeat(64)));
    assert_eq!(done.exit, Some(0));
    assert!(done.reaped);
    for kind in success().into_iter().skip(1) {
        assert_eq!(done.reduce(&event(&tasks[0], kind)).unwrap(), done);
    }
    for kind in [EventKind::CancelRequested, EventKind::DeadlineObserved] {
        rejected(&done, event(&tasks[0], kind), ModelError::AlreadyTerminal);
    }
    for kind in [EventKind::SuccessCandidate("c".repeat(64)), EventKind::ExitObserved(1), EventKind::CleanupFailed, EventKind::OutcomeUnknown, EventKind::Started, EventKind::FailureObserved("late".into())] {
        rejected(&done, event(&tasks[0], kind), ModelError::Conflict);
    }
}

#[test]
fn cancel_and_deadline_are_not_stop_and_block_both_result_orderings() {
    let parent = parent();
    let tasks = envelopes(&parent);
    for marker in [EventKind::CancelRequested, EventKind::DeadlineObserved] {
        let early = sequence(&tasks[0], &[marker.clone()]);
        assert_eq!(early.start, Start::NotStarted);
        assert_eq!(early.exit, None);
        assert!(!early.reaped);
        assert_eq!(early.outcome(), Outcome::Failed);
        rejected(&early, event(&tasks[0], EventKind::Started), ModelError::Order);
        assert_eq!(early.reduce(&event(&tasks[0], marker.clone())).unwrap(), early);
        for candidate_first in [false, true] {
            let mut kinds = vec![EventKind::Started];
            if candidate_first {
                kinds.push(EventKind::SuccessCandidate("b".repeat(64)));
            }
            kinds.push(marker.clone());
            let state = sequence(&tasks[0], &kinds);
            rejected(&state, event(&tasks[0], EventKind::SuccessCandidate("b".repeat(64))), ModelError::LateResult);
            let exited = state.reduce(&event(&tasks[0], EventKind::ExitObserved(0))).unwrap();
            assert!(!exited.reaped);
            let reaped = exited.reduce(&event(&tasks[0], EventKind::Reaped)).unwrap();
            assert_eq!(reaped.outcome(), Outcome::Failed);
            assert_eq!(reaped.cancel_requested, marker == EventKind::CancelRequested);
            assert_eq!(reaped.deadline_expired, marker == EventKind::DeadlineObserved);
        }
    }
}

#[test]
fn wrong_identity_or_payload_never_changes_even_a_successful_snapshot() {
    let parent = parent();
    let tasks = envelopes(&parent);
    for state in [TaskState::new(&tasks[0]), sequence(&tasks[0], &success())] {
        for dimension in 0..5 {
            let mut input = event(&tasks[0], EventKind::Reaped);
            match dimension {
                0 => input.identity.task_id = "foreign".into(),
                1 => input.identity.attempt_id = "attempt-two".into(),
                2 => input.identity.query_id = "foreign".into(),
                3 => input.identity.shard = 1,
                _ => input.payload_sha256 = "c".repeat(64),
            }
            rejected(&state, input, ModelError::Identity);
        }
    }
}

#[test]
fn result_order_conflicts_invalid_evidence_and_nonzero_exit_are_rejected() {
    let parent = parent();
    let tasks = envelopes(&parent);
    let initial = TaskState::new(&tasks[0]);
    for kind in [EventKind::Reaped, EventKind::ExitObserved(0), EventKind::SuccessCandidate("b".repeat(64))] {
        rejected(&initial, event(&tasks[0], kind), ModelError::Order);
    }
    for kind in [EventKind::StartFailed(String::new()), EventKind::FailureObserved(String::new()), EventKind::SuccessCandidate("Z".repeat(64))] {
        rejected(&initial, event(&tasks[0], kind), ModelError::InvalidEvidence);
    }
    let started = sequence(&tasks[0], &[EventKind::Started, EventKind::Started]);
    assert_eq!(started.start, Start::Started);
    rejected(&started, event(&tasks[0], EventKind::StartFailed("failed".into())), ModelError::Conflict);
    let candidate = started.reduce(&event(&tasks[0], EventKind::SuccessCandidate("b".repeat(64)))).unwrap();
    assert_eq!(candidate.reduce(&event(&tasks[0], EventKind::SuccessCandidate("b".repeat(64)))).unwrap(), candidate);
    rejected(&candidate, event(&tasks[0], EventKind::SuccessCandidate("c".repeat(64))), ModelError::Conflict);
    let exited = sequence(&tasks[0], &[EventKind::Started, EventKind::ExitObserved(9)]);
    assert_eq!(exited.outcome(), Outcome::Failed);
    assert_eq!(exited.reduce(&event(&tasks[0], EventKind::ExitObserved(9))).unwrap(), exited);
    rejected(&exited, event(&tasks[0], EventKind::ExitObserved(0)), ModelError::Conflict);
    rejected(&exited, event(&tasks[0], EventKind::SuccessCandidate("b".repeat(64))), ModelError::LateResult);
    // Result arriving after exit/reap is permitted only while still pending.
    assert_eq!(sequence(&tasks[0], &[EventKind::Started, EventKind::ExitObserved(0), EventKind::Reaped, EventKind::SuccessCandidate("b".repeat(64))]).outcome(), Outcome::Success);
}

#[test]
fn start_failures_unknown_cleanup_and_execution_failures_cannot_be_laundered() {
    let parent = parent();
    let tasks = envelopes(&parent);
    let failed = sequence(&tasks[0], &[EventKind::StartFailed("spawn".into()), EventKind::StartFailed("spawn".into())]);
    assert_eq!(failed.start, Start::Failed("spawn".into()));
    assert_eq!(failed.exit, None);
    assert!(!failed.reaped);
    rejected(&failed, event(&tasks[0], EventKind::StartFailed("different".into())), ModelError::Conflict);
    rejected(&failed, event(&tasks[0], EventKind::Started), ModelError::Order);
    for marker in [EventKind::OutcomeUnknown, EventKind::CleanupFailed, EventKind::FailureObserved("compute".into())] {
        let state = sequence(&tasks[0], &[EventKind::Started, EventKind::SuccessCandidate("b".repeat(64)), marker.clone(), marker.clone(), EventKind::ExitObserved(0), EventKind::Reaped]);
        assert!(state.reaped);
        assert_eq!(state.exit, Some(0));
        assert_eq!(state.outcome(), if marker == EventKind::OutcomeUnknown { Outcome::Unknown } else { Outcome::Failed });
        rejected(&state, event(&tasks[0], EventKind::SuccessCandidate("b".repeat(64))), ModelError::LateResult);
        if matches!(marker, EventKind::FailureObserved(_)) {
            rejected(&state, event(&tasks[0], EventKind::FailureObserved("different".into())), ModelError::Conflict);
        }
    }
}

#[test]
fn aggregate_requires_exact_three_bound_tasks_and_never_hides_partial_failure() {
    let parent = parent();
    let tasks = envelopes(&parent);
    let states = tasks.each_ref().map(|task| sequence(task, &success()));
    assert_eq!(aggregate(&tasks, &[&states[2], &states[0], &states[1]]), Ok(Outcome::Success));
    assert_eq!(aggregate(&tasks, &[&states[0], &states[1]]), Err(ModelError::TaskSet));
    assert_eq!(aggregate(&tasks, &[&states[0], &states[0], &states[2]]), Err(ModelError::TaskSet));
    let other_parent = crate::envelope_tests::parent();
    let other_tasks = envelopes(&other_parent);
    let foreign_parent = sequence(&other_tasks[0], &success());
    assert_eq!(aggregate(&tasks, &[&foreign_parent, &states[1], &states[2]]), Err(ModelError::TaskSet));
    let pending = TaskState::new(&tasks[0]);
    let failed = sequence(&tasks[0], &[EventKind::StartFailed("spawn".into())]);
    let unknown = sequence(&tasks[0], &[EventKind::OutcomeUnknown]);
    let cleanup = sequence(&tasks[0], &[EventKind::CleanupFailed]);
    for (first, expected) in [(&pending, Outcome::Pending), (&failed, Outcome::Failed), (&unknown, Outcome::Unknown), (&cleanup, Outcome::Failed)] {
        assert_eq!(aggregate(&tasks, &[first, &states[1], &states[2]]), Ok(expected));
    }
    let mut foreign = states[0].clone();
    // A snapshot from a separately validated payload set must not be accepted.
    let mut specs = crate::envelope_tests::specs();
    specs[0].payload_sha256 = "c".repeat(64);
    let alternate = crate::envelope::validate_envelopes(specs, &parent, &crate::envelope_tests::budget(3)).unwrap();
    foreign = foreign.reduce(&event(&tasks[0], EventKind::Reaped)).unwrap();
    assert_eq!(aggregate(&alternate, &[&foreign, &states[1], &states[2]]), Err(ModelError::TaskSet));
}
