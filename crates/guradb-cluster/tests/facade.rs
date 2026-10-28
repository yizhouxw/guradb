//! External-crate consumer source. Cargo wiring/build/execution is pending E.
//! Expected observations are literals; these tests prove no real backend stop.
use guradb_cluster::{
    aggregate, validate_envelopes, EnvelopeError, Event, EventKind, ModelError, Outcome,
    ResultObservation, Start, TaskEnvelope, TaskIdentity, TaskSpec, TaskState,
};
use guradb_common::cf1a::{AuthContext, Budget, Pin, QueryContext};

fn budget(value: u64) -> Budget {
    Budget {
        memory_bytes: value,
        object_requests: value,
        object_bytes: value,
        candidates: value,
        top_k: value,
        graph_edges: value,
        output_bytes: value,
        concurrency: value,
        temp_bytes: value,
    }
}

fn parent() -> QueryContext {
    QueryContext {
        request_id: "request".into(),
        query_id: "query".into(),
        tenant_id: "tenant".into(),
        dataset_id: "dataset".into(),
        schema_id: "schema".into(),
        schema_version: 1,
        data_revision_id: "revision".into(),
        read_view_id: "view".into(),
        source_version_ids: vec!["source-v1".into()],
        artifact_ids: vec![],
        auth: AuthContext {
            tenant_id: "tenant".into(),
            subject_id: "subject".into(),
            dataset_id: "dataset".into(),
            actions: vec!["read".into()],
            policy_epoch: 1,
            expires_unix_ms: 200,
            delegation_ref: "delegation".into(),
        },
        pin: Pin {
            pin_id: "pin".into(),
            lease_id: "lease".into(),
            data_revision_id: "revision".into(),
            read_view_id: "view".into(),
            expires_unix_ms: 200,
        },
        bound_at_unix_ms: 100,
        deadline_unix_ms: 200,
        remaining_ttl_ms: 100,
        budget: budget(3),
        cancellation_id: "cancel-parent".into(),
        trace_id: "trace".into(),
        span_id: "span".into(),
    }
}

fn specs() -> [TaskSpec; 3] {
    [0, 1, 2].map(|shard| TaskSpec {
        identity: TaskIdentity {
            task_id: format!("task-{shard}"),
            attempt_id: "attempt-one".into(),
            query_id: "query".into(),
            shard,
        },
        payload_sha256: "a".repeat(64),
        child_cap: budget(1),
    })
}

fn event(task: &TaskEnvelope<'_>, kind: EventKind) -> Event {
    Event {
        identity: task.identity().clone(),
        payload_sha256: task.payload_sha256().into(),
        kind,
    }
}

/// Consumer-owned acceptance gate. A rejected observation closes this operation;
/// it must never aggregate an older successful snapshot after discarding Err.
struct Consumer<'a> {
    states: [TaskState<'a>; 3],
    rejection: Option<ModelError>,
}

