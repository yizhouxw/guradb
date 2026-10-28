//! Independent closed metadata expectations. No network or Parquet execution.
use crate::fixed_manifest::validate_manifests;
use guradb_common::cf1a::{canonical, decode, digest, Contract};
use serde_json::{json, Value};

// Physical IDs/types/nullability follow tests/source_support/fixed_fixture.py's
// PyArrow contract; expected row counts and cell values do not use the new kernel.
pub(super) fn fixture(counts: &[usize]) -> (Value, Vec<Value>) {
    let golden: Value =
        serde_json::from_str(include_str!("../../../../api/cf1a/golden.json")).unwrap();
    let mut envelope = golden[0].clone();
    let binding = &mut envelope["payload"]["read_binding"];
    let fields = json!([
        {"field_id":1,"name":"record_id","type":"text","nullable":false,"role":"logical_id"},
        {"field_id":2,"name":"record_version","type":"text","nullable":false,"role":"record_version"},
        {"field_id":3,"name":"title","type":"text","nullable":true,"role":"value"},
        {"field_id":4,"name":"active","type":"bool","nullable":true,"role":"value"},
        {"field_id":5,"name":"priority","type":"int8","nullable":true,"role":"value"}
    ]);
    binding["resource"]["fields"] = fields;
    let old_source = binding["revision"]["sources"][0].clone();
    let mut manifests = Vec::new();
    let mut sources = Vec::new();
    for (index, rows) in counts.iter().enumerate() {
        let schema = json!([
            {"source_field_id":101,"name":"record_id","type":"text","nullable":false},
            {"source_field_id":102,"name":"record_version","type":"text","nullable":false},
            {"source_field_id":103,"name":"title","type":"text","nullable":true},
            {"source_field_id":104,"name":"active","type":"bool","nullable":true},
            {"source_field_id":105,"name":"priority","type":"int8","nullable":true}
        ]);
        let mut source = old_source.clone();
        source["source_id"] = json!(format!("source-{index}"));
        source["source_version_id"] = json!(format!("source-{index}-v1"));
        source["snapshot_id"] = json!(format!("snapshot-{index}-v1"));
        source["format"] = json!("manifest");
        source["format_version"] = json!("1");
        source["field_mapping"] = json!([]);
        for field in binding["resource"]["fields"].as_array().unwrap() {
            source["field_mapping"].as_array_mut().unwrap().push(json!({
                "source_field_id":100+field["field_id"].as_u64().unwrap(),
                "resource_field_id":field["field_id"],"type":field["type"],
                "source_type":field["type"],"transform":"identity"
            }));
        }
        let files = if *rows == 0 {
            json!([])
        } else {
            json!([{"object":object(&format!("data-{index}"), 100),"row_group_rows":[rows]}])
        };
        manifests.push(json!({
            "manifest_version":"p04-fixed/1", "source_id":source["source_id"],
            "source_version_id":source["source_version_id"],"snapshot_id":source["snapshot_id"],
            "source_schema":schema,"files":files,"delete_files":[],"schema_evolution":"none"
        }));
        sources.push(source);
    }
    binding["revision"]["sources"] = json!(sources);
    binding["indexes"] = json!([]);
    binding["view"]["required_artifact_ids"] = json!([]);
    binding["view"]["index_requirements"] = json!([]);
    binding["context"]["artifact_ids"] = json!([]);
    refresh(&mut envelope, &manifests);
    (envelope, manifests)
}

pub(super) fn object(name: &str, size: usize) -> Value {
    json!({"backend_id":"fixed","bucket":"data","key":name,"version":"sealed-v1",
        "size_bytes":size,"sha256":"a".repeat(64),
        "integrity":{"mode":"whole_sha256","block_size":0,"block_sha256":[],"proof_ref":""}})
}

