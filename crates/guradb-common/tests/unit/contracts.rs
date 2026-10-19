use super::*;
use serde_json::json;

#[test]
fn public_errors_defaults_and_identity_boundaries() {
    let error = Error::new("invalid", "explanation");
    assert_eq!(error.to_string(), "invalid: explanation");
    assert!(!error.retryable);
    assert!(Uuid::parse_str(&error.request_id).is_ok());
    assert_eq!(
        digest(b"abc"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert!(Limits::default().validate().is_ok());
    let value = serde_json::to_value(Limits::default()).unwrap();
    for name in value.as_object().unwrap().keys() {
        for number in [0, u64::MAX] {
            let mut changed = value.clone();
            changed[name] = json!(number);
            let limits: Limits = serde_json::from_value(changed).unwrap();
            assert_eq!(limits.validate().unwrap_err().code, "invalid_config");
        }
    }
    assert!(encode_key(&[("text", &[255])]).is_err());
    assert!(encode_key(&[("uuid", &[0; 16])]).is_ok());
    assert!(encode_key(&[("uuid", &[0; 15])]).is_err());
    assert!(encode_key(&[]).is_ok());
    assert_eq!(key_length(u32::MAX as usize, "width").unwrap(), u32::MAX);
    assert_eq!(
        key_length(usize::MAX, "width").unwrap_err().code,
        "invalid_key"
    );
}

#[test]
fn manifest_and_json_contract_rejects_unsupported_inputs() {
    use manifest::*;
    let valid = json!({"schema_version":1,"dataset_id":"89b349e2-cc73-4c22-871d-c80a159d7789",
        "table_name":"documents","schema":[{"name":"id","data_type":"int8","nullable":false}],
        "backend":{"kind":"local","root":"/tmp"},"files":[{"fragment_id":"f0","key":"a.parquet","size_bytes":1,"sha256":"a".repeat(64)}],"retention_mode":"best-effort"});
    let parse = |v| serde_json::from_value::<Manifest>(v).unwrap();
    parse(valid.clone()).validate().unwrap();
    let mut bad = valid.clone();
    bad["schema_version"] = json!(2);
    assert!(parse(bad).validate().is_err());
    let mut bad = valid.clone();
    bad["schema"][0]["name"] = json!("Bad");
    assert!(parse(bad).validate().is_err());
    for key in ["../x", "x//y", "/x", "x\\y", "x/./y", ""] {
        let mut bad = valid.clone();
        bad["files"][0]["key"] = json!(key);
        assert!(parse(bad).validate().is_err(), "{key}");
    }
    let mut bad = valid.clone();
    bad["files"][0]["version_id"] = json!("v1");
    assert!(parse(bad.clone()).validate().is_err());
    bad["backend"] = json!({"kind":"s3","bucket":"b","region":"r","endpoint":"http://localhost"});
    parse(bad.clone()).validate().unwrap();
    bad["files"][0]["version_id"] = json!("");
    assert!(parse(bad).validate().is_err());
    for name in ["", "2x", "A", "a-b"] {
        assert!(!identifier(name));
    }
    for name in ["a", "a_2", "_"] {
        assert!(identifier(name));
    }
    for sha in ["", &"A".repeat(64), &"g".repeat(64)] {
        assert!(!valid_digest(sha));
    }
    assert!(valid_digest(&"0".repeat(64)));
    let request: protocol::QueryRequest =
        serde_json::from_value(json!({"sql":"SELECT id FROM documents","max_rows":1})).unwrap();
    assert_eq!(request.mode, "read_only");
    assert_eq!(request.read_consistency, "published");
    assert_eq!(request.max_rows, Some(1));
    assert!(
        serde_json::from_value::<protocol::QueryRequest>(json!({"sql":"x","max_rows":null}))
            .is_err()
    );
}