impl<'a> Consumer<'a> {
    fn new(tasks: &[TaskEnvelope<'a>; 3]) -> Self {
        Self {
            states: tasks.each_ref().map(TaskState::new),
            rejection: None,
        }
    }

    fn observe(&mut self, shard: usize, observation: Event) -> Result<(), ModelError> {
        if let Some(error) = self.rejection {
            return Err(error);
        }
        match self.states[shard].reduce(&observation) {
            Ok(next) => {
                self.states[shard] = next;
                Ok(())
            }
            Err(error) => {
                self.rejection = Some(error);
                Err(error)
            }
        }
    }

    fn outcome(&self, tasks: &[TaskEnvelope<'_>; 3]) -> Result<Outcome, ModelError> {
        if let Some(error) = self.rejection {
            return Err(error);
        }
        aggregate(tasks, &self.states.each_ref())
    }
}

#[test]
fn external_consumer_constructs_specs_and_reads_snapshots_without_state_mutation() {
    let parent = parent();
    let tasks = validate_envelopes(specs(), &parent, &budget(3)).unwrap();
    let mut consumer = Consumer::new(&tasks);
    assert_eq!(consumer.outcome(&tasks), Ok(Outcome::Pending));
    for (shard, task) in tasks.iter().enumerate() {
        assert!(std::ptr::eq(task.parent(), &parent));
        assert_eq!(task.child_cap().memory_bytes, 1);
        let mut view = consumer.states[shard].snapshot();
        assert_eq!(view.identity, task.identity());
        assert_eq!(view.payload_sha256, "a".repeat(64));
        assert_eq!(view.start, &Start::NotStarted);
        assert_eq!(view.result, &ResultObservation::None);
        view.reaped = true;
        assert!(view.reaped);
        assert!(!consumer.states[shard].snapshot().reaped);
        for kind in [
            EventKind::Started,
            EventKind::SuccessCandidate("b".repeat(64)),
            EventKind::ExitObserved(0),
        ] {
            consumer.observe(shard, event(task, kind)).unwrap();
        }
        assert_eq!(consumer.states[shard].outcome(), Outcome::Pending);
        consumer.observe(shard, event(task, EventKind::Reaped)).unwrap();
        let view = consumer.states[shard].snapshot();
        assert_eq!(view.start, &Start::Started);
        assert_eq!(view.result, &ResultObservation::Candidate("b".repeat(64)));
        assert_eq!(view.exit, Some(0));
        assert!(view.reaped);
        assert!(!view.cancel_requested);
        assert!(!view.deadline_expired);
        assert!(!view.unknown);
        assert!(!view.cleanup_failed);
    }
    assert_eq!(consumer.outcome(&tasks), Ok(Outcome::Success));
    assert_eq!(aggregate(&tasks, &[&consumer.states[0], &consumer.states[1]]), Err(ModelError::TaskSet));
    assert_eq!(aggregate(&tasks, &[&consumer.states[0], &consumer.states[0], &consumer.states[2]]), Err(ModelError::TaskSet));
    // A conflict leaves the old model snapshot, but closes the consumer gate.
    assert_eq!(consumer.observe(0, event(&tasks[0], EventKind::OutcomeUnknown)), Err(ModelError::Conflict));
    assert_eq!(consumer.states[0].outcome(), Outcome::Success);
    assert_eq!(consumer.outcome(&tasks), Err(ModelError::Conflict));
    assert_eq!(consumer.observe(0, event(&tasks[0], EventKind::Reaped)), Err(ModelError::Conflict));
}

#[test]
fn cancellation_unknown_cleanup_and_failed_start_remain_independent_observations() {
    let parent = parent();
    let tasks = validate_envelopes(specs(), &parent, &budget(3)).unwrap();
    for (marker, expected) in [
        (EventKind::CancelRequested, Outcome::Failed),
        (EventKind::DeadlineObserved, Outcome::Failed),
        (EventKind::OutcomeUnknown, Outcome::Unknown),
        (EventKind::CleanupFailed, Outcome::Failed),
    ] {
        let mut state = TaskState::new(&tasks[0]);
        for kind in [EventKind::Started, marker.clone()] {
            state = state.reduce(&event(&tasks[0], kind)).unwrap();
        }
        let before_reap = state.snapshot();
        assert_eq!(before_reap.exit, None);
        assert!(!before_reap.reaped);
        assert_eq!(state.outcome(), expected);
        assert_eq!(state.reduce(&event(&tasks[0], EventKind::SuccessCandidate("b".repeat(64)))), Err(ModelError::LateResult));
        for kind in [EventKind::ExitObserved(0), EventKind::Reaped] {
            state = state.reduce(&event(&tasks[0], kind)).unwrap();
        }
        let after_reap = state.snapshot();
        assert_eq!(after_reap.exit, Some(0));
        assert!(after_reap.reaped);
        assert_eq!(after_reap.cancel_requested, marker == EventKind::CancelRequested);
        assert_eq!(after_reap.deadline_expired, marker == EventKind::DeadlineObserved);
        assert_eq!(after_reap.unknown, marker == EventKind::OutcomeUnknown);
        assert_eq!(after_reap.cleanup_failed, marker == EventKind::CleanupFailed);
        assert_eq!(state.outcome(), expected);
    }
    let failed = TaskState::new(&tasks[0]).reduce(&event(&tasks[0], EventKind::StartFailed("spawn".into()))).unwrap();
    assert_eq!(failed.snapshot().start, &Start::Failed("spawn".into()));
    assert_eq!(failed.snapshot().exit, None);
    assert!(!failed.snapshot().reaped);
    assert_eq!(failed.outcome(), Outcome::Failed);
}

#[test]
fn external_consumer_rejects_bad_caps_and_foreign_attempts() {
    let parent = parent();
    let mut over_cap = specs();
    over_cap[0].child_cap.object_bytes = 2;
    assert_eq!(validate_envelopes(over_cap, &parent, &budget(3)).unwrap_err(), EnvelopeError::AggregateExceedsRemaining);
    let tasks = validate_envelopes(specs(), &parent, &budget(3)).unwrap();
    let mut consumer = Consumer::new(&tasks);
    let mut foreign = event(&tasks[0], EventKind::Started);
    foreign.identity.attempt_id = "attempt-two".into();
    assert_eq!(consumer.observe(0, foreign), Err(ModelError::Identity));
    assert_eq!(consumer.states[0].snapshot().start, &Start::NotStarted);
    assert_eq!(consumer.outcome(&tasks), Err(ModelError::Identity));
    assert_eq!(consumer.observe(0, event(&tasks[0], EventKind::Started)), Err(ModelError::Identity));
}