pub(super) fn refresh(envelope: &mut Value, manifests: &[Value]) {
    let value = &mut envelope["payload"]["read_binding"];
    let schema_sha = digest(&value["resource"]["fields"]);
    value["resource"]["schema_sha256"] = json!(schema_sha);
    let mut objects = Vec::new();
    for (index, manifest) in manifests.iter().enumerate() {
        let source = &mut value["revision"]["sources"][index];
        source["source_schema_sha256"] = json!(digest(&manifest["source_schema"]));
        source["resource_schema_sha256"] = json!(schema_sha);
        source["metadata"] = object(&format!("metadata-{index}"), canonical(manifest).len());
        source["metadata"]["sha256"] = json!(guradb_common::digest(&canonical(manifest)));
        objects.push(source["metadata"].clone());
        objects.extend(
            manifest["files"]
                .as_array()
                .unwrap()
                .iter()
                .map(|file| file["object"].clone()),
        );
    }
    value["revision"]["objects"] = json!(objects);
    value["context"]["source_version_ids"] = json!(value["revision"]["sources"]
        .as_array()
        .unwrap()
        .iter()
        .map(|source| source["source_version_id"].clone())
        .collect::<Vec<_>>());
    for (name, field) in [
        ("revision", "content_sha256"),
        ("view", "descriptor_sha256"),
    ] {
        let mut payload = value[name].clone();
        payload.as_object_mut().unwrap().remove(field);
        value[name][field] = json!(digest(&payload));
    }
}

pub(super) fn binding(envelope: &Value) -> Contract {
    decode(&canonical(envelope)).unwrap()
}

pub(super) fn plan(
    envelope: &Value,
    metadata: &[Value],
) -> crate::fixed_manifest::FixedManifestPlan {
    let raw: Vec<_> = metadata.iter().map(canonical).collect();
    validate_manifests(
        &binding(envelope),
        &raw.iter().map(Vec::as_slice).collect::<Vec<_>>(),
    )
    .unwrap()
}

fn code(envelope: &Value, metadata: &[Value]) -> &'static str {
    let raw: Vec<_> = metadata.iter().map(canonical).collect();
    validate_manifests(
        &binding(envelope),
        &raw.iter().map(Vec::as_slice).collect::<Vec<_>>(),
    )
    .unwrap_err()
    .code
}

#[test]
fn fixed_one_two_empty_sources_and_schema_digest_are_bound() {
    for counts in [vec![11], vec![5, 6], vec![0], vec![0, 0]] {
        let (envelope, metadata) = fixture(&counts);
        let result = plan(&envelope, &metadata);
        assert_eq!(result.row_count(), counts.iter().sum::<usize>());
        assert_eq!(result.source_count(), counts.len());
        assert_eq!(result.binding_sha256(), binding(&envelope).sha256());
    }
}

#[test]
fn rejects_closed_fields_versions_delete_evolution_and_source_mismatch() {
    let (base, metadata) = fixture(&[11]);
    for (name, replacement, expected) in [
        ("extra", json!(1), "invalid_contract"),
        (
            "manifest_version",
            json!("p04-fixed/2"),
            "unsupported_version",
        ),
        ("delete_files", json!([{}]), "unsupported_capability"),
        (
            "schema_evolution",
            json!("rename"),
            "unsupported_capability",
        ),
        (
            "source_version_id",
            json!("another-source-v1"),
            "corrupt_object",
        ),
        ("snapshot_id", Value::Null, "corrupt_object"),
    ] {
        let (mut envelope, mut changed) = (base.clone(), metadata.clone());
        changed[0][name] = replacement;
        refresh(&mut envelope, &changed);
        assert_eq!(code(&envelope, &changed), expected, "{name}");
    }
    let (mut envelope, mut changed) = (base.clone(), metadata.clone());
    changed[0].as_object_mut().unwrap().remove("snapshot_id");
    refresh(&mut envelope, &changed);
    assert_eq!(code(&envelope, &changed), "invalid_contract");
}

