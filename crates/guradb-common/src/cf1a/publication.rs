use super::wire::{require, require_code, Result};
use super::{digest, Contract};
use serde_json::Value;

pub(crate) fn validate_publication(kind: &str, value: &Value) -> Result<()> {
    match kind {
        "publish_intent" => {
            let artifacts = value["artifact_ids"].as_array().unwrap();
            require(
                artifacts
                    .iter()
                    .enumerate()
                    .all(|(n, item)| !artifacts[..n].contains(item)),
                "duplicate publication artifacts",
            )?;
            require(
                value["expected_generation"].as_u64().unwrap() > 0
                    || value["expected_view_id"] == "",
                "invalid initial publication",
            )?;
            require(
                value["target_view_id"] != value["expected_view_id"],
                "publication must advance view",
            )?;
        }
        "mutation_receipt" => {
            let state = value["state"].as_str().unwrap();
            let result = value["result_id"].as_str().unwrap();
            let error = value["error_code"].as_str().unwrap();
            require(
                (state == "applied"
                    && !result.is_empty()
                    && error == "none"
                    && value["generation"].as_u64().unwrap() > 0)
                    || (state == "rejected"
                        && result.is_empty()
                        && ["conflict", "stale_generation", "idempotency_conflict"]
                            .contains(&error))
                    || (state == "outcome_unknown"
                        && result.is_empty()
                        && error == "outcome_unknown"),
                "invalid receipt state",
            )?;
        }
        "mutation_auth" => {
            let actions = value["actions"].as_array().unwrap();
            require(
                actions
                    .iter()
                    .enumerate()
                    .all(|(n, item)| !actions[..n].contains(item)),
                "duplicate mutation authorization action",
            )?;
        }
        "contract_error" => {
            require(
                value["retryable"] == false || value["code"] == "backend_unavailable",
                "unsafe automatic retry",
            )?;
            require(
                (value["code"] == "outcome_unknown") == (value["reconcile_ref"] != ""),
                "unknown result requires reconciliation",
            )?;
        }
        _ => {}
    }
    Ok(())
}
fn intent_value(intent: &Contract) -> Result<&Value> {
    require(
        ["register_intent", "publish_intent"].contains(&intent.kind()),
        "expected catalog intent",
    )?;
    Ok(intent.value())
}
pub fn check_cas(
    intent: &Contract,
    actual_generation: u64,
    actual_owner_epoch: u64,
    actual_view_id: &str,
    actual_sequence: u64,
) -> Result<()> {
    let value = intent_value(intent)?;
    super::wire::safe_integer(actual_generation, false)?;
    super::wire::safe_integer(actual_owner_epoch, true)?;
    super::wire::safe_integer(actual_sequence, false)?;
    require_code(
        value["owner_epoch"] == actual_owner_epoch,
        "stale publication owner",
        "stale_generation",
    )?;
    require_code(
        value["expected_generation"] == actual_generation,
        "catalog generation conflict",
        "conflict",
    )?;
    if intent.kind() == "publish_intent" {
        require_code(
            value["expected_view_id"] == actual_view_id
                && value["publication_sequence"].as_u64().unwrap() > actual_sequence,
            "publication cannot roll back view",
            "conflict",
        )?;
    }
    Ok(())
}
pub fn check_receipt(intent: &Contract, receipt: &Contract) -> Result<bool> {
    let request = intent_value(intent)?;
    require(
        receipt.kind() == "mutation_receipt",
        "expected mutation receipt",
    )?;
    let value = receipt.value();
    require(
        value["operation_id"] == request["operation_id"]
            && value["request_sha256"] == digest(request),
        "receipt does not identify intent",
    )?;
    if value["state"] == "applied" {
        require(
            value["generation"].as_u64().unwrap()
                == request["expected_generation"].as_u64().unwrap() + 1,
            "receipt generation mismatch",
        )?;
        let target = if intent.kind() == "publish_intent" {
            &request["target_view_id"]
        } else {
            &request["target_revision_id"]
        };
        require(value["result_id"] == *target, "receipt target mismatch")?;
    }
    Ok(value["state"] != "outcome_unknown")
}
pub fn check_replay(original: &Contract, replay: &Contract) -> Result<()> {
    let first = intent_value(original)?;
    let second = intent_value(replay)?;
    require_code(
        first["operation_id"] == second["operation_id"] && digest(first) == digest(second),
        "operation ID reused with different request",
        "conflict",
    )
}

/// Bind each mutation to exactly the immutable read descriptors reviewed by catalog.
pub fn check_target(intent: &Contract, binding: &Contract) -> Result<()> {
    let request = intent_value(intent)?;
    require(
        binding.kind() == "read_descriptors",
        "expected read descriptors target",
    )?;
    let target = binding.value();
    require(
        request["target_descriptors_sha256"] == digest(target),
        "target descriptor content mismatch",
    )?;
    require(
        request["tenant_id"] == target["resource"]["tenant_id"]
            && request["dataset_id"] == target["resource"]["dataset_id"]
            && request["target_revision_id"] == target["revision"]["data_revision_id"],
        "target resource mismatch",
    )?;
    if intent.kind() == "register_intent" {
        require(
            request["revision_sha256"] == target["revision"]["content_sha256"],
            "registered revision mismatch",
        )?;
    } else {
        let mut expected: Vec<_> = request["artifact_ids"].as_array().unwrap().iter().collect();
        let mut actual: Vec<_> = target["view"]["required_artifact_ids"]
            .as_array()
            .unwrap()
            .iter()
            .collect();
        expected.sort_by_key(|v| v.as_str());
        actual.sort_by_key(|v| v.as_str());
        require(
            request["target_revision_sha256"] == target["revision"]["content_sha256"]
                && request["target_view_sha256"] == target["view"]["descriptor_sha256"]
                && request["target_view_id"] == target["view"]["read_view_id"]
                && target["view"]["publication_generation"].as_u64().unwrap()
                    == request["expected_generation"].as_u64().unwrap() + 1
                && request["publication_sequence"] == target["view"]["publication_sequence"]
                && expected == actual,
            "publication target mismatch",
        )?;
    }
    Ok(())
}

pub fn check_mutation_auth(
    intent: &Contract,
    authorization: &Contract,
    now_unix_ms: u64,
    current_policy_epoch: u64,
    reconcile: bool,
) -> Result<()> {
    let request = intent_value(intent)?;
    require(
        authorization.kind() == "mutation_auth",
        "expected mutation authorization",
    )?;
    let auth = authorization.value();
    super::wire::safe_integer(now_unix_ms, false)?;
    super::wire::safe_integer(current_policy_epoch, true)?;
    let action = if reconcile {
        "reconcile"
    } else if intent.kind() == "register_intent" {
        "register"
    } else {
        "publish"
    };
    require_code(
        auth["tenant_id"] == request["tenant_id"]
            && auth["dataset_id"] == request["dataset_id"]
            && auth["actions"]
                .as_array()
                .unwrap()
                .contains(&Value::String(action.into())),
        "unauthorized mutation scope",
        "unauthorized",
    )?;
    require_code(
        auth["policy_epoch"] == current_policy_epoch,
        "mutation authorization revoked",
        "revoked",
    )?;
    require_code(
        now_unix_ms < auth["expires_unix_ms"].as_u64().unwrap(),
        "mutation authorization expired",
        "expired_context",
    )
}
