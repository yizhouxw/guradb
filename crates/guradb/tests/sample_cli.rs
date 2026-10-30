//! Real Rust selection processes; tiny byte fixtures are not decoded images.
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
    sha: String,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "guradb-sample-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(root.join("images")).unwrap();
        let ids = [10_i64, 10, 20, 30];
        let paths: Vec<_> = ids
            .iter()
            .map(|id| format!("images/{id:012}.jpg"))
            .collect();
        let mut hashes = Vec::new();
        let mut sizes = Vec::new();
        for id in ids {
            let bytes = format!("tiny nondecoded media bytes {id}").into_bytes();
            fs::write(root.join(format!("images/{id:012}.jpg")), &bytes).unwrap();
            hashes.push(hex::encode(Sha256::digest(&bytes)));
            sizes.push(bytes.len() as i64);
        }
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
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(vec!["a", "b", "c", "d"])),
                Arc::new(StringArray::from(vec![
                    "first ten",
                    "second ten",
                    "twenty",
                    "thirty",
                ])),
                Arc::new(Int64Array::from(vec![1; 4])),
                Arc::new(Int64Array::from(ids.to_vec())),
                Arc::new(StringArray::from(paths)),
                Arc::new(Int64Array::from(vec![1; 4])),
                Arc::new(Int64Array::from(sizes)),
                Arc::new(StringArray::from(hashes)),
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
        fs::write(
            root.join("config.json"),
            json!({"source":"records.parquet","sha256":sha,"timeout_ms":5000}).to_string(),
        )
        .unwrap();
        Self { root, sha }
    }
    fn request(&self, ids: Value, seed: Value) -> Value {
        json!({"format_version":1,"source_sha256":self.sha,"seed":seed,"doc_ids":ids})
    }
    fn run(&self, value: &Value) -> Output {
        fs::write(self.root.join("selection.json"), value.to_string()).unwrap();
        Command::new(env!("CARGO_BIN_EXE_guradb"))
            .args(["sample", "--config"])
            .arg(self.root.join("config.json"))
            .arg("--selection")
            .arg(self.root.join("selection.json"))
            .output()
            .unwrap()
    }
    fn reject(&self, value: &Value) {
        let r = self.run(value);
        assert!(!r.status.success());
        assert!(r.stdout.is_empty());
    }
}

#[test]
fn exact_members_group_truth_stable_order_and_minimal_subset() {
    let f = Fixture::new();
    let request = f.request(json!(["d", "b", "c", "a"]), json!(0));
    let a = f.run(&request);
    assert!(a.status.success(), "{:?}", a);
    let b = f.run(&request);
    assert_eq!(a.stdout, b.stdout);
    let result: Value = serde_json::from_slice(&a.stdout).unwrap();
    assert_eq!(result["selected_doc_ids"], json!(["a", "b", "c", "d"]));
    assert_eq!(result["model"], "not_used");
    // External Python hashlib frozen vector for seed0/asset30, not runtime-produced expected.
    assert_eq!(
        result["groups"][0],
        json!({"asset_id":"30","sha256":"0673339c1d724640c47a112d370bdab512945fe5d8438ae587224ac4aefa8af5","split":"validation"})
    );
    assert_eq!(
        result["train"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| x["doc_id"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["a", "b", "c"]
    );
    assert_eq!(result["validation"][0]["doc_id"], "d");
    let sub = f.run(&f.request(json!(["a", "c"]), json!(4294967295_u32)));
    assert!(sub.status.success());
    let sub: Value = serde_json::from_slice(&sub.stdout).unwrap();
    assert_eq!(sub["selected_doc_ids"], json!(["a", "c"]));
    assert_eq!(
        sub["train"].as_array().unwrap().len() + sub["validation"].as_array().unwrap().len(),
        2
    );
}

#[test]
fn bad_versions_seed_members_and_unknown_fields_reject() {
    let f = Fixture::new();
    let good = f.request(json!(["a", "c"]), json!(0));
    for ids in [
        json!([]),
        json!(["a", "a", "c"]),
        json!(["missing", "c"]),
        json!(["a", "b"]),
        json!(["../a", "c"]),
        json!(vec!["a"; 201]),
    ] {
        f.reject(&f.request(ids, json!(0)));
    }
    for seed in [
        json!(-1),
        json!(4294967296_u64),
        json!(1.5),
        json!(true),
        Value::Null,
    ] {
        f.reject(&f.request(json!(["a", "c"]), seed));
    }
    for (field, value) in [
        ("format_version", json!(2)),
        ("source_sha256", json!("0".repeat(64))),
        ("split_fraction", json!(0.5)),
    ] {
        let mut r = good.clone();
        r[field] = value;
        f.reject(&r);
    }
}

#[test]
fn missing_same_length_replacement_and_wrong_source_fail_then_recover() {
    let f = Fixture::new();
    let request = f.request(json!(["a", "c"]), json!(0));
    let path = f.root.join("images/000000000010.jpg");
    let original = fs::read(&path).unwrap();
    fs::remove_file(&path).unwrap();
    f.reject(&request);
    fs::write(&path, &original).unwrap();
    assert!(f.run(&request).status.success());
    fs::write(&path, vec![b'x'; original.len()]).unwrap();
    f.reject(&request);
    fs::write(&path, &original).unwrap();
    assert!(f.run(&request).status.success());
    let source = f.root.join("records.parquet");
    let original = fs::read(&source).unwrap();
    fs::write(&source, vec![0; original.len()]).unwrap();
    f.reject(&request);
    fs::write(&source, &original).unwrap();
    assert!(f.run(&request).status.success());
}

#[test]
fn oversized_selection_and_closed_stdout_exit_then_same_request_recovers() {
    let f = Fixture::new();
    let request = f.request(json!(["a", "c"]), json!(0));
    fs::write(f.root.join("selection.json"), vec![b' '; 65537]).unwrap();
    let r = Command::new(env!("CARGO_BIN_EXE_guradb"))
        .arg("sample")
        .arg("--config")
        .arg(f.root.join("config.json"))
        .arg("--selection")
        .arg(f.root.join("selection.json"))
        .output()
        .unwrap();
    assert!(!r.status.success());
    assert!(r.stdout.is_empty());
    assert!(f.run(&request).status.success());
    let mut child = Command::new(env!("CARGO_BIN_EXE_guradb"))
        .arg("sample")
        .arg("--config")
        .arg(f.root.join("config.json"))
        .arg("--selection")
        .arg(f.root.join("selection.json"))
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    drop(child.stdout.take());
    let status = child.wait().unwrap();
    assert!(!status.success());
    assert!(f.run(&request).status.success());
}
