use super::*;
use serde::{
    de::value::{BytesDeserializer, Error as DeError, F64Deserializer},
    Deserialize,
};
use serde_json::{json, Value};

fn golden() -> Vec<Value> {
    serde_json::from_str(include_str!("../../../../api/cf1a/golden.json")).unwrap()
}
fn contract(index: usize) -> Contract {
    decode(&serde_json::to_vec(&golden()[index]).unwrap()).unwrap()
}
fn changed(
    index: usize,
    edit: impl FnOnce(&mut Value),
    rehash: bool,
) -> Result<Contract, ContractFailure> {
    let mut document = golden()[index].clone();
    let value = document["payload"]
        .as_object_mut()
        .unwrap()
        .values_mut()
        .next()
        .unwrap();
    edit(value);
    if rehash && (index == 0 || index == 11) {
        value["revision"]["content_sha256"] =
            digest(&read::without(&value["revision"], "content_sha256")).into();
        value["view"]["descriptor_sha256"] =
            digest(&read::without(&value["view"], "descriptor_sha256")).into();
    }
    if rehash && index == 1 {
        value["content_sha256"] = digest(&read::without(value, "content_sha256")).into();
    }
    decode(&serde_json::to_vec(&document).unwrap())
}
#[test]
fn golden_roundtrip() {
    for value in golden() {
        let decoded = decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert_eq!(decoded.document(), &value);
        assert_eq!(decoded.envelope().contract_version, VERSION);
        assert_eq!(
            decode(decoded.encoded()).unwrap().sha256(),
            decoded.sha256()
        );
    }
    let schema: Value =
        serde_json::from_str(include_str!("../../../../api/cf1a/schema.json")).unwrap();
    assert_eq!(
        schema["$defs"]["ObjectRef"]["properties"]["version"]["minLength"],
        1
    );
}
#[test]
fn shared_rejections_and_strict_json() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("../../../../api/cf1a/rejections.json")).unwrap();
    for case in cases {
        let error = decode(case["raw"].as_str().unwrap().as_bytes()).unwrap_err();
        assert_eq!(
            error.code,
            case["code"].as_str().unwrap(),
            "{}",
            case["name"]
        );
    }
    for raw in [
        b"null".as_slice(),
        b"true",
        b"1.5",
        b"-1",
        b"\"text\"",
        b"[]",
        b"{",
        b"NaN",
    ] {
        assert!(decode(raw).is_err());
    }
    let nested = format!("{}0{}", "[".repeat(65), "]".repeat(65));
    assert!(decode(nested.as_bytes()).is_err());
    assert!(decode(&vec![b' '; (1 << 20) + 1]).is_err());
    assert!(super::json::Strict::deserialize(BytesDeserializer::<DeError>::new(b"bytes")).is_err());
    assert!(
        super::json::Strict::deserialize(F64Deserializer::<DeError>::new(f64::INFINITY)).is_err()
    );
}
#[test]
fn source_fields_retention_integrity_and_binding() {
    let failures = [
        ("/resource/fields/1/field_id", json!(1)),
        ("/resource/fields/1/role", json!("value")),
        ("/resource/schema_sha256", json!("b".repeat(64))),
        ("/context/dataset_id", json!("other")),
        ("/context/tenant_id", json!("other")),
        ("/context/auth/dataset_id", json!("other")),
        ("/context/pin/data_revision_id", json!("other")),
        ("/context/pin/read_view_id", json!("other")),
        ("/revision/parent_revision_ids", json!(["revision-1"])),
        ("/context/source_version_ids", json!(["other"])),
        ("/context/deadline_unix_ms", json!(32000)),
        ("/context/auth/expires_unix_ms", json!(1000)),
        ("/revision/sources/0/format_version", json!("2")),
        (
            "/revision/sources/0/resource_schema_sha256",
            json!("b".repeat(64)),
        ),
        ("/revision/sources/0/field_mapping/0/type", json!("int8")),
        ("/revision/sources/0/protected_until_unix_ms", json!(99999)),
        ("/indexes/0/data_revision_id", json!("other")),
        ("/indexes/0/source_version_ids", json!(["other"])),
        ("/view/index_requirements", json!([])),
        ("/indexes/0/model_version", json!("other")),
        ("/indexes/0/deletion_watermark", json!(1)),
        ("/indexes/0/shard_count", json!(2)),
        ("/indexes/0/reader_capabilities", json!(["other"])),
        ("/indexes/0/kind", json!("bm25")),
        ("/context/artifact_ids", json!([])),
        ("/context/budget/top_k", json!(100)),
        ("/revision/objects/0/size_bytes", json!(9)),
        (
            "/revision/sources/0/field_mapping/0/transform",
            json!("revision_version"),
        ),
    ];
    for (path, replacement) in failures {
        assert!(
            changed(
                0,
                |value| *value.pointer_mut(path).unwrap() = replacement,
                true
            )
            .is_err(),
            "{path}"
        );
    }
    assert!(changed(
        0,
        |value| value["revision"]["content_sha256"] = "b".repeat(64).into(),
        false
    )
    .is_err());
    assert!(changed(
        0,
        |value| value["view"]["descriptor_sha256"] = "b".repeat(64).into(),
        false
    )
    .is_err());
    let transformed = changed(
        0,
        |value| {
            let mappings = value["revision"]["sources"][0]["field_mapping"]
                .as_array_mut()
                .unwrap();
            mappings[0]["source_type"] = "int8".into();
            mappings[0]["transform"] = "key_v1".into();
            mappings[1]["source_field_id"] = 0.into();
            mappings[1]["source_type"] = "none".into();
            mappings[1]["transform"] = "revision_version".into();
        },
        true,
    )
    .unwrap();
    assert!(read::validate_batch_for(&transformed, &contract(1)).is_err());
    changed(
        0,
        |value| {
            value["indexes"][0]["kind"] = "bm25".into();
            value["indexes"][0]["metric"] = "bm25".into();
            value["indexes"][0]["dimension"] = 1.into();
            value["view"]["index_requirements"][0]["metric"] = "bm25".into();
            value["view"]["index_requirements"][0]["dimension"] = 1.into();
            value["revision"]["sources"][0]["format"] = "iceberg".into();
            value["revision"]["sources"][0]["format_version"] = "2".into();
        },
        true,
    )
    .unwrap();
    for section in ["objects", "sources"] {
        assert!(changed(
            0,
            |value| {
                let values = value["revision"][section].as_array_mut().unwrap();
                values.push(values[0].clone());
            },
            true
        )
        .is_err());
    }
    assert!(changed(
        0,
        |value| {
            let index = &mut value["indexes"][0];
            index["shard_count"] = 2.into();
            let shard = index["shards"][0].clone();
            index["shards"].as_array_mut().unwrap().push(shard);
        },
        true
    )
    .is_err());
}
#[test]
fn strong_whole_and_block_ranges() {
    let reference = contract(0).value()["revision"]["objects"][0].clone();
    let mut object: ObjectRef = serde_json::from_value(reference).unwrap();
    assert_eq!(
        object.immutable_locator(),
        (
            "local_simulation",
            "fixture",
            "固定/data.parquet",
            "object-v1"
        )
    );
    read::validate_range(&object, 0, 8).unwrap();
    for (offset, length) in [(0, 4), (1, 7), (0, 0), (8, 1), (0, 9)] {
        assert!(read::validate_range(&object, offset, length).is_err());
    }
    object.integrity.mode = "block_sha256".into();
    object.integrity.block_size = 3;
    object.integrity.block_sha256 = vec!["a".repeat(64); 3];
    object.integrity.proof_ref = "trusted-blocks".into();
    for (offset, length) in [(0, 3), (3, 3), (6, 2), (0, 8)] {
        read::validate_range(&object, offset, length).unwrap();
    }
    assert!(read::validate_range(&object, 1, 3).is_err());
    object.integrity.block_size = 0;
    assert!(read::validate_range(&object, 0, 8).is_err());
    object.integrity.mode = "whole_sha256".into();
    assert!(read::validate_range(&object, 0, 8).is_err());
}
#[test]
fn typed_batches_budgets_and_current_authorization() {
    let binding = contract(0);
    let batch = contract(1);
    read::validate_batch_for(&binding, &batch).unwrap();
    read::validate_access(&binding, 1001, 1).unwrap();
    for (now, epoch) in [(999, 1), (1001, 2), (31000, 1)] {
        assert!(read::validate_access(&binding, now, epoch).is_err());
    }
    assert!(read::validate_access(&batch, 1001, 1).is_err());
    assert!(read::validate_batch_for(&batch, &binding).is_err());
    for (path, replacement) in [
        ("/rows/0/record_version", json!("other")),
        ("/rows/0/cells/2", json!({"type":"bool","value":false})),
        ("/truncated", json!(true)),
        ("/context_sha256", json!("b".repeat(64))),
        ("/usage/memory_bytes", json!(4097)),
    ] {
        let result = changed(
            1,
            |value| {
                *value.pointer_mut(path).unwrap() = replacement;
                if path == "/truncated" {
                    value["last"] = false.into();
                }
            },
            true,
        );
        assert!(result.is_err() || read::validate_batch_for(&binding, &result.unwrap()).is_err());
    }
    assert!(changed(
        1,
        |value| value["content_sha256"] = "b".repeat(64).into(),
        false
    )
    .is_err());
    assert!(changed(
        1,
        |value| {
            value["rows"][0]["cells"].as_array_mut().unwrap().pop();
        },
        true
    )
    .is_err());
    assert!(changed(
        1,
        |value| value["rows"].as_array_mut().unwrap().reverse(),
        true
    )
    .is_err());
    changed(
        1,
        |value| {
            value["ordering"] = "unspecified".into();
            value["truncated"] = true.into();
        },
        true,
    )
    .unwrap();
    assert!(changed(5, |value| value["max_ttl_ms"] = 30001.into(), false).is_err());
    assert!(changed(
        5,
        |value| value["capabilities"] = json!(["fixed_read"]),
        false
    )
    .is_err());
    changed(
        7,
        |value| {
            value["view_mode"] = "explicit".into();
            value["read_view_id"] = "view-1".into();
        },
        false,
    )
    .unwrap();
    assert!(changed(7, |value| value["read_view_id"] = "wrong".into(), false).is_err());
}
#[test]
fn mutation_intent_receipt_fencing_reconciliation_and_authorization() {
    let register = contract(2);
    let publish = contract(3);
    let receipt = contract(4);
    let auth = contract(9);
    publication::check_cas(&register, 0, 1, "", 0).unwrap();
    publication::check_cas(&publish, 1, 1, "", 0).unwrap();
    publication::check_replay(&publish, &publish).unwrap();
    for (generation, owner, prior, sequence) in [
        (1, 2, "", 0),
        (2, 1, "", 0),
        (1, 1, "new", 0),
        (1, 1, "", 1),
    ] {
        assert!(publication::check_cas(&publish, generation, owner, prior, sequence).is_err());
    }
    assert!(publication::check_replay(
        &publish,
        &changed(3, |value| value["owner_epoch"] = 2.into(), false).unwrap()
    )
    .is_err());
    assert!(publication::check_replay(&contract(0), &publish).is_err());
    assert!(publication::check_receipt(&publish, &receipt).unwrap());
    assert!(publication::check_receipt(&publish, &auth).is_err());
    for (state, error) in [
        ("rejected", "conflict"),
        ("outcome_unknown", "outcome_unknown"),
    ] {
        let response = changed(
            4,
            |value| {
                value["state"] = state.into();
                value["error_code"] = error.into();
                value["result_id"] = "".into();
            },
            false,
        )
        .unwrap();
        assert_eq!(
            publication::check_receipt(&publish, &response).unwrap(),
            state != "outcome_unknown"
        );
    }
    let registered = changed(
        4,
        |value| {
            value["operation_id"] = register.value()["operation_id"].clone();
            value["request_sha256"] = digest(register.value()).into();
            value["generation"] = 1.into();
            value["result_id"] = "revision-1".into();
        },
        false,
    )
    .unwrap();
    publication::check_receipt(&register, &registered).unwrap();
    for intent in [&register, &publish] {
        publication::check_target(intent, &contract(11)).unwrap();
        publication::check_mutation_auth(intent, &auth, 1001, 1, false).unwrap();
        publication::check_mutation_auth(intent, &auth, 1001, 1, true).unwrap();
    }
    assert!(publication::check_target(
        &publish,
        &changed(
            0,
            |value| value["view"]["publication_generation"] = 100.into(),
            true
        )
        .unwrap()
    )
    .is_err());
    assert!(publication::check_target(&publish, &auth).is_err());
    for (now, epoch) in [(1001, 2), (100000, 1)] {
        assert!(publication::check_mutation_auth(&publish, &auth, now, epoch, false).is_err());
    }
    assert!(publication::check_mutation_auth(
        &publish,
        &changed(9, |value| value["actions"] = json!(["register"]), false).unwrap(),
        1001,
        1,
        false
    )
    .is_err());
    assert!(publication::check_mutation_auth(&publish, &receipt, 1001, 1, false).is_err());
    assert!(changed(
        9,
        |value| value["actions"] = json!(["publish", "publish"]),
        false
    )
    .is_err());
    assert!(changed(6, |value| value["retryable"] = true.into(), false).is_err());
    changed(
        6,
        |value| {
            value["code"] = "backend_unavailable".into();
            value["retryable"] = true.into();
            value["reconcile_ref"] = "".into();
        },
        false,
    )
    .unwrap();
}
#[test]
fn index_queries_and_candidates_share_context_models_filters_and_budgets() {
    let binding = contract(0);
    let query = contract(10);
    let candidates = contract(8);
    read::validate_candidates_for(&binding, &query, &candidates).unwrap();
    assert!(read::validate_candidates_for(&query, &binding, &candidates).is_err());
    let pairs = changed(
        8,
        |value| {
            let mut row = value["rows"][0].clone();
            row["record_id"] = "record-2".into();
            row["score_f64_hex"] = "3ff0000000000000".into();
            value["rows"].as_array_mut().unwrap().push(row);
        },
        false,
    )
    .unwrap();
    read::validate_candidates_for(&binding, &query, &pairs).unwrap();
    assert!(changed(
        8,
        |value| {
            let mut row = value["rows"][0].clone();
            row["record_id"] = "record-2".into();
            value["rows"].as_array_mut().unwrap().insert(0, row);
        },
        false
    )
    .is_err());
    for (path, replacement) in [
        ("/candidate_limit", json!(2)),
        ("/query_text", json!("bad")),
        ("/allowed_record_ids", json!(["x"])),
        (
            "/query_vector_f64_hex",
            json!(["7fefffffffffffff", "7fefffffffffffff", "7fefffffffffffff"]),
        ),
    ] {
        assert!(changed(
            10,
            |value| *value.pointer_mut(path).unwrap() = replacement,
            false
        )
        .is_err());
    }
    for (path, replacement) in [
        ("/artifact_id", json!("wrong")),
        ("/rows/0/locator/source_version_id", json!("wrong")),
        ("/usage/output_bytes", json!(99999)),
    ] {
        assert!(read::validate_candidates_for(
            &binding,
            &query,
            &changed(
                8,
                |value| *value.pointer_mut(path).unwrap() = replacement,
                false
            )
            .unwrap()
        )
        .is_err());
    }
    changed(
        10,
        |value| {
            value["kind"] = "bm25".into();
            value["metric"] = "bm25".into();
            value["dimension"] = 1.into();
            value["query_text"] = "term".into();
            value["query_vector_f64_hex"] = json!([]);
        },
        false,
    )
    .unwrap();
}

