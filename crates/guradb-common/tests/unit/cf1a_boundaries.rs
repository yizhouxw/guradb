//! Invalid inputs reach every safety assertion, including exact predicate failures.
use super::*;

#[test]
fn descriptor_and_pin_lease_boundary_failures() {
    for (path, replacement) in [
        ("/resource/schema_version", json!(2)),
        ("/indexes", json!([])),
        ("/view/data_revision_id", json!("other")),
        (
            "/revision/sources/0/field_mapping/2/source_field_id",
            json!(1),
        ),
        ("/revision/objects/0/key", json!("")),
        ("/context/auth/policy_epoch", json!(0)),
    ] {
        assert!(changed(
            0,
            |value| *value.pointer_mut(path).unwrap() = replacement,
            true
        )
        .is_err());
    }
    assert!(changed(
        0,
        |value| {
            let mut source = value["revision"]["sources"][0].clone();
            source["source_id"] = "source-2".into();
            source["source_version_id"] = "source-version-2".into();
            source["field_mapping"][1]["source_field_id"] = 0.into();
            source["field_mapping"][1]["source_type"] = "none".into();
            source["field_mapping"][1]["transform"] = "revision_version".into();
            value["revision"]["sources"]
                .as_array_mut()
                .unwrap()
                .push(source);
        },
        true
    )
    .is_err());
    let binding = changed(
        0,
        |value| {
            value["revision"]["sources"][0]["field_mapping"][1]["source_field_id"] = 0.into();
            value["revision"]["sources"][0]["field_mapping"][1]["source_type"] = "none".into();
            value["revision"]["sources"][0]["field_mapping"][1]["transform"] =
                "revision_version".into();
        },
        true,
    )
    .unwrap();
    let batch = changed(
        1,
        |value| {
            value["context_sha256"] = binding.sha256().into();
            for row in value["rows"].as_array_mut().unwrap() {
                row["record_version"] = "revision-1".into();
                row["cells"][1]["value"] = "revision-1".into();
            }
        },
        true,
    )
    .unwrap();
    read::validate_batch_for(&binding, &batch).unwrap();
    let wrong = changed(
        1,
        |value| value["context_sha256"] = binding.sha256().into(),
        true,
    )
    .unwrap();
    assert!(read::validate_batch_for(&binding, &wrong).is_err());
    let mut object: ObjectRef =
        serde_json::from_value(contract(0).value()["revision"]["objects"][0].clone()).unwrap();
    object.integrity.mode = "block_sha256".into();
    object.integrity.block_size = 3;
    object.integrity.block_sha256 = vec!["a".repeat(64); 2];
    object.integrity.proof_ref = "proof".into();
    assert!(read::validate_range(&object, 0, 8).is_err());
}

#[test]
fn mutation_targets_and_replays_bind_all_entity_content() {
    for (path, replacement) in [
        ("/artifact_ids", json!(["a", "a"])),
        ("/expected_generation", json!(0)),
        ("/expected_view_id", json!("view-1")),
    ] {
        assert!(changed(
            3,
            |value| {
                *value.pointer_mut(path).unwrap() = replacement;
                if path == "/expected_generation" {
                    value["expected_view_id"] = "nonempty".into();
                }
            },
            false
        )
        .is_err());
    }
    for (path, replacement) in [("/state", json!("rejected")), ("/result_id", json!(""))] {
        assert!(changed(
            4,
            |value| *value.pointer_mut(path).unwrap() = replacement,
            false
        )
        .is_err());
    }
    assert!(changed(6, |value| value["reconcile_ref"] = "".into(), false).is_err());
    for (path, replacement) in [
        ("/operation_id", json!("wrong")),
        ("/generation", json!(3)),
        ("/result_id", json!("wrong")),
    ] {
        let receipt = changed(
            4,
            |value| *value.pointer_mut(path).unwrap() = replacement,
            false,
        )
        .unwrap();
        assert!(publication::check_receipt(&contract(3), &receipt).is_err());
    }
    assert!(publication::check_target(
        &changed(2, |value| value["tenant_id"] = "other".into(), false).unwrap(),
        &contract(11)
    )
    .is_err());
    assert!(publication::check_target(
        &changed(
            2,
            |value| value["revision_sha256"] = "b".repeat(64).into(),
            false
        )
        .unwrap(),
        &contract(11)
    )
    .is_err());
    let target = changed(
        11,
        |value| value["resource"]["display_name"] = "changed".into(),
        true,
    )
    .unwrap();
    assert!(publication::check_target(&contract(2), &target).is_err());
    let target = changed(
        11,
        |value| value["view"]["publication_generation"] = 100.into(),
        true,
    )
    .unwrap();
    let intent = changed(
        3,
        |value| {
            value["target_descriptors_sha256"] = digest(target.value()).into();
            value["target_view_sha256"] = target.value()["view"]["descriptor_sha256"].clone();
        },
        false,
    )
    .unwrap();
    assert!(publication::check_target(&intent, &target).is_err());
    for number in [0, 1_u64 << 53] {
        assert!(publication::check_cas(&contract(3), 1, number, "", 0).is_err());
    }
}

