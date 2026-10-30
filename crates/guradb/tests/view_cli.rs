//! Persistent-state invariants via real CLI; tiny bytes are not decoded JPEGs.
use arrow::{
    array::{Int64Array, StringArray},
    datatypes::{DataType, Field, Schema},
    record_batch::RecordBatch,
};
use parquet::arrow::ArrowWriter;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::PathBuf,
    process::{Command, Output},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
};
static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Fixture {
    root: PathBuf,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "guradb-views-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        Self { root }
    }
    fn input(&self, version: usize) -> (String, String) {
        let root = self.root.join(format!("input-{version}"));
        fs::create_dir_all(root.join("images")).unwrap();
        let payload = b"tiny captured byte identity, not an image";
        fs::write(root.join("images/000000000010.jpg"), payload).unwrap();
        let schema = Arc::new(Schema::new(vec![
            Field::new("doc_id", DataType::Utf8, false),
            Field::new("text", DataType::Utf8, false),
            Field::new("text_version", DataType::Int64, false),
            Field::new("image_id", DataType::Int64, false),
            Field::new("image_path", DataType::Utf8, false),
            Field::new("media_version", DataType::Int64, false),
            Field::new("media_bytes", DataType::Int64, false),
            Field::new("media_sha256", DataType::Utf8, false),
        ]));
        let text = format!("version {version} original text");
        let hash = hex::encode(Sha256::digest(payload));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(vec!["same-doc"])),
                Arc::new(StringArray::from(vec![text])),
                Arc::new(Int64Array::from(vec![1])),
                Arc::new(Int64Array::from(vec![10])),
                Arc::new(StringArray::from(vec!["images/000000000010.jpg"])),
                Arc::new(Int64Array::from(vec![1])),
                Arc::new(Int64Array::from(vec![payload.len() as i64])),
                Arc::new(StringArray::from(vec![hash])),
            ],
        )
        .unwrap();
        let mut writer = ArrowWriter::try_new(
            fs::File::create(root.join("records.parquet")).unwrap(),
            schema,
            None,
        )
        .unwrap();
        writer.write(&batch).unwrap();
        writer.close().unwrap();
        let sha = hex::encode(Sha256::digest(
            fs::read(root.join("records.parquet")).unwrap(),
        ));
        let path = root.join("config.json");
        fs::write(
            &path,
            json!({"source":"records.parquet","sha256":sha,"timeout_ms":5000}).to_string(),
        )
        .unwrap();
        (path.to_str().unwrap().into(), sha)
    }
    fn features(&self, source: &str, tag: &str) -> (String, String, String) {
        let space = json!({"id":"two-d","dimensions":2,"dtype":"f64","metric":"cosine","normalization":"l2-scaled-f64-v1","origin":"numerical-fixture","model_id":"not-used","model_revision":"fixture-v1","preprocessing_id":"explicit-coordinates-v1","license":"test fixture"});
        let file = self.root.join(format!("features-{tag}.jsonl"));
        let header = json!({"format_version":1,"source_sha256":source,"documents":1,"space":space});
        let row = json!({"doc_id":"same-doc","vector":[3,4]});
        fs::write(&file, format!("{header}\n{row}\n")).unwrap();
        let pin = hex::encode(Sha256::digest(fs::read(&file).unwrap()));
        let query = self.root.join(format!("query-{tag}.json"));
        fs::write(
            &query,
            json!({"format_version":1,"source_sha256":source,"space":space,"vector":[3,4]})
                .to_string(),
        )
        .unwrap();
        (
            file.to_str().unwrap().into(),
            pin,
            query.to_str().unwrap().into(),
        )
    }
    fn run(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_guradb"))
            .arg("view")
            .arg(args[0])
            .arg("--store")
            .arg(self.root.join("store"))
            .args(&args[1..])
            .output()
            .unwrap()
    }
    fn ok(&self, args: &[&str]) -> Value {
        let p = self.run(args);
        assert!(p.status.success(), "{}", String::from_utf8_lossy(&p.stderr));
        serde_json::from_slice(&p.stdout).unwrap()
    }
    fn error(&self, args: &[&str], code: &str) {
        let p = self.run(args);
        assert!(!p.status.success());
        assert!(p.stdout.is_empty());
        let v: Value = serde_json::from_slice(&p.stderr).unwrap();
        assert_eq!(v["code"], code);
    }
    fn prepare(&self, path: &str, r: &str) -> Value {
        self.ok(&["prepare", "--config", path, "--request-id", r])
    }
    fn query(&self, id: &str) -> Value {
        self.ok(&[
            "query",
            "--view",
            id,
            "--sql",
            "SELECT doc_id,text FROM records LIMIT 5",
        ])
    }
}
#[test]
fn two_full_versions_pin_old_bytes_and_replay_does_not_roll_back_current() {
    let f = Fixture::new();
    let (a, sha_a) = f.input(1);
    let (b, sha_b) = f.input(2);
    assert_eq!(f.prepare(&a, "a")["state"], "prepared");
    f.error(
        &[
            "query",
            "--view",
            &sha_a,
            "--sql",
            "SELECT doc_id FROM records LIMIT 1",
        ],
        "view_not_ready",
    );
    f.ok(&["publish", "--request-id", "a"]);
    f.prepare(&b, "b");
    f.ok(&["publish", "--request-id", "b"]);
    assert_eq!(f.query("current")["view_id"], sha_b);
    assert_eq!(
        f.query(&sha_a)["result"]["rows"][0][1],
        "version 1 original text"
    );
    fs::remove_dir_all(f.root.join("input-1")).unwrap();
    let media = f.ok(&["media", "--view", &sha_a, "--asset-id", "10"]);
    assert_eq!(
        media["result"]["bytes_hex"],
        hex::encode(b"tiny captured byte identity, not an image")
    );
    assert_eq!(f.ok(&["publish", "--request-id", "a"])["current"], sha_b);
    assert_eq!(f.prepare(&b, "b")["replayed"], true);
    f.error(
        &["prepare", "--config", &b, "--request-id", "alias"],
        "view_identity_conflict",
    );
    let (third, _) = f.input(3);
    f.error(
        &["prepare", "--config", &third, "--request-id", "c"],
        "resource_limit",
    );
    for op in ["vector", "hybrid", "sample", "delete"] {
        f.error(&[op], "unsupported_view_operation");
    }
    assert_eq!(f.ok(&["recover"])["current"], sha_b);
}
#[test]
fn failed_capture_is_not_ready_and_public_recover_allows_exact_retry() {
    let f = Fixture::new();
    let (a, sha) = f.input(1);
    let media = f.root.join("input-1/images/000000000010.jpg");
    let bytes = fs::read(&media).unwrap();
    fs::write(&media, vec![b'x'; bytes.len()]).unwrap();
    f.error(
        &["prepare", "--config", &a, "--request-id", "a"],
        "media_changed",
    );
    let status = f.ok(&["status"]);
    assert!(status["current"].is_null());
    assert_eq!(status["recovery_required"], true);
    assert_eq!(status["views"], json!([]));
    f.error(
        &["prepare", "--config", &a, "--request-id", "a"],
        "view_recovery_required",
    );
    assert_eq!(f.ok(&["recover"])["recovery"], "reconciled");
    fs::write(media, bytes).unwrap();
    f.prepare(&a, "a");
    f.ok(&["publish", "--request-id", "a"]);
    assert_eq!(f.query("current")["view_id"], sha);
    let source = f
        .root
        .join("store/objects")
        .join(&sha)
        .join("records.parquet");
    let mut b = fs::read(&source).unwrap();
    b[0] ^= 1;
    fs::write(source, b).unwrap();
    f.error(
        &[
            "query",
            "--view",
            &sha,
            "--sql",
            "SELECT doc_id FROM records LIMIT 1",
        ],
        "source_changed",
    );
}
#[test]
fn unknown_format_layout_links_and_real_lock_are_rejected() {
    use std::os::{
        fd::AsRawFd,
        unix::fs::{symlink, MetadataExt},
    };
    let f = Fixture::new();
    let (a, _) = f.input(1);
    f.prepare(&a, "a");
    let store = f.root.join("store");
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(store.join(".lock"))
        .unwrap();
    let inode = lock.metadata().unwrap().ino();
    // SAFETY: lock owns this regular file descriptor for the complete assertion.
    assert_eq!(
        unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) },
        0
    );
    f.error(&["status"], "view_busy");
    drop(lock);
    f.ok(&["recover"]);
    assert_eq!(fs::metadata(store.join(".lock")).unwrap().ino(), inode);
    fs::write(store.join("foreign"), b"sentinel").unwrap();
    f.error(&["status"], "invalid_view_store");
    assert_eq!(fs::read(store.join("foreign")).unwrap(), b"sentinel");
    fs::remove_file(store.join("foreign")).unwrap();
    let catalog = store.join("catalog.json");
    let bytes = fs::read(&catalog).unwrap();
    let mut v: Value = serde_json::from_slice(&bytes).unwrap();
    v["format_version"] = json!(2);
    fs::write(&catalog, v.to_string()).unwrap();
    f.error(&["recover"], "invalid_view_store");
    fs::write(&catalog, bytes).unwrap();
    fs::rename(&catalog, store.join("original-catalog")).unwrap();
    symlink(store.join("original-catalog"), &catalog).unwrap();
    f.error(&["status"], "invalid_view_store");
}

