//! Shape/negative fixtures only; no test proves PG effects or proof authority.
use super::controlled_ports::*;
use super::read_control::*;
use super::read_control_tests::{budget, cleanup, clock, id, key, principal, request, spec};
use super::{decode, Contract};
use std::collections::BTreeSet;

fn usage(sequence: u64, delta: u64, total: u64) -> UsageEvidence {
    UsageEvidence { sequence, delta: KnownUsage { pg_sql_attempts: delta, ..Default::default() },
        cumulative: KnownUsage { pg_sql_attempts: total, ..Default::default() },
        unknown_dimensions: BTreeSet::new(), retained_reservations: budget_from([0; 9]) }
}
fn receipt(key: ReadRequestKey) -> CallReceipt {
    CallReceipt { key, attempt_id: id("attempt-a"), method_id: MethodId::RcBind, phase: ReadPhase::Validate,
        observed_ns: 1_000_000_000, request_state: RequestState::NotAttempted,
        usage: usage(1, 0, 0), stop: StopEvidence::not_started(), cleanup: CleanupState::NotRequired,
        custody: None, protection_level: ProtectionLevel::FixtureOnly }
}
fn binding() -> Contract {
    let mut golden: Vec<serde_json::Value> = serde_json::from_str(include_str!("../../../../api/cf1a/golden.json")).unwrap();
    // Match B0/P0 before strict decoding; never mutate a key to fit a binding.
    let auth = &mut golden[0]["payload"]["read_binding"]["context"]["auth"];
    auth["subject_id"] = "svc-1".into();
    auth["delegation_ref"] = "host-1".into();
    decode(&super::canonical(&golden[0])).unwrap()
}
fn bound() -> BoundRead {
    let k = ReadRequestKey::new(&request(), principal()).unwrap();
    BoundRead::new(binding(), k).unwrap()
}
fn stopped() -> StopEvidence {
    StopEvidence { local_io: LocalIoState::Stopped, pg_attempt: PgAttemptState::StoppedConfirmed,
        pg_proof: Some(PgStopProof { session_id: id("session-1"), backend_pid: 42,
            backend_start_unix_ms: 1000, transaction_id: id("transaction-1"), proof_ref: id("proof-1"),
            no_queued_work: true }) }
}

#[test]
fn exact_lease_is_original_full_binding_identity() {
    let b = bound(); let lease = b.exact_lease().unwrap();
    assert_eq!(lease.pin_id, id("pin-1"));
    assert_eq!(lease.lease_id, id("lease-1"));
    assert_eq!(lease.read_view_id, id("view-1"));
    assert_eq!(lease.data_revision_id, id("revision-1"));
    b.require_lease(&b.key, &lease).unwrap();
    let mut wrong = lease.clone(); wrong.lease_id = id("lease-new");
    assert_eq!(b.require_lease(&b.key, &wrong).unwrap_err().code, ErrorCode::Conflict);
    wrong = lease.clone(); wrong.binding_sha256 = Sha256([0; 32]);
    assert!(b.require_lease(&b.key, &wrong).is_err());
    let mut other = b.key.clone(); other.request_id = id("request-new");
    assert!(b.require_lease(&other, &lease).is_err());
    assert!(BoundRead::new(request().bind_request, key()).is_err());
    let mut stale = key();
    stale.principal.subject_id = id("subject-1");
    stale.principal.delegation_ref = id("delegation-1");
    assert_eq!(ReadRequestKey::new(&request(), stale.principal.clone()).unwrap_err().code, ErrorCode::Unauthorized);
    assert!(BoundRead::new(binding(), stale).is_err());
}

