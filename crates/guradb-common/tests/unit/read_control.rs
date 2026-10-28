//! Fixed QA66 vectors; no PG, clock I/O or production encoder as expected.
use super::read_control::*;
use super::{decode, Budget, Cell};
use std::sync::{Arc, Mutex};

pub(super) const B0: &str = r#"{"contract_version":"cf1a/1.0","payload":{"bind_request":{"budget":{"candidates":16,"concurrency":1,"graph_edges":1,"memory_bytes":4096,"object_bytes":4096,"object_requests":8,"output_bytes":4096,"temp_bytes":4096,"top_k":3},"cancellation_id":"cancel-1","dataset_id":"dataset-1","delegation_ref":"host-1","query_id":"query-1","read_view_id":"","request_id":"request-1","span_id":"span-1","subject_id":"svc-1","tenant_id":"tenant-1","timeout_ms":30000,"trace_id":"trace-1","view_mode":"published"}},"required_capabilities":["fixed_read","typed_json_v1","strong_integrity","catalog_cas"]}"#;
pub(super) fn id(value: &str) -> Id { Id::new(value).unwrap() }
pub(super) fn principal() -> HostPrincipal {
    HostPrincipal { issuer_id: id("operator-1"),
        config_sha256: Sha256::from_hex("55bb6500b8de191709cc6b6333467c9836d43caed411c0fe9903584ee5fd6581").unwrap(),
        tenant_id: id("tenant-1"), subject_id: id("svc-1"), delegation_ref: id("host-1") }
}
pub(super) fn request() -> R1QueryRequest {
    R1QueryRequest { bind_request: decode(B0.as_bytes()).unwrap(),
        sql: "SELECT title FROM bound_resource".into(), params: vec![] }
}
pub(super) fn key() -> ReadRequestKey { ReadRequestKey::new(&request(), principal()).unwrap() }
pub(super) fn budget() -> Budget { request().bind().unwrap().budget.clone() }
pub(super) struct TestClock(pub Mutex<ClockSample>);
impl TestClock {
    pub fn set(&self, ns: u64, ms: u64) { *self.0.lock().unwrap() = ClockSample { monotonic_ns: ns, unix_ms: ms }; }
}
impl ControlClock for TestClock { fn sample(&self) -> ClockSample { *self.0.lock().unwrap() } }
pub(super) fn clock() -> Arc<TestClock> {
    Arc::new(TestClock(Mutex::new(ClockSample { monotonic_ns: 1_000_000_000, unix_ms: 1000 })))
}
pub(super) fn spec() -> ReadControlSpec {
    ReadControlSpec { version: READ_CONTROL_VERSION.into(), profile: READ_CONTROL_PROFILE.into(),
        owner_id: id("host-1"), control_id: id("control-1"), key: key(),
        started: ClockSample { monotonic_ns: 1_000_000_000, unix_ms: 1000 },
        host_cap_ms: 10_000, budget: budget(), required_guarantees: Default::default() }
}
pub(super) fn cleanup(read: &ReadControl, clock: Arc<TestClock>) -> CleanupControl {
    CleanupControl::new(cleanup_spec(read, &clock), clock, read.call_gate()).unwrap()
}
fn cleanup_spec(read: &ReadControl, clock: &TestClock) -> CleanupControlSpec {
    CleanupControlSpec { version: READ_CONTROL_VERSION.into(), owner_id: id("host-1"),
        original_key: read.key().clone(), cleanup_attempt_id: id("cleanup-1"), started: clock.sample(),
        timeout_ms: 5000, budget: budget(), maintenance_cap: budget() }
}

#[test]
fn qa66_complete_envelope_and_three_raw_sql_hashes() {
    let mut r = request();
    assert_eq!(Sha256::of(r.bind_request.encoded()).hex(), "d59414db67b535ef380c78975996ea1e6806f48f24a00d37ff2fb8671142a7d5");
    for (sql, expected) in [
        ("SELECT title FROM bound_resource", "62c61142ccd90fdb28e0abf01a6454b8086fb4716b6b5263660fc760ab446c8b"),
        ("SELECT title FROM BOUND_RESOURCE", "ce6ee3413c857a217214416f1babb1953c3f9ce721b13c3022c611dee5ade105"),
        ("SELECT title FROM \"bound_resource\"", "17a21ab8b42db23750166d0b0442bab62ff29e46242cacddf3902407e2a5cf09"),
    ] {
        r.sql = sql.into();
        assert_eq!(r.execution_sha256(&principal()).unwrap().hex(), expected);
    }
}