#[test]
fn rejects_schema_ids_order_names_types_nullability_and_stale_digest() {
    for (field, value, expected) in [
        ("source_field_id", json!(0), "invalid_contract"),
        ("source_field_id", json!(102), "invalid_contract"),
        ("source_field_id", json!(1_u64 << 31), "invalid_contract"),
        ("source_field_id", json!(true), "invalid_contract"),
        ("name", json!("title"), "invalid_contract"),
        ("type", json!("float"), "unsupported_capability"),
        ("type", json!("bool"), "corrupt_object"),
        ("nullable", json!("false"), "unsupported_capability"),
    ] {
        let (mut envelope, mut changed) = fixture(&[11]);
        changed[0]["source_schema"][0][field] = value;
        refresh(&mut envelope, &changed);
        assert_eq!(code(&envelope, &changed), expected, "{field}");
    }
    let (mut envelope, mut metadata) = fixture(&[11]);
    metadata[0]["source_schema"]
        .as_array_mut()
        .unwrap()
        .swap(0, 1);
    refresh(&mut envelope, &metadata);
    assert_eq!(code(&envelope, &metadata), "invalid_contract");
    let (mut envelope, mut metadata) = fixture(&[11]);
    metadata[0]["source_schema"][0]["name"] = json!("othername");
    refresh(&mut envelope, &metadata);
    envelope["payload"]["read_binding"]["revision"]["sources"][0]["source_schema_sha256"] =
        json!("0".repeat(64));
    let revision = &mut envelope["payload"]["read_binding"]["revision"];
    let mut unhashed = revision.clone();
    unhashed.as_object_mut().unwrap().remove("content_sha256");
    revision["content_sha256"] = json!(digest(&unhashed));
    assert_eq!(code(&envelope, &metadata), "corrupt_object");
}

#[test]
fn combined_limits_closure_and_cross_source_duplicates_are_rejected() {
    let (mut envelope, mut metadata) = fixture(&[500, 500]);
    assert_eq!(plan(&envelope, &metadata).row_count(), 1000);
    metadata[1]["files"][0]["row_group_rows"] = json!([501]);
    refresh(&mut envelope, &metadata);
    assert_eq!(code(&envelope, &metadata), "resource_limit");
    let (mut envelope, mut metadata) = fixture(&[1]);
    metadata[0]["files"][0]["row_group_rows"] = json!(vec![1; 16]);
    refresh(&mut envelope, &metadata);
    assert_eq!(plan(&envelope, &metadata).row_count(), 16);
    metadata[0]["files"][0]["row_group_rows"] = json!(vec![1; 17]);
    refresh(&mut envelope, &metadata);
    assert_eq!(code(&envelope, &metadata), "invalid_contract");
    for size in [1 << 20, (1 << 20) + 1] {
        let (mut envelope, mut metadata) = fixture(&[1]);
        metadata[0]["files"][0]["object"]["size_bytes"] = json!(size);
        refresh(&mut envelope, &metadata);
        if size == 1 << 20 {
            assert_eq!(plan(&envelope, &metadata).row_count(), 1);
        } else {
            assert_eq!(code(&envelope, &metadata), "resource_limit");
        }
    }
    let (mut envelope, metadata) = fixture(&[1]);
    envelope["payload"]["read_binding"]["revision"]["objects"]
        .as_array_mut()
        .unwrap()
        .push(object("unlisted", 10));
    let revision = &mut envelope["payload"]["read_binding"]["revision"];
    let mut unhashed = revision.clone();
    unhashed.as_object_mut().unwrap().remove("content_sha256");
    revision["content_sha256"] = json!(digest(&unhashed));
    assert_eq!(code(&envelope, &metadata), "unsupported_capability");
    // Same object cannot supply two distinct source sets.
    let (mut envelope, mut metadata) = fixture(&[1, 1]);
    metadata[1]["files"][0]["object"] = metadata[0]["files"][0]["object"].clone();
    refresh(&mut envelope, &metadata);
    // A binding itself rejects two identical physical locators; never bypass it.
    assert!(decode(&canonical(&envelope)).is_err());
}

