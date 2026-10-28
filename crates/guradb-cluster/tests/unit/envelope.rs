//! Literal fixtures; no clocks, authorization providers, processes or network.
use crate::envelope::{validate_envelopes, EnvelopeError, TaskEnvelope, TaskIdentity, TaskSpec};
use guradb_common::cf1a::{AuthContext, Budget, Pin, QueryContext};

pub(crate) fn budget(value: u64) -> Budget {
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

pub(crate) fn parent() -> QueryContext {
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

pub(crate) fn specs() -> [TaskSpec; 3] {
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

pub(crate) fn envelopes(parent: &QueryContext) -> [TaskEnvelope<'_>; 3] {
    validate_envelopes(specs(), parent, &budget(3)).unwrap()
}

fn axis(value: &mut Budget, dimension: usize) -> &mut u64 {
    match dimension {
        0 => &mut value.memory_bytes,
        1 => &mut value.object_requests,
        2 => &mut value.object_bytes,
        3 => &mut value.candidates,
        4 => &mut value.top_k,
        5 => &mut value.graph_edges,
        6 => &mut value.output_bytes,
        7 => &mut value.concurrency,
        8 => &mut value.temp_bytes,
        _ => unreachable!("fixture dimension"),
    }
}

#[test]
fn exact_caps_borrow_the_original_parent_without_replacing_deadline() {
    let parent = parent();
    let values = envelopes(&parent);
    for (shard, value) in values.iter().enumerate() {
        assert!(std::ptr::eq(value.parent(), &parent));
        assert_eq!(value.parent().deadline_unix_ms, 200);
        assert_eq!(value.parent().remaining_ttl_ms, 100);
        assert_eq!(value.parent().cancellation_id, "cancel-parent");
        assert_eq!(usize::from(value.identity().shard), shard);
        assert_eq!(value.child_cap().memory_bytes, 1);
        assert_eq!(value.payload_sha256(), "a".repeat(64));
    }
    assert_eq!(parent.budget.memory_bytes, 3);
}

#[test]
fn every_budget_axis_rejects_child_aggregate_and_invented_remaining() {
    for dimension in 0..9 {
        let parent = parent();
        let mut tasks = specs();
        *axis(&mut tasks[0].child_cap, dimension) = 4;
        assert_eq!(validate_envelopes(tasks, &parent, &budget(3)).unwrap_err(), EnvelopeError::ChildExceedsRemaining);

        let mut tasks = specs();
        *axis(&mut tasks[0].child_cap, dimension) = 2;
        assert_eq!(validate_envelopes(tasks, &parent, &budget(3)).unwrap_err(), EnvelopeError::AggregateExceedsRemaining);

        let mut remaining = budget(3);
        *axis(&mut remaining, dimension) = 4;
        assert_eq!(validate_envelopes(specs(), &parent, &remaining).unwrap_err(), EnvelopeError::RemainingExceedsParent);

        let mut parent = parent;
        parent.budget = budget(u64::MAX);
        let mut tasks = specs();
        *axis(&mut tasks[0].child_cap, dimension) = u64::MAX;
        assert_eq!(validate_envelopes(tasks, &parent, &budget(u64::MAX)).unwrap_err(), EnvelopeError::Overflow);
    }
}

#[test]
fn zero_remaining_allows_only_zero_caps() {
    let mut parent = parent();
    parent.budget = budget(0);
    let mut tasks = specs();
    for task in &mut tasks {
        task.child_cap = budget(0);
    }
    assert!(validate_envelopes(tasks, &parent, &budget(0)).is_ok());
    assert_eq!(validate_envelopes(specs(), &parent, &budget(0)).unwrap_err(), EnvelopeError::ChildExceedsRemaining);
}

#[test]
fn rejects_empty_or_foreign_identity_and_malformed_fingerprints() {
    let parent = parent();
    for field in 0..4 {
        let mut tasks = specs();
        match field {
            0 => tasks[0].identity.task_id.clear(),
            1 => tasks[0].identity.attempt_id.clear(),
            2 => tasks[0].identity.query_id.clear(),
            _ => tasks[0].identity.query_id = "other-query".into(),
        }
        assert_eq!(validate_envelopes(tasks, &parent, &budget(3)).unwrap_err(), EnvelopeError::Identity);
    }
    for digest in ["", &"a".repeat(63), &"a".repeat(65), &"A".repeat(64), &"z".repeat(64)] {
        let mut tasks = specs();
        tasks[0].payload_sha256 = digest.into();
        assert_eq!(validate_envelopes(tasks, &parent, &budget(3)).unwrap_err(), EnvelopeError::Fingerprint);
    }
}

#[test]
fn fixed_three_shards_and_unique_tasks_are_required() {
    let parent = parent();
    for shard in [0, 3, u8::MAX] {
        let mut tasks = specs();
        tasks[1].identity.shard = shard;
        assert_eq!(validate_envelopes(tasks, &parent, &budget(3)).unwrap_err(), EnvelopeError::Shards);
    }
    let mut tasks = specs();
    tasks[1].identity.task_id = tasks[0].identity.task_id.clone();
    assert_eq!(validate_envelopes(tasks, &parent, &budget(3)).unwrap_err(), EnvelopeError::DuplicateTask);
    let mut tasks = specs();
    tasks.swap(0, 2);
    assert!(validate_envelopes(tasks, &parent, &budget(3)).is_ok());
}