#[test]
fn fixed_ids_hashes_and_tagged_parameters_fail_closed() {
    for bad in ["", "latest", "with space", "名", "a/b"] { assert!(Id::new(bad).is_err()); }
    assert!(Id::new("Data-1").is_ok());
    for bad in ["", &"A".repeat(64), &"g".repeat(64), &"a".repeat(63)] {
        assert!(Sha256::from_hex(bad).is_err());
    }
    let mut r = request();
    for bad in ["01", "+1", "-0", "9223372036854775808"] {
        r.params = vec![Cell::Int8(bad.into())];
        assert_eq!(r.validate().unwrap_err().code, ErrorCode::InvalidContract);
    }
    r.params = vec![Cell::Int8("-9223372036854775808".into()), Cell::Null(())];
    r.validate().unwrap();
    r.params = vec![Cell::Text("x".repeat(4097))];
    assert!(r.validate().is_err());
    r.params = vec![Cell::Text("x".repeat(4096)); 20];
    assert_eq!(r.validate().unwrap_err().code, ErrorCode::ResourceLimit);
    r.params = vec![Cell::Bool(false); 65];
    assert!(r.validate().is_err());
    r.params.clear(); r.sql = "x".repeat(16 * 1024 + 1);
    assert!(r.validate().is_err());
}

#[test]
fn key_keeps_principal_request_and_full_fingerprint() {
    let first = key();
    first.require_same(&key()).unwrap();
    let mut r = request(); r.sql = "SELECT title FROM BOUND_RESOURCE".into();
    let changed = ReadRequestKey::new(&r, principal()).unwrap();
    assert_eq!(first.require_same(&changed).unwrap_err().code, ErrorCode::Conflict);
    r = request(); r.params.push(Cell::Bool(false));
    assert_ne!(first.execution_sha256, ReadRequestKey::new(&r, principal()).unwrap().execution_sha256);
    let mut p = principal(); p.subject_id = id("other");
    assert_eq!(ReadRequestKey::new(&request(), p).unwrap_err().code, ErrorCode::Unauthorized);
    let mut p = principal(); p.config_sha256 = Sha256([7; 32]);
    assert_ne!(first.execution_sha256, ReadRequestKey::new(&request(), p).unwrap().execution_sha256);
}

#[test]
fn original_t0_checked_units_and_fresh_clock_only_tighten() {
    let mut raw: serde_json::Value = serde_json::from_str(B0).unwrap();
    raw["payload"]["bind_request"]["timeout_ms"] = 100.into();
    let r = R1QueryRequest { bind_request: decode(&super::canonical(&raw)).unwrap(), ..request() };
    let mut s = spec(); s.key = ReadRequestKey::new(&r, principal()).unwrap();
    let c = clock(); c.set(1_007_000_000, 1007);
    let mut read = ReadControl::new(s, &r, c.clone()).unwrap();
    assert_eq!(read.t0_ns(), 1_000_000_000);
    assert_eq!(read.deadline_ns(), 1_100_000_000);
    assert_eq!(read.checkpoint().unwrap().wait_ms().unwrap(), 93);
    read.tighten_wall_deadline(1050).unwrap();
    assert_eq!(read.deadline_ns(), 1_050_000_000);
    read.tighten_wall_deadline(2000).unwrap();
    assert_eq!(read.deadline_ns(), 1_050_000_000);
    c.set(1_049_000_001, 1049);
    assert_eq!(read.checkpoint().unwrap_err().code, ErrorCode::Deadline);
    assert_eq!(Remaining { remaining_ns: 1_999_999, budget: budget() }.wait_ms().unwrap(), 1);
    assert!(Remaining { remaining_ns: 999_999, budget: budget() }.wait_ms().is_err());
}