#[test]
fn lease_fixture_keeps_complete_request_principal_and_fingerprints() {
    let original = request();
    let p = principal();
    let original_key = ReadRequestKey::new(&original, p.clone()).unwrap();
    assert_eq!(
        original_key.bind_sha256.hex(),
        "d59414db67b535ef380c78975996ea1e6806f48f24a00d37ff2fb8671142a7d5"
    );
    assert_eq!(
        original_key.execution_sha256.hex(),
        "62c61142ccd90fdb28e0abf01a6454b8086fb4716b6b5263660fc760ab446c8b"
    );
    let b = BoundRead::new(binding(), original_key.clone()).unwrap();
    let lease = b.exact_lease().unwrap();
    // Independently canonicalized golden binding with literal B0/P0 auth.
    assert_eq!(
        lease.binding_sha256.hex(),
        "97b514cc7a3ab6abd39a94d5558a9460f0e04bcf4ff64465abe93244eb5e49ee"
    );
    b.require_lease(&original_key, &lease).unwrap();
    let read = ReadControl::new(spec(), &original, clock()).unwrap();
    let input = BindInput { principal: p.clone(), request: original.clone(), key: original_key.clone() };
    input.validate(&read).unwrap();

    let mut changed_sql = original.clone();
    changed_sql.sql = "SELECT number FROM bound_resource".into();
    let input = BindInput { principal: p.clone(), request: changed_sql, key: original_key.clone() };
    assert_eq!(input.validate(&read).unwrap_err().code, ErrorCode::Conflict);

    let mut changed_bind = original.bind_request.document().clone();
    changed_bind["payload"]["bind_request"]["subject_id"] = "svc-other".into();
    let changed_request = R1QueryRequest {
        bind_request: decode(&super::canonical(&changed_bind)).unwrap(),
        ..original
    };
    let mut changed_principal = p;
    changed_principal.subject_id = id("svc-other");
    // Keep the old bind/execution digests explicitly as a negative fixture.
    let mut stale = original_key;
    stale.principal = changed_principal.clone();
    let input = BindInput { principal: changed_principal, request: changed_request, key: stale };
    assert_eq!(input.validate(&read).unwrap_err().code, ErrorCode::Conflict);
    assert!(BoundRead::new(binding(), input.key).is_err());
}

#[test]
fn receipt_replay_is_per_original_key_attempt_and_sequence() {
    let mut a = receipt(key()); a.usage = usage(1, 1, 1);
    assert_eq!(a.usage_after(&a).unwrap(), UsageTransition::Replay);
    let mut b = a.clone(); b.usage = usage(2, 2, 3);
    assert_eq!(b.usage_after(&a).unwrap(), UsageTransition::New);
    assert_eq!(b.usage.cumulative.pg_sql_attempts, 3);
    let mut wrong = b.clone(); wrong.usage.cumulative.pg_sql_attempts = 2;
    assert!(wrong.usage_after(&a).is_err());
    wrong = b.clone(); wrong.attempt_id = id("other-attempt");
    assert!(wrong.usage_after(&a).is_err());
    wrong = a.clone(); wrong.phase = ReadPhase::Connect;
    assert!(wrong.usage_after(&a).is_err());
    wrong = a.clone(); wrong.key.request_id = id("other-request");
    assert!(wrong.usage_after(&a).is_err());
    wrong = a.clone(); wrong.method_id = MethodId::RcReconcile;
    assert!(wrong.usage_after(&a).is_err());
    a.usage.cumulative.pg_sql_attempts = u64::MAX;
    b.usage = usage(2, 1, u64::MAX);
    assert!(b.usage_after(&a).is_err());
}

