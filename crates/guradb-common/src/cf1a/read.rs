use super::wire::{require, require_code, Result};
use super::{digest, Contract, ObjectRef, CAPABILITIES};
use serde_json::Value;

pub(super) fn array(value: &Value) -> &[Value] {
    value.as_array().unwrap()
}
pub(super) fn number(value: &Value) -> u64 {
    value.as_u64().unwrap()
}
pub(super) fn unique(values: &[Value]) -> bool {
    values
        .iter()
        .enumerate()
        .all(|(n, item)| !values[..n].contains(item))
}
pub(super) fn ids(values: &[Value], name: &str) -> Vec<Value> {
    values.iter().map(|item| item[name].clone()).collect()
}
pub(super) fn same_set(left: &[Value], right: &[Value]) -> bool {
    unique(left)
        && unique(right)
        && left.len() == right.len()
        && left.iter().all(|item| right.contains(item))
}
pub(crate) fn without(value: &Value, key: &str) -> Value {
    let mut object = value.as_object().unwrap().clone();
    object.remove(key);
    Value::Object(object)
}
pub(super) fn validate_object(reference: &Value) -> Result<()> {
    let integrity = &reference["integrity"];
    require(
        !reference["key"].as_str().unwrap().is_empty(),
        "empty object key",
    )?;
    if integrity["mode"] == "whole_sha256" {
        require(
            integrity["block_size"] == 0
                && array(&integrity["block_sha256"]).is_empty()
                && integrity["proof_ref"] == "",
            "whole digest cannot claim blocks",
        )?;
    } else {
        let width = number(&integrity["block_size"]);
        require(
            width > 0 && integrity["proof_ref"] != "",
            "missing trusted block proof",
        )?;
        require(
            array(&integrity["block_sha256"]).len() as u64
                == number(&reference["size_bytes"]).div_ceil(width),
            "incomplete block table",
        )?;
    }
    Ok(())
}