#[test]
fn rollback_overflow_unsupported_version_and_guarantee_reject() {
    let c = clock(); let mut read = ReadControl::new(spec(), &request(), c.clone()).unwrap();
    c.set(999_999_999, 1000);
    assert_eq!(read.checkpoint().unwrap_err().code, ErrorCode::InvalidContract);
    c.set(1_000_000_000, 999);
    assert_eq!(read.checkpoint().unwrap_err().code, ErrorCode::InvalidContract);
    let mut s = spec(); s.started.monotonic_ns = u64::MAX;
    assert_eq!(ReadControl::new(s, &request(), clock()).err().unwrap().code, ErrorCode::InvalidContract);
    let mut s = spec(); s.version = "rc-unknown".into();
    assert_eq!(ReadControl::new(s, &request(), clock()).err().unwrap().code, ErrorCode::UnsupportedVersion);
    let mut s = spec(); s.profile = "other".into();
    assert_eq!(ReadControl::new(s, &request(), clock()).err().unwrap().code, ErrorCode::UnsupportedVersion);
    for guarantee in [Guarantee::PgNativeHardBound, Guarantee::ProductionSourceProtection] {
        let mut s = spec(); s.required_guarantees.insert(guarantee);
        assert_eq!(ReadControl::new(s, &request(), clock()).err().unwrap().code, ErrorCode::Unsupported);
    }
    let mut read = ReadControl::new(spec(), &request(), clock()).unwrap();
    assert_eq!(read.tighten_wall_deadline(u64::MAX).unwrap_err().code, ErrorCode::InvalidContract);
}

#[test]
fn cancellation_and_shared_call_gate_do_not_cancel_cleanup() {
    let c = clock(); let mut read = ReadControl::new(spec(), &request(), c.clone()).unwrap();
    let mut clean = cleanup(&read, c.clone());
    let permit = read.enter().unwrap();
    assert_eq!(clean.enter().err().unwrap().code, ErrorCode::ResourceLimit);
    drop(permit);
    drop(clean.enter().unwrap());
    read.cancel_handle().cancel();
    assert_eq!(read.checkpoint().unwrap_err().code, ErrorCode::Cancelled);
    assert!(read.cancel_handle().is_cancelled());
    assert_eq!(clean.checkpoint().unwrap().wait_ms().unwrap(), 5000);
    c.set(6_000_000_000, 6000);
    assert_eq!(clean.checkpoint().unwrap_err().code, ErrorCode::Deadline);
}

#[test]
fn cap_snapshots_conserve_all_dimensions_and_do_not_refund_unknown() {
    let cap = budget();
    let mut ledger = ReadLedger::default();
    ledger.consumed.memory_bytes = 3072;
    ledger.retained_reservations.memory_bytes = 1024;
    assert_eq!(ledger.remaining(&cap).unwrap().memory_bytes, 0);
    ledger.retained_reservations.memory_bytes += 1;
    assert_eq!(ledger.remaining(&cap).unwrap_err().code, ErrorCode::ResourceLimit);
    ledger.consumed.memory_bytes = u64::MAX;
    assert!(ledger.remaining(&cap).is_err());
    let narrowed = narrow_budget(&cap, &budget_from([1; 9]));
    assert_eq!(budget_values(&narrowed), [1; 9]);
    let mut read = ReadControl::new(spec(), &request(), clock()).unwrap();
    assert!(read.replace_ledger(ledger).is_err());
    assert_eq!(read.checkpoint().unwrap().budget.memory_bytes, 4096);
}

#[test]
fn parent_and_cleanup_snapshots_keep_spent_costs_and_unknown_holds() {
    let c = clock(); let mut read = ReadControl::new(spec(), &request(), c.clone()).unwrap();
    assert_eq!(read.owner_id(), &id("host-1"));
    assert_eq!(read.control_id(), &id("control-1"));
    let mut ledger = ReadLedger::default();
    ledger.consumed.object_requests = 1;
    ledger.retained_reservations.memory_bytes = 128;
    ledger.unknown_dimensions.insert(id("pg-native-memory"));
    read.replace_ledger(ledger.clone()).unwrap();
    assert_eq!(read.checkpoint().unwrap().budget.object_requests, 7);
    assert_eq!(read.ledger().retained_reservations.memory_bytes, 128);
    assert_eq!(read.replace_ledger(ReadLedger::default()).unwrap_err().code, ErrorCode::Conflict);
    let mut clean = cleanup(&read, c);
    assert_eq!(clean.owner_id(), &id("host-1"));
    assert_eq!(clean.attempt_id(), &id("cleanup-1"));
    assert_eq!(clean.deadline_ns(), 6_000_000_000);
    clean.replace_ledger(ledger).unwrap();
    assert_eq!(clean.checkpoint().unwrap().budget.memory_bytes, 3968);
    assert!(clean.replace_ledger(ReadLedger::default()).is_err());
}