#[test]
fn live_peak_elapsed_and_unknown_do_not_become_additive_or_zero() {
    let mut a = usage(1, 1, 1);
    a.cumulative.host_logical_live_bytes = 10; a.cumulative.host_logical_peak_bytes = 20;
    a.cumulative.elapsed_ns = 100;
    a.unknown_dimensions.insert(id("pg-native-memory"));
    a.retained_reservations.memory_bytes = 64;
    let mut b = usage(2, 2, 3);
    b.cumulative.host_logical_live_bytes = 5; b.cumulative.host_logical_peak_bytes = 20;
    b.cumulative.elapsed_ns = 110;
    b.unknown_dimensions = a.unknown_dimensions.clone();
    b.retained_reservations.memory_bytes = 64;
    assert_eq!(b.transition(&a).unwrap(), UsageTransition::New);
    b.retained_reservations.memory_bytes = 0;
    assert!(b.transition(&a).is_err());
    b.retained_reservations.memory_bytes = 64; b.unknown_dimensions.clear();
    assert!(b.transition(&a).is_err());
    b.unknown_dimensions = a.unknown_dimensions.clone(); b.cumulative.elapsed_ns = 90;
    assert!(b.transition(&a).is_err());
    b.cumulative.elapsed_ns = 110; b.cumulative.host_logical_peak_bytes = 4;
    assert!(b.validate().is_err());
}

#[test]
fn interval_peak_is_contained_without_summing_peaks_or_monotonic_live() {
    let mut previous = usage(1, 1, 1);
    previous.cumulative.host_logical_live_bytes = 10;
    previous.cumulative.host_logical_peak_bytes = 20;
    previous.cumulative.elapsed_ns = 100;
    let mut current = usage(2, 2, 3);
    current.delta.host_logical_live_bytes = 15;
    current.delta.host_logical_peak_bytes = 30;
    current.cumulative.host_logical_live_bytes = 5;
    current.cumulative.host_logical_peak_bytes = 20;
    current.cumulative.elapsed_ns = 110;
    assert_eq!(current.validate().unwrap_err().code, ErrorCode::InvalidContract);
    assert!(current.transition(&previous).is_err());
    // The parent observed max(20, 30, 5) = 30, not the sum 50.
    current.cumulative.host_logical_peak_bytes = 30;
    assert_eq!(current.transition(&previous).unwrap(), UsageTransition::New);
    assert_eq!(current.cumulative.host_logical_live_bytes, 5);
    assert_eq!(current.cumulative.host_logical_peak_bytes, 30);
    current.delta.host_logical_live_bytes = 31;
    assert!(current.validate().is_err());
}

#[test]
fn unknown_failure_keeps_original_key_costs_and_cleanup_custody() {
    let mut r = receipt(key()); r.phase = ReadPhase::BindCommit;
    r.request_state = RequestState::OutcomeUnknown;
    r.usage.delta.pg_commit_attempts = 1; r.usage.cumulative.pg_commit_attempts = 1;
    r.usage.unknown_dimensions.insert(id("pg-native-memory"));
    r.usage.retained_reservations = budget();
    r.stop.pg_attempt = PgAttemptState::Unconfirmed; r.stop.local_io = LocalIoState::Stopped;
    r.cleanup = CleanupState::CleanupUnconfirmed;
    r.custody = Some(CustodyTicket { key: key(), record_version: 1, state: CustodyState::ReconcilePending });
    assert!(ReadCall::new(Ok(()), r.clone()).is_err());
    let bypassed = ReadCall { result: Ok(()), receipt: r.clone() };
    assert!(bypassed.require_key(&key()).is_err());
    let error = ReadFailure::unknown(ErrorCode::Cancelled, ReadPhase::BindCommit);
    let call = ReadCall::<ReadResolution>::new(Err(error), r.clone()).unwrap();
    call.require_key(&key()).unwrap();
    assert_eq!(call.result.unwrap_err().trigger_code, Some(ErrorCode::Cancelled));
    assert_eq!(call.receipt.usage.cumulative.pg_commit_attempts, 1);
    assert_eq!(call.receipt.usage.retained_reservations.memory_bytes, 4096);
    assert!(ReadCall::<ReadResolution>::new(Err(ReadFailure::new(ErrorCode::Cancelled, ReadPhase::BindCommit)), r.clone()).is_err());
    r.custody = None;
    assert!(ReadCall::<ReadResolution>::new(Err(ReadFailure::unknown(ErrorCode::Deadline, ReadPhase::BindCommit)), r).is_err());
}