/// Structural strong-range check. The storage port still verifies proof authority.
pub fn validate_range(reference: &ObjectRef, offset: u64, length: u64) -> Result<()> {
    let value = serde_json::to_value(reference).unwrap();
    super::wire::validate_named(&value, "ObjectRef")?;
    validate_object(&value)?;
    let size = reference.size_bytes;
    require(
        offset < size && length > 0 && length <= size - offset,
        "invalid object range",
    )?;
    if reference.integrity.mode == "whole_sha256" {
        require(
            offset == 0 && length == size,
            "whole digest cannot verify partial range",
        )?;
    } else {
        let width = reference.integrity.block_size;
        require(
            offset.is_multiple_of(width)
                && ((offset + length).is_multiple_of(width) || offset + length == size),
            "range must cover complete blocks",
        )?;
    }
    Ok(())
}
pub(super) fn canonical_locator(reference: &Value) -> Vec<u8> {
    super::canonical(&serde_json::json!([
        reference["backend_id"],
        reference["bucket"],
        reference["key"],
        reference["version"]
    ]))
}
fn score(value: &Value) -> f64 {
    f64::from_bits(u64::from_str_radix(value.as_str().unwrap(), 16).unwrap())
}
pub(super) fn field_invariants(fields: &[Value]) -> Result<()> {
    require(
        unique(&ids(fields, "field_id")) && unique(&ids(fields, "name")),
        "duplicate field identity",
    )?;
    for role in ["logical_id", "record_version"] {
        let chosen: Vec<_> = fields
            .iter()
            .filter(|field| field["role"] == role)
            .collect();
        require(
            chosen.len() == 1 && chosen[0]["type"] == "text" && chosen[0]["nullable"] == false,
            "missing stable ID/version field",
        )?;
    }
    Ok(())
}
fn validate_batch(value: &Value) -> Result<()> {
    let fields = array(&value["fields"]);
    field_invariants(fields)?;
    require(
        value["content_sha256"] == digest(&without(value, "content_sha256")),
        "batch digest mismatch",
    )?;
    let mut identities = Vec::new();
    for row in array(&value["rows"]) {
        identities.push(row["record_id"].clone());
        require(
            array(&row["cells"]).len() == fields.len(),
            "row width mismatch",
        )?;
        for (field, cell) in fields.iter().zip(array(&row["cells"])) {
            require(
                cell["type"] == field["type"]
                    || (field["nullable"] == true && cell["type"] == "null"),
                "cell type mismatch",
            )?;
            if field["role"] == "logical_id" || field["role"] == "record_version" {
                let name = if field["role"] == "logical_id" {
                    "record_id"
                } else {
                    "record_version"
                };
                require(
                    cell["value"] == row[name],
                    "record identity/version mapping mismatch",
                )?;
            }
        }
    }
    require(unique(&identities), "duplicate logical record")?;
    if value["ordering"] == "logical_id_asc" {
        require(
            identities
                .windows(2)
                .all(|pair| pair[0].as_str() < pair[1].as_str()),
            "incorrect declared order",
        )?;
    }
    require(
        value["truncated"] == false || value["last"] == true,
        "truncation must end stream",
    )?;
    Ok(())
}
pub(crate) fn validate_read(kind: &str, value: &Value) -> Result<()> {
    match kind {
        "read_binding" => super::binding::validate_binding(value)?,
        "read_descriptors" => super::binding::validate_descriptors(value)?,
        "read_batch" => validate_batch(value)?,
        "bind_request" => {
            require(
                number(&value["timeout_ms"]) <= 30000
                    && number(&value["budget"]["top_k"]) <= number(&value["budget"]["candidates"]),
                "invalid bind budget/deadline",
            )?;
            require(
                (value["view_mode"] == "published") == (value["read_view_id"] == ""),
                "invalid bind view selector",
            )?;
            if value["view_mode"] == "explicit" {
                super::wire::validate_named(&value["read_view_id"], "FixedId")?;
            }
        }
        "index_query" => {
            require(
                number(&value["top_k"]) <= number(&value["candidate_limit"])
                    && number(&value["candidate_limit"]) <= 1024,
                "invalid index query limit",
            )?;
            require(
                unique(array(&value["allowed_record_ids"]))
                    && (value["filter_mode"] == "ids"
                        || array(&value["allowed_record_ids"]).is_empty()),
                "invalid index query filter",
            )?;
            require(
                (value["kind"] == "bm25"
                    && value["metric"] == "bm25"
                    && value["dimension"] == 1
                    && value["query_text"] != ""
                    && array(&value["query_vector_f64_hex"]).is_empty())
                    || (value["kind"] == "exact_vector"
                        && value["metric"] == "squared_l2"
                        && value["analyzer"] == "none"
                        && value["query_text"] == ""
                        && array(&value["query_vector_f64_hex"]).len() as u64
                            == number(&value["dimension"])),
                "incompatible index query",
            )?;
            require(
                array(&value["query_vector_f64_hex"])
                    .iter()
                    .all(|item| score(item).abs() <= 1e150),
                "query vector outside distance bounds",
            )?;
        }
        "candidate_batch" => {
            require(
                value["complete"] == true,
                "partial candidate coverage is not certified",
            )?;
            require(
                (value["metric"] == "squared_l2") == (value["score_order"] == "ascending"),
                "wrong candidate score order",
            )?;
            let rows = array(&value["rows"]);
            require(unique(&ids(rows, "record_id")), "duplicate candidate ID")?;
            for row in rows {
                validate_object(&row["locator"]["object"])?;
            }
            require(
                value["metric"] != "squared_l2"
                    || rows.iter().all(|row| score(&row["score_f64_hex"]) >= 0.0),
                "negative squared distance",
            )?;
            require(
                rows.windows(2).all(|pair| {
                    let left = score(&pair[0]["score_f64_hex"]);
                    let right = score(&pair[1]["score_f64_hex"]);
                    (left == right && pair[0]["record_id"].as_str() < pair[1]["record_id"].as_str())
                        || (left != right
                            && if value["score_order"] == "ascending" {
                                left < right
                            } else {
                                left > right
                            })
                }),
                "candidate rows violate score/tie order",
            )?;
        }
        "reader_config" => {
            require(
                number(&value["max_envelope_bytes"]) <= 1 << 20
                    && number(&value["max_batch_rows"]) <= 1024
                    && number(&value["max_ttl_ms"]) <= 30000,
                "config exceeds certified bounds",
            )?;
            let expected: Vec<Value> = CAPABILITIES
                .iter()
                .map(|item| Value::String((*item).into()))
                .collect();
            require_code(
                same_set(array(&value["capabilities"]), &expected),
                "config cannot weaken contract",
                "unsupported_capability",
            )?;
        }
        _ => {}
    }
    Ok(())
}
/// current_policy_epoch must come from a successful current catalog check.
pub fn validate_access(
    binding: &Contract,
    now_unix_ms: u64,
    current_policy_epoch: u64,
) -> Result<()> {
    require(binding.kind() == "read_binding", "expected read binding")?;
    let context = &binding.value()["context"];
    super::wire::safe_integer(now_unix_ms, false)?;
    super::wire::safe_integer(current_policy_epoch, true)?;
    require(
        now_unix_ms >= number(&context["bound_at_unix_ms"]),
        "invalid current time",
    )?;
    require_code(
        current_policy_epoch == number(&context["auth"]["policy_epoch"]),
        "authorization revoked",
        "revoked",
    )?;
    require_code(
        now_unix_ms < number(&context["deadline_unix_ms"]),
        "query deadline reached",
        "deadline",
    )
}
pub fn validate_batch_for(binding: &Contract, batch: &Contract) -> Result<()> {
    require(
        binding.kind() == "read_binding" && batch.kind() == "read_batch",
        "wrong contract kinds",
    )?;
    let resource = &binding.value()["resource"];
    let value = batch.value();
    require(
        value["context_sha256"] == binding.sha256()
            && value["schema_id"] == resource["schema_id"]
            && value["schema_version"] == resource["schema_version"]
            && value["fields"] == resource["fields"],
        "batch context/schema mismatch",
    )?;
    let revision = &binding.value()["revision"];
    let derived = array(&revision["sources"]).iter().any(|source| {
        array(&source["field_mapping"])
            .iter()
            .any(|item| item["transform"] == "revision_version")
    });
    require(
        !derived
            || array(&value["rows"])
                .iter()
                .all(|row| row["record_version"] == revision["data_revision_id"]),
        "derived record version mismatch",
    )?;
    let budget = &binding.value()["context"]["budget"];
    require_code(
        [
            "object_requests",
            "object_bytes",
            "memory_bytes",
            "output_bytes",
        ]
        .iter()
        .all(|name| number(&value["usage"][name]) <= number(&budget[name])),
        "batch exceeds budget",
        "resource_limit",
    )
}

