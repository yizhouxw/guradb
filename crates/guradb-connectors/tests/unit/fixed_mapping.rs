use crate::{
    fixed_manifest_tests::{fixture, plan, refresh},
    fixed_mapping::{map_records, PhysicalRow},
};
use guradb_common::cf1a::Cell;
use serde_json::json;

fn row(id: &str) -> PhysicalRow {
    [
        (101, Cell::Text(id.into())),
        (102, Cell::Text("version-1".into())),
        (103, Cell::Text("数据库".into())),
        (104, Cell::Bool(false)),
        (105, Cell::Int8(i64::MIN.to_string())),
    ]
    .into_iter()
    .collect()
}

#[test]
fn stable_identity_version_unicode_int64_and_null_preserve_exact_cells() {
    let (envelope, metadata) = fixture(&[2]);
    let p = plan(&envelope, &metadata);
    let first = row("a");
    let mut second = row("z");
    second.insert(103, Cell::Null(()));
    second.insert(104, Cell::Null(()));
    second.insert(105, Cell::Int8(i64::MAX.to_string()));
    let output = map_records(&p, &[vec![second, first]]).unwrap();
    assert_eq!(
        output
            .iter()
            .map(|record| record.record_id.as_str())
            .collect::<Vec<_>>(),
        ["a", "z"]
    );
    assert_eq!(output[0].record_version, "version-1");
    assert!(matches!(&output[0].cells[2], Cell::Text(value) if value == "数据库"));
    assert!(matches!(&output[0].cells[4], Cell::Int8(value) if value == "-9223372036854775808"));
    assert!(matches!(&output[1].cells[2], Cell::Null(())));
    assert!(matches!(&output[1].cells[4], Cell::Int8(value) if value == "9223372036854775807"));
}

#[test]
fn key_v1_uses_independent_hand_calculated_prefix_tag_and_bytes() {
    let (mut envelope, metadata) = fixture(&[1]);
    let source = &mut envelope["payload"]["read_binding"]["revision"]["sources"][0];
    source["field_mapping"][0]["transform"] = json!("key_v1");
    source["field_mapping"][1]["transform"] = json!("revision_version");
    source["field_mapping"][1]["source_field_id"] = json!(0);
    source["field_mapping"][1]["source_type"] = json!("none");
    refresh(&mut envelope, &metadata);
    let p = plan(&envelope, &metadata);
    let output = map_records(&p, &[vec![row("中")]]).unwrap();
    // Version01 + parts00000001 + text01 + len00000003 + UTF8e4b8ad.
    assert_eq!(output[0].record_id, "01000000010100000003e4b8ad");
    assert_eq!(
        output[0].record_version,
        envelope["payload"]["read_binding"]["revision"]["data_revision_id"]
            .as_str()
            .unwrap()
    );
    let mut too_wide = row(&"中".repeat(19));
    assert_eq!(
        map_records(&p, &[vec![too_wide.clone()]]).unwrap_err().code,
        "resource_limit"
    );
    too_wide.insert(101, Cell::Text("a".repeat(54)));
    assert_eq!(
        map_records(&p, &[vec![too_wide]]).unwrap()[0]
            .record_id
            .len(),
        128
    );
}

#[test]
fn typed_integer_key_does_not_become_text_or_pass_through_float() {
    let (mut envelope, mut metadata) = fixture(&[1]);
    metadata[0]["source_schema"][0]["type"] = json!("int8");
    let mapping =
        &mut envelope["payload"]["read_binding"]["revision"]["sources"][0]["field_mapping"][0];
    mapping["source_type"] = json!("int8");
    mapping["transform"] = json!("key_v1");
    refresh(&mut envelope, &metadata);
    let p = plan(&envelope, &metadata);
    let mut physical = row("unused");
    physical.insert(101, Cell::Int8(i64::MIN.to_string()));
    // Version01 + count1 + int8 tag02 + width8 + signed int64 BE.
    assert_eq!(
        map_records(&p, &[vec![physical.clone()]]).unwrap()[0].record_id,
        "010000000102000000088000000000000000"
    );
    physical.insert(101, Cell::Int8(i64::MAX.to_string()));
    assert_eq!(
        map_records(&p, &[vec![physical.clone()]]).unwrap()[0].record_id,
        "010000000102000000087fffffffffffffff"
    );
    physical.insert(101, Cell::Int8("1".into()));
    assert_eq!(
        map_records(&p, &[vec![physical.clone()]]).unwrap()[0].record_id,
        "010000000102000000080000000000000001"
    );
    for value in ["01", "-0", "1.0", "9223372036854775808"] {
        physical.insert(101, Cell::Int8(value.into()));
        assert_eq!(
            map_records(&p, &[vec![physical.clone()]]).unwrap_err().code,
            "corrupt_object"
        );
    }
}