#[test]
fn candidate_ranking_filter_and_delta_budget_boundaries() {
    assert!(changed(7, |value| value["timeout_ms"] = 30001.into(), false).is_err());
    for (path, replacement) in [
        ("/complete", json!(false)),
        ("/score_order", json!("descending")),
    ] {
        assert!(changed(
            8,
            |value| *value.pointer_mut(path).unwrap() = replacement,
            false
        )
        .is_err());
    }
    changed(
        8,
        |value| {
            value["metric"] = "bm25".into();
            value["score_order"] = "descending".into();
            value["rows"][0]["score_f64_hex"] = "3ff0000000000000".into();
            let mut second = value["rows"][0].clone();
            second["record_id"] = "record-2".into();
            second["score_f64_hex"] = "0000000000000000".into();
            value["rows"].as_array_mut().unwrap().push(second);
        },
        false,
    )
    .unwrap();
    let query = changed(
        10,
        |value| {
            value["filter_mode"] = "ids".into();
            value["allowed_record_ids"] = json!(["record-1"]);
        },
        false,
    )
    .unwrap();
    let batch = changed(
        8,
        |value| value["index_query_sha256"] = query.sha256().into(),
        false,
    )
    .unwrap();
    read::validate_candidates_for(&contract(0), &query, &batch).unwrap();
    let query = changed(
        10,
        |value| {
            value["filter_mode"] = "ids".into();
            value["allowed_record_ids"] = json!(["other"]);
        },
        false,
    )
    .unwrap();
    let batch = changed(
        8,
        |value| value["index_query_sha256"] = query.sha256().into(),
        false,
    )
    .unwrap();
    assert!(read::validate_candidates_for(&contract(0), &query, &batch).is_err());
    let query = changed(10, |value| value["candidate_limit"] = 17.into(), false).unwrap();
    let batch = changed(
        8,
        |value| value["index_query_sha256"] = query.sha256().into(),
        false,
    )
    .unwrap();
    assert!(read::validate_candidates_for(&contract(0), &query, &batch).is_err());
}

#[test]
fn raw_schema_rejects_structural_and_scalar_malformations() {
    let root: Value =
        serde_json::from_str(include_str!("../../../../api/cf1a/schema.json")).unwrap();
    let mut duplicate_caps = golden()[0].clone();
    duplicate_caps["required_capabilities"] = json!(["fixed_read", "fixed_read"]);
    assert!(super::super::wire::shape(&duplicate_caps, &root, &root).is_err());
    for (value, spec) in [
        (
            json!({}),
            json!({"type":"object","properties":{"x":{"type":"boolean"}}}),
        ),
        (
            json!([]),
            json!({"type":"array","minItems":1,"items":{"type":"boolean"}}),
        ),
    ] {
        assert!(super::super::wire::shape(&value, &spec, &root).is_err());
    }
    for (path, replacement) in [
        ("/resource/dataset_id", json!("bad/id")),
        ("/resource/schema_sha256", json!("A".repeat(64))),
        ("/resource/display_name", json!("x".repeat(4097))),
        ("/revision/objects/0/version", json!("")),
        ("/revision/objects/0/version", json!("bad\nversion")),
        ("/context/budget/memory_bytes", json!(0)),
    ] {
        assert!(changed(
            0,
            |value| *value.pointer_mut(path).unwrap() = replacement,
            true
        )
        .is_err());
    }
    let mut doc = golden()[0].clone();
    doc["required_capabilities"] = json!(["fixed_read", "fixed_read"]);
    assert!(decode(&serde_json::to_vec(&doc).unwrap()).is_err());
    doc["required_capabilities"] = json!(["future"]);
    assert!(decode(&serde_json::to_vec(&doc).unwrap()).is_err());
    doc = golden()[0].clone();
    doc["payload"] = json!({});
    assert!(decode(&serde_json::to_vec(&doc).unwrap()).is_err());
    doc["payload"] = json!({"future":{}});
    assert!(decode(&serde_json::to_vec(&doc).unwrap()).is_err());
}