pub fn validate_candidates_for(
    binding: &Contract,
    query: &Contract,
    batch: &Contract,
) -> Result<()> {
    require(
        binding.kind() == "read_binding"
            && query.kind() == "index_query"
            && batch.kind() == "candidate_batch",
        "wrong candidate contract kinds",
    )?;
    let request = query.value();
    let response = batch.value();
    let artifact = array(&binding.value()["indexes"])
        .iter()
        .find(|item| item["artifact_id"] == response["artifact_id"]);
    require(
        artifact.is_some_and(|index| {
            response["metric"] == index["metric"]
                && response["context_sha256"] == binding.sha256()
                && request["context_sha256"] == binding.sha256()
                && request["artifact_id"] == response["artifact_id"]
                && response["index_query_sha256"] == query.sha256()
                && [
                    "kind",
                    "model_id",
                    "model_version",
                    "dimension",
                    "metric",
                    "analyzer",
                    "configuration_sha256",
                    "processing_version",
                ]
                .iter()
                .all(|name| request[name] == index[name])
        }),
        "candidate binding/artifact mismatch",
    )?;
    let artifact = artifact.unwrap();
    let budget = &binding.value()["context"]["budget"];
    require_code(
        array(&response["rows"]).len() as u64 <= number(&request["top_k"])
            && number(&request["top_k"]) <= number(&budget["top_k"])
            && number(&request["candidate_limit"]) <= number(&budget["candidates"]),
        "candidate budget exceeded",
        "resource_limit",
    )?;
    for row in array(&response["rows"]) {
        require(
            request["filter_mode"] == "all"
                || array(&request["allowed_record_ids"]).contains(&row["record_id"]),
            "candidate violates filter",
        )?;
        require(
            array(&artifact["source_version_ids"]).contains(&row["locator"]["source_version_id"])
                && array(&binding.value()["revision"]["objects"])
                    .contains(&row["locator"]["object"]),
            "candidate locator outside fixed input",
        )?;
    }
    require_code(
        [
            "object_requests",
            "object_bytes",
            "memory_bytes",
            "output_bytes",
        ]
        .iter()
        .all(|name| number(&response["usage"][name]) <= number(&budget[name])),
        "candidate usage exceeds budget",
        "resource_limit",
    )
}
