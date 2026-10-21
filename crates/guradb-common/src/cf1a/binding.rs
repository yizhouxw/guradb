//! Fixed resource/source/index/auth/pin consistency checks.
use super::digest;
use super::read::{
    array, canonical_locator, field_invariants, ids, number, same_set, unique, validate_object,
    without,
};
use super::wire::{require, require_code, Result};
use serde_json::Value;
use std::collections::BTreeSet;

pub(super) fn validate_descriptors(value: &Value) -> Result<()> {
    let resource = &value["resource"];
    let revision = &value["revision"];
    let view = &value["view"];
    let fields = array(&resource["fields"]);
    field_invariants(fields)?;
    require(
        resource["schema_sha256"] == digest(&resource["fields"]),
        "schema digest mismatch",
    )?;
    require(
        revision["content_sha256"] == digest(&without(revision, "content_sha256")),
        "revision digest mismatch",
    )?;
    require(
        view["descriptor_sha256"] == digest(&without(view, "descriptor_sha256")),
        "view digest mismatch",
    )?;
    for name in ["dataset_id", "schema_id", "schema_version"] {
        require(
            resource[name] == revision[name],
            "resource/schema binding mismatch",
        )?;
    }
    require(
        revision["data_revision_id"] == view["data_revision_id"],
        "revision mismatch",
    )?;
    require(
        unique(array(&revision["parent_revision_ids"]))
            && !array(&revision["parent_revision_ids"]).contains(&revision["data_revision_id"]),
        "invalid revision parents",
    )?;
    let sources = array(&revision["sources"]);
    let source_ids = ids(sources, "source_version_id");
    require(
        unique(&source_ids) && unique(&ids(sources, "source_id")),
        "duplicate source identity",
    )?;
    let field_types: BTreeSet<_> = fields
        .iter()
        .map(|field| (number(&field["field_id"]), field["type"].as_str().unwrap()))
        .collect();
    let mut identity_strategies = std::collections::BTreeMap::new();
    for source in sources {
        require(
            (source["format"] == "manifest" && source["format_version"] == "1")
                || (source["format"] == "iceberg" && source["format_version"] == "2"),
            "unsupported source format version",
        )?;
        require(
            source["resource_schema_sha256"] == resource["schema_sha256"],
            "source schema mismatch",
        )?;
        let mappings = array(&source["field_mapping"]);
        let mapping_types: BTreeSet<_> = mappings
            .iter()
            .map(|item| {
                (
                    number(&item["resource_field_id"]),
                    item["type"].as_str().unwrap(),
                )
            })
            .collect();
        require(
            unique(&ids(mappings, "resource_field_id")) && mapping_types == field_types,
            "incomplete source field mapping",
        )?;
        let mut source_types = std::collections::BTreeMap::new();
        for item in mappings {
            let role = fields
                .iter()
                .find(|field| field["field_id"] == item["resource_field_id"])
                .unwrap()["role"]
                .as_str()
                .unwrap();
            let transform = item["transform"].as_str().unwrap();
            require(
                (transform == "identity"
                    && number(&item["source_field_id"]) > 0
                    && item["source_type"] == item["type"])
                    || (transform == "key_v1"
                        && number(&item["source_field_id"]) > 0
                        && ["int8", "text"].contains(&item["source_type"].as_str().unwrap())
                        && item["type"] == "text"
                        && role == "logical_id")
                    || (transform == "revision_version"
                        && item["source_field_id"] == 0
                        && item["source_type"] == "none"
                        && item["type"] == "text"
                        && role == "record_version"),
                "unsupported identity transform",
            )?;
            if ["logical_id", "record_version"].contains(&role) {
                let strategy = (
                    transform.to_string(),
                    item["source_type"].as_str().unwrap().to_string(),
                );
                require(
                    identity_strategies
                        .get(role)
                        .is_none_or(|prior| *prior == strategy),
                    "mixed source identity strategies",
                )?;
                identity_strategies.insert(role.to_string(), strategy);
            }
            if number(&item["source_field_id"]) > 0 {
                require(
                    source_types
                        .get(&number(&item["source_field_id"]))
                        .is_none_or(|kind| *kind == item["source_type"]),
                    "conflicting source field type",
                )?;
                source_types.insert(
                    number(&item["source_field_id"]),
                    item["source_type"].clone(),
                );
            }
        }
        validate_object(&source["metadata"])?;
    }
    let mut objects = Vec::new();
    for reference in array(&revision["objects"]) {
        validate_object(reference)?;
        objects.push(serde_json::json!([
            reference["backend_id"],
            reference["bucket"],
            reference["key"],
            reference["version"]
        ]));
    }
    require(unique(&objects), "duplicate immutable object")?;
    let requirements = array(&view["index_requirements"]);
    require(
        same_set(
            &ids(requirements, "artifact_id"),
            array(&view["required_artifact_ids"]),
        ),
        "index requirement mismatch",
    )?;
    let mut artifact_ids = Vec::new();
    for artifact in array(&value["indexes"]) {
        artifact_ids.push(artifact["artifact_id"].clone());
        require(
            artifact["data_revision_id"] == revision["data_revision_id"]
                && artifact["schema_sha256"] == resource["schema_sha256"],
            "index version mismatch",
        )?;
        require(
            same_set(array(&artifact["source_version_ids"]), &source_ids),
            "index coverage gap",
        )?;
        let expected = requirements
            .iter()
            .find(|item| item["artifact_id"] == artifact["artifact_id"]);
        require(
            expected.is_some_and(|item| {
                item.as_object()
                    .unwrap()
                    .iter()
                    .all(|(name, required)| artifact[name] == *required)
            }),
            "index model requirement mismatch",
        )?;
        let shard_ids: Vec<Value> = array(&artifact["shards"])
            .iter()
            .map(|shard| {
                serde_json::json!([
                    shard["backend_id"],
                    shard["bucket"],
                    shard["key"],
                    shard["version"]
                ])
            })
            .collect();
        require(unique(&shard_ids), "duplicate index shard")?;
        require(artifact["deletion_watermark"] == 0, "deletes not certified")?;
        require(
            number(&artifact["shard_count"]) == array(&artifact["shards"]).len() as u64,
            "missing index shard",
        )?;
        require(
            artifact["reader_capabilities"] == serde_json::json!(["fixed_read"]),
            "unsupported index reader capability",
        )?;
        require(
            (artifact["kind"] == "bm25"
                && artifact["metric"] == "bm25"
                && artifact["dimension"] == 1)
                || (artifact["kind"] == "exact_vector"
                    && artifact["metric"] == "squared_l2"
                    && artifact["analyzer"] == "none"),
            "incompatible model/metric/analyzer",
        )?;
        for shard in array(&artifact["shards"]) {
            validate_object(shard)?;
        }
    }
    require(
        same_set(&artifact_ids, array(&view["required_artifact_ids"])),
        "index binding mismatch",
    )?;
    let mut references = Vec::new();
    references.extend(sources.iter().map(|source| &source["metadata"]));
    references.extend(array(&revision["objects"]));
    references.extend(
        array(&value["indexes"])
            .iter()
            .flat_map(|artifact| array(&artifact["shards"])),
    );
    let mut immutable = std::collections::BTreeMap::new();
    for reference in references {
        let locator = canonical_locator(reference);
        require(
            immutable
                .get(&locator)
                .is_none_or(|prior| *prior == reference),
            "contradictory immutable object descriptors",
        )?;
        immutable.insert(locator, reference);
    }
    Ok(())
}