#[test]
fn invalid_caps_keys_and_cleanup_limits_are_not_new_authority() {
    for host_cap_ms in [0, 10_001] {
        let mut s = spec(); s.host_cap_ms = host_cap_ms;
        assert!(ReadControl::new(s, &request(), clock()).is_err());
    }
    let mut s = spec(); s.budget.object_requests = 9;
    assert!(ReadControl::new(s, &request(), clock()).is_err());
    let mut s = spec(); s.key.execution_sha256 = Sha256([0; 32]);
    assert!(ReadControl::new(s, &request(), clock()).is_err());
    let c = clock(); let read = ReadControl::new(spec(), &request(), c.clone()).unwrap();
    let mut k = key(); k.query_id = id("other-query");
    assert!(read.call_gate().enter(&k).is_err());
    let mut s = cleanup_spec(&read, &c); s.version = "unknown".into();
    assert_eq!(CleanupControl::new(s, c.clone(), read.call_gate()).err().unwrap().code, ErrorCode::UnsupportedVersion);
    for timeout_ms in [0, 5001] {
        let mut s = cleanup_spec(&read, &c); s.timeout_ms = timeout_ms;
        assert!(CleanupControl::new(s, c.clone(), read.call_gate()).is_err());
    }
    let mut s = cleanup_spec(&read, &c); s.maintenance_cap.memory_bytes = 4095;
    assert!(CleanupControl::new(s, c.clone(), read.call_gate()).is_err());
    let mut s = cleanup_spec(&read, &c); s.started.monotonic_ns = u64::MAX;
    assert!(CleanupControl::new(s, c.clone(), read.call_gate()).is_err());
    let mut s = cleanup_spec(&read, &c); s.original_key.query_id = id("other-query");
    assert!(CleanupControl::new(s, c.clone(), read.call_gate()).is_err());
    let mut clean = cleanup(&read, c.clone()); c.set(1_000_000_000, 999);
    assert_eq!(clean.checkpoint().unwrap_err().code, ErrorCode::InvalidContract);
}

#[test]
fn error_code_vocabulary_remains_the_closed_rc2_set() {
    for (code, text) in [
        (ErrorCode::InvalidContract, "invalid_contract"), (ErrorCode::UnsupportedVersion, "unsupported_version"),
        (ErrorCode::Unauthorized, "unauthorized"), (ErrorCode::Revoked, "revoked"),
        (ErrorCode::ExpiredContext, "expired_context"), (ErrorCode::Conflict, "conflict"),
        (ErrorCode::ResourceLimit, "resource_limit"), (ErrorCode::Deadline, "deadline"),
        (ErrorCode::Cancelled, "cancelled"), (ErrorCode::BackendUnavailable, "backend_unavailable"),
        (ErrorCode::ExecutionFailed, "execution_failed"), (ErrorCode::Unsupported, "unsupported"),
        (ErrorCode::InvalidParameter, "invalid_parameter"), (ErrorCode::OutcomeUnknown, "outcome_unknown"),
    ] { assert_eq!(code.as_str(), text); }
}

#[test]
fn original_a_version_capabilities_and_golden_stay_unchanged() {
    assert_eq!(super::VERSION, "cf1a/1.0");
    assert_eq!(super::CAPABILITIES, ["fixed_read", "typed_json_v1", "strong_integrity", "catalog_cas"]);
    let values: Vec<serde_json::Value> = serde_json::from_str(include_str!("../../../../api/cf1a/golden.json")).unwrap();
    for value in values {
        let bytes = super::canonical(&value);
        assert_eq!(decode(&bytes).unwrap().encoded(), bytes.as_slice());
    }
}
