use super::*;
use serde_json::json;

#[test]
fn manifests_are_pinned_unique_and_bounded() {
    let root = std::env::temp_dir().join(format!("gura-catalog-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    let path = root.join("manifest.json");
    let value = json!({"schema_version":1,"dataset_id":"89b349e2-cc73-4c22-871d-c80a159d7789",
        "table_name":"documents","schema":[{"name":"id","data_type":"int8","nullable":false}],
        "backend":{"kind":"local","root":root},"files":[{"fragment_id":"f0","key":"a.parquet","size_bytes":1,"sha256":"a".repeat(64)}],"retention_mode":"best-effort"});
    let raw = serde_json::to_vec(&value).unwrap();
    std::fs::write(&path, &raw).unwrap();
    let reference = ManifestRef {
        path: path.to_str().unwrap().into(),
        sha256: digest(&raw),
    };
    let catalog = load(std::slice::from_ref(&reference)).unwrap();
    assert_eq!(
        catalog["documents"].context.read_view_id,
        format!("view_{}", reference.sha256)
    );
    assert!(load(&[reference.clone(), reference.clone()]).is_err());
    assert!(load(&[]).is_err());
    assert!(load(&vec![reference.clone(); 17]).is_err());
    for raw in [b"invalid JSON".to_vec(), vec![b'x'; 262145]] {
        std::fs::write(&path, &raw).unwrap();
        assert!(load(&[ManifestRef {
            path: reference.path.clone(),
            sha256: digest(&raw)
        }])
        .is_err());
    }
    std::fs::remove_file(&path).unwrap();
    assert!(load(&[reference]).is_err());
    assert!(load(&[ManifestRef {
        path: root.to_str().unwrap().into(),
        sha256: "a".repeat(64)
    }])
    .is_err());
    std::fs::remove_dir_all(root).unwrap();
}