struct FakeCatalog {
    epoch: u64,
    fail: bool,
}
impl ports::CatalogReadPort for FakeCatalog {
    fn bind(&self, _: &Contract) -> ports::PortResult<Contract> {
        Ok(contract(0))
    }
    fn reauthorize(&self, _: &Contract) -> ports::PortResult<u64> {
        if self.fail {
            Err(ContractFailure {
                code: "backend_unavailable",
                message: "authority unavailable",
            })
        } else {
            Ok(self.epoch)
        }
    }
    fn register(&self, _: &Contract, _: &Contract, _: &Contract) -> ports::PortResult<Contract> {
        Ok(contract(4))
    }
    fn publish(&self, _: &Contract, _: &Contract, _: &Contract) -> ports::PortResult<Contract> {
        Ok(contract(4))
    }
    fn reconcile(&self, _: &Contract, _: &Contract) -> ports::PortResult<Contract> {
        Ok(contract(4))
    }
    fn release_pin(&self, binding: &Contract) -> ports::PortResult<()> {
        super::wire::require(
            binding.value()["context"]["pin"]["lease_id"] == "lease-1",
            "stale pin lease",
        )
    }
}
#[test]
fn injected_authority_is_checked_at_output_and_pin_cleanup() {
    let catalog = FakeCatalog {
        epoch: 1,
        fail: false,
    };
    ports::reauthorize_read(&catalog, &contract(0), 1001).unwrap();
    ports::release_bound_pin(&catalog, &contract(0)).unwrap();
    let stale = changed(
        0,
        |value| value["context"]["pin"]["lease_id"] = "lease-2".into(),
        true,
    )
    .unwrap();
    assert!(ports::release_bound_pin(&catalog, &stale).is_err());
    assert!(ports::reauthorize_read(&catalog, &contract(3), 1001).is_err());
    assert!(ports::release_bound_pin(&catalog, &contract(3)).is_err());
    assert!(ports::reauthorize_read(
        &FakeCatalog {
            epoch: 2,
            fail: false
        },
        &contract(0),
        1001
    )
    .is_err());
    assert!(ports::reauthorize_read(
        &FakeCatalog {
            epoch: 1,
            fail: true
        },
        &contract(0),
        1001
    )
    .is_err());
}

#[path = "cf1a_boundaries.rs"]
mod boundaries;
