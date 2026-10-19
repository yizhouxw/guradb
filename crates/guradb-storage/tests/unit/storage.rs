use super::*;
use object_store::{memory::InMemory, PutPayload};

#[tokio::test]
async fn local_and_object_store_reads_enforce_immutable_content() {
    let root = std::env::temp_dir().join(format!(
        "gura-storage-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let source = Source::new(&Backend::Local {
        root: root.to_str().unwrap().into(),
    })
    .unwrap();
    let raw = b"fixed bytes";
    std::fs::write(root.join("data"), raw).unwrap();
    let mut fragment = Fragment {
        fragment_id: "f0".into(),
        key: "data".into(),
        size_bytes: raw.len(),
        sha256: digest(raw),
        version_id: None,
    };
    let cancel = CancellationToken::new();
    assert_eq!(source.read(&fragment, &cancel).await.unwrap().as_ref(), raw);
    fragment.sha256 = "0".repeat(64);
    assert_eq!(
        source.read(&fragment, &cancel).await.unwrap_err().code,
        "source_invalid"
    );
    fragment.sha256 = digest(raw);
    std::os::unix::fs::symlink(root.join("data"), root.join("link")).unwrap();
    fragment.key = "link".into();
    assert_eq!(
        source.read(&fragment, &cancel).await.unwrap_err().code,
        "source_invalid"
    );
    fragment.key = "missing".into();
    assert_eq!(
        source.read(&fragment, &cancel).await.unwrap_err().code,
        "source_unavailable"
    );
    fragment.key = "../".into();
    assert_eq!(
        source.read(&fragment, &cancel).await.unwrap_err().code,
        "source_invalid"
    );
    fragment.key = "data".into();
    let store = Arc::new(InMemory::new());
    store
        .put(&ObjectPath::from("data"), PutPayload::from_static(raw))
        .await
        .unwrap();
    let source = Source::S3(store);
    assert_eq!(source.read(&fragment, &cancel).await.unwrap().as_ref(), raw);
    fragment.size_bytes += 1;
    assert_eq!(
        source.read(&fragment, &cancel).await.unwrap_err().code,
        "source_invalid"
    );
    fragment.size_bytes -= 1;
    cancel.cancel();
    assert_eq!(
        source.read(&fragment, &cancel).await.unwrap_err().code,
        "cancelled"
    );
    assert!(Source::new(&Backend::Local {
        root: root.join("missing").to_str().unwrap().into()
    })
    .is_err());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn s3_configuration() {
    if let Ok(mode) = std::env::var("GURA_S3_CONFIG_UNIT") {
        let backend = Backend::S3 {
            bucket: "unit".into(),
            region: "us-east-1".into(),
            endpoint: if mode == "invalid" {
                "http://[bad]"
            } else {
                "http://127.0.0.1:1"
            }
            .into(),
            allow_http: true,
        };
        let result = Source::new(&backend);
        if mode == "valid" || mode == "invalid" {
            assert!(result.is_ok());
        } else {
            assert!(result.is_err());
        }
        return;
    }
    for mode in ["valid", "invalid", "missing-key", "missing-secret"] {
        let mut command = std::process::Command::new(std::env::current_exe().unwrap());
        command
            .args(["--exact", "tests::s3_configuration", "--nocapture"])
            .env("GURA_S3_CONFIG_UNIT", mode)
            .env("AWS_ACCESS_KEY_ID", "unit")
            .env("AWS_SECRET_ACCESS_KEY", "unit")
            .env("AWS_SESSION_TOKEN", "unit");
        if mode == "missing-key" {
            command.env_remove("AWS_ACCESS_KEY_ID");
        }
        if mode == "missing-secret" {
            command.env_remove("AWS_SECRET_ACCESS_KEY");
        }
        assert!(command.status().unwrap().success(), "{mode}");
    }
}