#[test]
fn public_recover_handles_known_empty_bootstrap_but_never_guesses_away_data() {
    for phase in 0..3 {
        let f = Fixture::new();
        let store = f.root.join("store");
        fs::create_dir(&store).unwrap();
        if phase > 0 {
            fs::create_dir(store.join("objects")).unwrap();
        }
        if phase > 1 {
            fs::write(store.join("catalog.tmp"), b"partial initial descriptor").unwrap();
        }
        f.error(&["status"], "view_recovery_required");
        assert!(f.ok(&["recover"])["current"].is_null());
        let (config, _) = f.input(1);
        f.prepare(&config, "first");
        f.ok(&["publish", "--request-id", "first"]);
    }
    let f = Fixture::new();
    fs::create_dir_all(f.root.join("store/objects/surviving-data")).unwrap();
    f.error(&["recover"], "invalid_view_store");
    assert!(f.root.join("store/objects/surviving-data").exists());
}

#[test]
fn full_view_pins_source_feature_space_and_refuses_mutation() {
    let f = Fixture::new();
    let (config, source) = f.input(1);
    let (features, pin, query) = f.features(&source, "a");
    let prepared = f.ok(&[
        "prepare",
        "--config",
        &config,
        "--request-id",
        "full",
        "--features",
        &features,
        "--features-sha256",
        &pin,
    ]);
    let id = prepared["view_id"].as_str().unwrap();
    assert_ne!(id, source);
    assert_eq!(prepared["source_sha256"], source);
    let expected = hex::encode(Sha256::digest(
        format!("guradb-view-features-v2\n{source}\n{pin}\n").as_bytes(),
    ));
    assert_eq!(id, expected);
    f.ok(&["publish", "--request-id", "full"]);
    assert_eq!(f.ok(&["status"])["format_version"], 2);
    let result = f.ok(&["vector", "--view", id, "--query", &query, "--top-k", "1"]);
    assert_eq!(result["source_sha256"], source);
    assert_eq!(result["result"]["features_sha256"], pin);
    assert_eq!(result["result"]["hits"][0]["doc_id"], "same-doc");
    assert!((result["result"]["hits"][0]["score"].as_f64().unwrap() - 1.0).abs() < 1e-14);
    let mut q: Value = serde_json::from_slice(&fs::read(&query).unwrap()).unwrap();
    q["source_sha256"] = json!(id);
    fs::write(&query, q.to_string()).unwrap();
    f.error(
        &["vector", "--view", id, "--query", &query, "--top-k", "1"],
        "source_mismatch",
    );
    q["source_sha256"] = json!(source);
    q["space"]["model_revision"] = json!("different");
    fs::write(&query, q.to_string()).unwrap();
    f.error(
        &[
            "hybrid",
            "--view",
            id,
            "--query",
            &query,
            "--top-k",
            "1",
            "--text-query",
            "original",
        ],
        "space_mismatch",
    );
    let own = f.root.join("store/objects").join(id).join("features.jsonl");
    let mut b = fs::read(&own).unwrap();
    let n = b.len();
    b[n - 3] ^= 1;
    fs::write(own, b).unwrap();
    f.error(
        &[
            "query",
            "--view",
            id,
            "--sql",
            "SELECT doc_id FROM records LIMIT 1",
        ],
        "feature_changed",
    );
}
#[test]
fn legacy_store_cannot_acquire_mutable_feature_dependencies() {
    let f = Fixture::new();
    let (config, source) = f.input(1);
    f.prepare(&config, "plain");
    f.ok(&["publish", "--request-id", "plain"]);
    let (features, pin, query) = f.features(&source, "a");
    f.error(
        &[
            "prepare",
            "--config",
            &config,
            "--request-id",
            "full",
            "--features",
            &features,
            "--features-sha256",
            &pin,
        ],
        "unsupported_view_version",
    );
    f.error(
        &[
            "vector", "--view", &source, "--query", &query, "--top-k", "1",
        ],
        "view_features_required",
    );
    f.error(
        &["sample", "--view", &source, "--selection", &query],
        "view_features_required",
    );
    assert_eq!(f.query("current")["source_sha256"], source);
}