#[test]
fn rejects_noncanonical_duplicate_unsafe_numeric_and_structural_json() {
    let (envelope, metadata) = fixture(&[1]);
    let valid = canonical(&metadata[0]);
    let invalid = [
        [b" ".as_slice(), valid.as_slice()].concat(),
        br#"{"x":1,"x":2}"#.to_vec(),
        br#"{"x":-0}"#.to_vec(),
        br#"{"x":1.0}"#.to_vec(),
        br#"{"x":9007199254740992}"#.to_vec(),
        b"[".repeat(13),
        b"\"truncated".to_vec(),
        vec![0xff],
        vec![b' '; 65537],
    ];
    for raw in invalid {
        let mut changed = envelope.clone();
        let b = &mut changed["payload"]["read_binding"];
        let old = b["revision"]["sources"][0]["metadata"].clone();
        let mut new = object("metadata-0", raw.len());
        new["sha256"] = json!(guradb_common::digest(&raw));
        b["revision"]["sources"][0]["metadata"] = new.clone();
        let objects = b["revision"]["objects"].as_array_mut().unwrap();
        *objects.iter_mut().find(|item| **item == old).unwrap() = new;
        let mut unhashed = b["revision"].clone();
        unhashed.as_object_mut().unwrap().remove("content_sha256");
        b["revision"]["content_sha256"] = json!(digest(&unhashed));
        assert!(validate_manifests(&binding(&changed), &[&raw]).is_err());
    }
    assert!(validate_manifests(&binding(&envelope), &[]).is_err());
    assert!(validate_manifests(&binding(&envelope), &[b"short"]).is_err());
}

#[test]
fn two_sources_preserve_aggregate_file_group_byte_and_width_boundaries() {
    let (mut envelope, mut metadata) = fixture(&[1, 1]);
    for (source_index, manifest) in metadata.iter_mut().enumerate() {
        manifest["files"] = json!((0..2)
            .map(|file| json!({
                "object":object(&format!("source-{source_index}-file-{file}"), 1 << 20),
                "row_group_rows":vec![1; 4]
            }))
            .collect::<Vec<_>>());
    }
    refresh(&mut envelope, &metadata);
    assert_eq!(plan(&envelope, &metadata).row_count(), 16); // 4 files,16 groups,4MiB.
    metadata[1]["files"].as_array_mut().unwrap().push(json!({
        "object":object("fifth-file", 1),"row_group_rows":[1]
    }));
    refresh(&mut envelope, &metadata);
    assert_eq!(code(&envelope, &metadata), "resource_limit");
    let (mut envelope, mut metadata) = fixture(&[1, 1]);
    metadata[0]["files"][0]["row_group_rows"] = json!(vec![1; 8]);
    metadata[1]["files"][0]["row_group_rows"] = json!(vec![1; 9]);
    refresh(&mut envelope, &metadata);
    assert_eq!(code(&envelope, &metadata), "resource_limit");
    let (mut envelope, mut metadata) = fixture(&[0, 0]);
    for manifest in &mut metadata {
        let fields = manifest["source_schema"].as_array_mut().unwrap();
        for id in 106..=116 {
            fields.push(json!({"source_field_id":id,"name":format!("extra-{id}"),
                "type":"bool","nullable":true}));
        }
    }
    refresh(&mut envelope, &metadata);
    assert_eq!(plan(&envelope, &metadata).row_count(), 0); // 16+16 columns.
    metadata[1]["source_schema"]
        .as_array_mut()
        .unwrap()
        .push(json!({
            "source_field_id":117,"name":"one-more","type":"bool","nullable":true
        }));
    refresh(&mut envelope, &metadata);
    assert_eq!(code(&envelope, &metadata), "resource_limit");
}

#[test]
fn count_format_mapping_and_object_binding_cannot_be_substituted() {
    let (envelope, metadata) = fixture(&[0, 0, 0]);
    assert_eq!(code(&envelope, &metadata), "unsupported_capability");
    let (mut envelope, metadata) = fixture(&[1]);
    envelope["payload"]["read_binding"]["revision"]["sources"][0]["format"] = json!("iceberg");
    envelope["payload"]["read_binding"]["revision"]["sources"][0]["format_version"] = json!("2");
    refresh(&mut envelope, &metadata);
    assert_eq!(code(&envelope, &metadata), "unsupported_capability");
    let (mut envelope, metadata) = fixture(&[1]);
    envelope["payload"]["read_binding"]["revision"]["sources"][0]["field_mapping"][0]
        ["source_field_id"] = json!(999);
    refresh(&mut envelope, &metadata);
    assert_eq!(code(&envelope, &metadata), "corrupt_object");
    // The metadata bytes cannot be replaced by a same-size canonical object.
    let (envelope, mut metadata) = fixture(&[1]);
    metadata[0]["files"][0]["row_group_rows"] = json!([2]);
    assert_eq!(code(&envelope, &metadata), "corrupt_object");
}