pub(super) fn validate_binding(value: &Value) -> Result<()> {
    validate_descriptors(value)?;
    let resource = &value["resource"];
    let revision = &value["revision"];
    let view = &value["view"];
    let context = &value["context"];
    require(
        ["dataset_id", "schema_id", "schema_version"]
            .iter()
            .all(|name| context[name] == resource[name]),
        "context resource/schema mismatch",
    )?;
    require(
        context["tenant_id"] == resource["tenant_id"]
            && resource["tenant_id"] == context["auth"]["tenant_id"],
        "tenant mismatch",
    )?;
    require(
        context["auth"]["dataset_id"] == resource["dataset_id"],
        "authorization scope mismatch",
    )?;
    require(
        revision["data_revision_id"] == context["data_revision_id"]
            && context["data_revision_id"] == context["pin"]["data_revision_id"],
        "context revision mismatch",
    )?;
    require(
        view["read_view_id"] == context["read_view_id"]
            && context["read_view_id"] == context["pin"]["read_view_id"],
        "context view mismatch",
    )?;
    let sources = array(&revision["sources"]);
    require(
        same_set(
            &ids(sources, "source_version_id"),
            array(&context["source_version_ids"]),
        ),
        "source binding mismatch",
    )?;
    require(
        same_set(
            array(&context["artifact_ids"]),
            array(&view["required_artifact_ids"]),
        ),
        "context index mismatch",
    )?;
    let deadline = number(&context["deadline_unix_ms"]);
    let bound = number(&context["bound_at_unix_ms"]);
    let ttl = number(&context["remaining_ttl_ms"]);
    require(
        ttl <= 30000 && deadline > bound && deadline - bound == ttl,
        "invalid remaining deadline",
    )?;
    require_code(
        number(&context["pin"]["expires_unix_ms"]) >= deadline
            && number(&context["auth"]["expires_unix_ms"]) >= deadline,
        "pin/auth expires before execution",
        "expired_context",
    )?;
    require_code(
        sources.iter().all(|source| {
            number(&source["protected_until_unix_ms"]) >= number(&context["pin"]["expires_unix_ms"])
        }),
        "source retention cannot protect pin",
        "expired_context",
    )?;
    require(
        number(&context["budget"]["top_k"]) <= number(&context["budget"]["candidates"]),
        "top-k exceeds candidate budget",
    )
}