#[test]
fn duplicate_ids_are_rejected_across_entire_supplied_source_set() {
    for counts in [vec![2], vec![1, 1]] {
        let (envelope, metadata) = fixture(&counts);
        let rows = counts
            .iter()
            .map(|count| vec![row("same"); *count])
            .collect::<Vec<_>>();
        assert_eq!(
            map_records(&plan(&envelope, &metadata), &rows)
                .unwrap_err()
                .code,
            "corrupt_object"
        );
    }
}

#[test]
fn missing_extra_field_wrong_type_null_and_bad_id_fail_closed() {
    let (envelope, metadata) = fixture(&[1]);
    let p = plan(&envelope, &metadata);
    for (id, cell) in [
        (101, Cell::Null(())),
        (102, Cell::Null(())),
        (103, Cell::Bool(true)),
        (105, Cell::Int8("-0".into())),
    ] {
        let mut physical = row("valid");
        physical.insert(id, cell);
        assert_eq!(
            map_records(&p, &[vec![physical]]).unwrap_err().code,
            "corrupt_object"
        );
    }
    for bad in ["", "latest", "invalid id", "中文"] {
        assert_eq!(
            map_records(&p, &[vec![row(bad)]]).unwrap_err().code,
            "invalid_contract"
        );
    }
    let mut missing = row("valid");
    missing.remove(&105);
    assert!(map_records(&p, &[vec![missing]]).is_err());
    let mut extra = row("valid");
    extra.insert(999, Cell::Bool(true));
    assert!(map_records(&p, &[vec![extra]]).is_err());
    let mut wrong_id = row("valid");
    wrong_id.remove(&105);
    wrong_id.insert(999, Cell::Bool(true));
    assert!(map_records(&p, &[vec![wrong_id]]).is_err());
    assert!(map_records(&p, &[]).is_err());
    assert!(map_records(&p, &[vec![]]).is_err());
    let (envelope, metadata) = fixture(&[0, 0]);
    assert!(map_records(&plan(&envelope, &metadata), &[vec![], vec![]])
        .unwrap()
        .is_empty());
}

#[test]
fn key_null_and_identity_version_must_fail_before_any_result_is_returned() {
    let (mut envelope, mut metadata) = fixture(&[1]);
    metadata[0]["source_schema"][0]["nullable"] = json!(true);
    envelope["payload"]["read_binding"]["revision"]["sources"][0]["field_mapping"][0]
        ["transform"] = json!("key_v1");
    refresh(&mut envelope, &metadata);
    let p = plan(&envelope, &metadata);
    let mut physical = row("valid");
    physical.insert(101, Cell::Null(()));
    assert_eq!(
        map_records(&p, &[vec![physical]]).unwrap_err().code,
        "corrupt_object"
    );
    let (envelope, metadata) = fixture(&[2]);
    let p = plan(&envelope, &metadata);
    let mut late = row("second");
    late.insert(102, Cell::Text("latest".into()));
    assert_eq!(
        map_records(&p, &[vec![row("first"), late]])
            .unwrap_err()
            .code,
        "invalid_contract"
    );
    let (envelope, metadata) = fixture(&[1]);
    let p = plan(&envelope, &metadata);
    let mut physical = row("first");
    physical.insert(103, Cell::Text("中".repeat(4097)));
    assert_eq!(
        map_records(&p, &[vec![physical]]).unwrap_err().code,
        "resource_limit"
    );
}