#[test]
fn no_terminal_cleanup_from_absent_or_missing_stop_proof() {
    let b = bound(); let lease = b.exact_lease().unwrap();
    let mut resolution = ReadResolution { key: b.key.clone(),
        custody: CustodyTicket { key: b.key.clone(), record_version: 1, state: CustodyState::ReconcilePending },
        cleanup: CleanupState::CleanupUnconfirmed, stop: StopEvidence::not_started() };
    resolution.validate().unwrap();
    resolution.custody.state = CustodyState::Closed;
    assert!(resolution.validate().is_err());
    resolution.cleanup = CleanupState::ReleasedConfirmed(lease.clone()); resolution.stop = stopped();
    resolution.require_original(&b.key, Some(&lease)).unwrap();
    resolution.require_original(&b.key, None).unwrap();
    let mut other_key = b.key.clone(); other_key.request_id = id("request-other");
    assert!(resolution.require_original(&other_key, None).is_err());
    let mut wrong = lease.clone(); wrong.lease_id = id("lease-other");
    assert!(resolution.require_original(&b.key, Some(&wrong)).is_err());
    resolution.stop.pg_proof = None;
    assert!(resolution.require_original(&b.key, None).is_err());
    resolution.stop = stopped(); resolution.stop.pg_attempt = PgAttemptState::Active;
    assert!(resolution.require_original(&b.key, None).is_err());
    resolution.stop = stopped(); resolution.stop.pg_proof.as_mut().unwrap().no_queued_work = false;
    assert!(resolution.validate().is_err());
    resolution.stop = stopped(); resolution.stop.pg_proof.as_mut().unwrap().backend_pid = 0;
    assert!(resolution.validate().is_err());
    resolution.stop = StopEvidence::not_started(); resolution.cleanup = CleanupState::NotBoundConfirmed;
    resolution.require_original(&b.key, None).unwrap();
    assert!(resolution.require_original(&b.key, Some(&lease)).is_err());
    assert!(resolution.require_original(&b.key, Some(&wrong)).is_err());
    resolution.custody.state = CustodyState::Active;
    resolution.cleanup = CleanupState::Bound(lease.clone()); resolution.stop = stopped();
    resolution.require_original(&b.key, None).unwrap();
    resolution.require_original(&b.key, Some(&lease)).unwrap();
    assert!(resolution.require_original(&b.key, Some(&wrong)).is_err());
    let mut closed_receipt = receipt(b.key.clone());
    closed_receipt.custody = Some(CustodyTicket { key: b.key.clone(), record_version: 1, state: CustodyState::Closed });
    closed_receipt.cleanup = CleanupState::NotBoundConfirmed;
    closed_receipt.stop = StopEvidence::not_started();
    closed_receipt.request_state = RequestState::InFlight;
    assert!(closed_receipt.validate().is_err());
    closed_receipt.request_state = RequestState::NotAttempted;
    closed_receipt.validate().unwrap();
    closed_receipt.request_state = RequestState::Settled;
    closed_receipt.validate().unwrap();
    // A settled bind result still owns a lease; no assertion of PG or cleanup.
    let mut r = receipt(b.key.clone()); r.request_state = RequestState::Settled;
    r.cleanup = CleanupState::Bound(b.exact_lease().unwrap());
    r.custody = Some(CustodyTicket { key: b.key, record_version: 1, state: CustodyState::Active });
    r.validate().unwrap();
    assert!(matches!(r.cleanup, CleanupState::Bound(_)));
}