fn binding_for_raw_metadata(envelope: &Value, raw: &[u8]) -> Contract {
    // Preserve the valid schema/source/context. Bind the mutated raw bytes so
    // the intended parser error cannot be masked by a stale size or digest.
    let mut changed = envelope.clone();
    let value = &mut changed["payload"]["read_binding"];
    let original = value["revision"]["sources"][0]["metadata"].clone();
    let mut replacement = object("metadata-0", raw.len());
    replacement["sha256"] = json!(guradb_common::digest(raw));
    value["revision"]["sources"][0]["metadata"] = replacement.clone();
    let objects = value["revision"]["objects"].as_array_mut().unwrap();
    let entry = objects.iter_mut().find(|item| **item == original).unwrap();
    *entry = replacement;
    let mut revision = value["revision"].clone();
    revision.as_object_mut().unwrap().remove("content_sha256");
    value["revision"]["content_sha256"] = json!(digest(&revision));
    binding(&changed)
}

fn raw_manifest_error(envelope: &Value, raw: &[u8]) -> &'static str {
    validate_manifests(&binding_for_raw_metadata(envelope, raw), &[raw])
        .unwrap_err()
        .code
}

#[test]
fn complete_manifest_numeric_tokens_have_stable_error_codes() {
    let (envelope, metadata) = fixture(&[1]);
    let valid = String::from_utf8(canonical(&metadata[0])).unwrap();
    let marker = "\"row_group_rows\":[1]";
    assert_eq!(valid.matches(marker).count(), 1);
    assert_eq!(plan(&envelope, &metadata).row_count(), 1);
    for token in [
        "-0",
        "-1",
        "1.0",
        "1e0",
        "9007199254740992",
        "18446744073709551615",
    ] {
        let raw = valid.replacen(marker, &format!("\"row_group_rows\":[{token}]"), 1);
        let witness: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(witness.as_object().unwrap().len(), 8);
        assert_eq!(witness["files"].as_array().unwrap().len(), 1);
        assert_eq!(
            raw_manifest_error(&envelope, raw.as_bytes()),
            "invalid_contract",
            "numeric token {token}",
        );
    }
}

#[test]
fn complete_manifest_same_value_duplicate_fields_are_invalid_contract() {
    let (envelope, metadata) = fixture(&[1]);
    let valid = String::from_utf8(canonical(&metadata[0])).unwrap();
    for marker in [
        "\"snapshot_id\":\"snapshot-0-v1\"",
        "\"source_field_id\":101",
    ] {
        assert_eq!(valid.matches(marker).count(), 1);
        let duplicated = valid.replacen(marker, &format!("{marker},{marker}"), 1);
        // Ordinary JSON parsing retains the last equal value. Every semantic
        // field is still the valid fixture; only the duplicate bytes differ.
        let witness: Value = serde_json::from_str(&duplicated).unwrap();
        assert_eq!(witness, metadata[0]);
        assert_eq!(
            raw_manifest_error(&envelope, duplicated.as_bytes()),
            "invalid_contract",
        );
    }
    let truncated = &valid.as_bytes()[..valid.len() - 1];
    assert!(serde_json::from_slice::<Value>(truncated).is_err());
    assert_eq!(raw_manifest_error(&envelope, truncated), "corrupt_object");
}

#[test]
fn parser_byte_boundary_is_not_a_full_manifest_support_claim() {
    let (envelope, _) = fixture(&[1]);
    for (bytes, expected_code) in [(65536, "invalid_contract"), (65537, "resource_limit")] {
        let raw = format!("\"{}\"", "a".repeat(bytes - 2)).into_bytes();
        assert_eq!(raw.len(), bytes);
        let witness: Value = serde_json::from_slice(&raw).unwrap();
        assert_eq!(witness.as_str().unwrap().len(), bytes - 2);
        assert_eq!(raw_manifest_error(&envelope, &raw), expected_code);
    }
}