#[test]
fn malformed_receipts_and_wrong_binding_input_do_not_hide_in_result() {
    let mut r = receipt(key()); r.phase = ReadPhase::Return;
    assert!(ReadCall::<()>::new(Err(ReadFailure::invalid()), r).is_err());
    let r = receipt(key());
    assert!(ReadCall::<()>::new(Err(ReadFailure::unknown(ErrorCode::BackendUnavailable, ReadPhase::Validate)), r).is_err());
    let mut r = receipt(key());
    let mut wrong = key(); wrong.request_id = id("wrong");
    r.custody = Some(CustodyTicket { key: wrong.clone(), record_version: 1, state: CustodyState::Active });
    assert!(r.validate().is_err());
    let r = receipt(key()); let call = ReadCall::new(Ok(()), r).unwrap();
    assert!(call.require_key(&wrong).is_err());
    let read = ReadControl::new(spec(), &request(), clock()).unwrap();
    let input = BindInput { principal: principal(), request: request(), key: wrong };
    assert!(input.validate(&read).is_err());
    let mut bad = usage(1, 2, 1);
    assert!(bad.validate().is_err());
    bad = usage(1, 1, 1); bad.delta.elapsed_ns = 10;
    assert!(bad.validate().is_err());
    let mut proof = stopped(); proof.pg_proof.as_mut().unwrap().backend_start_unix_ms = 0;
    assert!(proof.validate().is_err());
}

struct ShapeOnly;
impl ShapeOnly {
    fn rejected<T>(&self, key: &ReadRequestKey, method: MethodId) -> ReadCall<T> {
        let mut r = receipt(key.clone()); r.method_id = method;
        ReadCall::new(Err(ReadFailure::new(ErrorCode::Unsupported, ReadPhase::Validate)), r).unwrap()
    }
}
impl ControlledCatalogRead for ShapeOnly {
    fn bind(&mut self, input: &BindInput, read: &mut ReadControl) -> ReadCall<BoundRead> {
        input.validate(read).unwrap(); self.rejected(&input.key, MethodId::RcBind)
    }
    fn reauthorize(&mut self, bound: &BoundRead, _: &mut ReadControl) -> ReadCall<AuthEpoch> {
        self.rejected(&bound.key, MethodId::RcReauthorize)
    }
    fn finish(&mut self, key: &ReadRequestKey, _: Option<&ExactLease>, _: &mut CleanupControl) -> ReadCall<ReadResolution> {
        self.rejected(key, MethodId::RcFinish)
    }
    fn reconcile_read(&mut self, key: &ReadRequestKey, _: &mut CleanupControl) -> ReadCall<ReadResolution> {
        self.rejected(key, MethodId::RcReconcile)
    }
}

#[test]
fn controlled_trait_is_object_safe_and_errors_preserve_original_owner() {
    let c = clock(); let mut read = ReadControl::new(spec(), &request(), c.clone()).unwrap();
    let mut clean = cleanup(&read, c);
    let input = BindInput { principal: principal(), request: request(), key: key() };
    let provider: &mut dyn ControlledCatalogRead = &mut ShapeOnly;
    let reply = provider.bind(&input, &mut read);
    reply.require_key(&input.key).unwrap();
    assert_eq!(reply.receipt.method_id.as_str(), "RC-B");
    assert!(reply.result.is_err());
    read.cancel_handle().cancel();
    let finish = provider.finish(&input.key, None, &mut clean);
    finish.require_key(&input.key).unwrap();
    assert_eq!(finish.receipt.method_id.as_str(), "RC-F");
    let reconcile = provider.reconcile_read(&input.key, &mut clean);
    assert_eq!(reconcile.receipt.method_id.as_str(), "RC-R");
    let reauth = provider.reauthorize(&bound(), &mut read);
    assert_eq!(reauth.receipt.method_id.as_str(), "RC-A");
    assert_eq!(MethodId::RqAdmit.as_str(), "RQ-1");
    assert_eq!(MethodId::RqFinish.as_str(), "RQ-2");
    assert_eq!(ReadFailure::unknown(ErrorCode::BackendUnavailable, ReadPhase::ReleaseCommit).code.as_str(), "outcome_unknown");
}
