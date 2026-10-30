//! Real process checks for pinned external numerical inputs, not model quality.
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
    io::Read,
    path::PathBuf,
    process::{Child, Command, Output, Stdio},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Fixture {
    root: PathBuf,
    sha: String,
    pin: String,
    child: Option<Child>,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        if let Some(child) = &mut self.child {
            let _ = child.kill();
            let _ = child.wait();
        }
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn space() -> Value {
    json!({"id":"math-2d-v1","dimensions":2,"dtype":"f64","metric":"cosine","normalization":"l2-scaled-f64-v1","origin":"numerical-fixture","model_id":"none","model_revision":"none","preprocessing_id":"self-authored","license":"self-authored"})
}
impl Fixture {
    fn new(rows: &[(&str, &str)], vectors: &[Vec<f64>]) -> Self {
        let root = std::env::temp_dir().join(format!(
            "guradb-vector-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let schema = Arc::new(Schema::new(vec![
            Field::new("doc_id", DataType::Utf8, false),
            Field::new("text", DataType::Utf8, false),
            Field::new("text_version", DataType::Int64, false),
        ]));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(
                    rows.iter().map(|r| r.0).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    rows.iter().map(|r| r.1).collect::<Vec<_>>(),
                )),
                Arc::new(Int64Array::from(vec![1; rows.len()])),
            ],
        )
        .unwrap();
        let source = root.join("records.parquet");
        let mut writer =
            ArrowWriter::try_new(fs::File::create(&source).unwrap(), schema, None).unwrap();
        writer.write(&batch).unwrap();
        writer.close().unwrap();
        let sha = hex::encode(Sha256::digest(fs::read(source).unwrap()));
        fs::write(
            root.join("config.json"),
            json!({"source":"records.parquet","sha256":sha,"timeout_ms":5000}).to_string(),
        )
        .unwrap();
        let mut lines = vec![
            json!({"format_version":1,"source_sha256":sha,"documents":rows.len(),"space":space()})
                .to_string(),
        ];
        for (row, vector) in rows.iter().zip(vectors) {
            lines.push(json!({"doc_id":row.0,"vector":vector}).to_string());
        }
        fs::write(root.join("features.jsonl"), lines.join("\n") + "\n").unwrap();
        let pin = hex::encode(Sha256::digest(
            fs::read(root.join("features.jsonl")).unwrap(),
        ));
        fs::write(
            root.join("query.json"),
            json!({"format_version":1,"source_sha256":sha,"space":space(),"vector":[1.0,0.0]})
                .to_string(),
        )
        .unwrap();
        Self {
            root,
            sha,
            pin,
            child: None,
        }
    }
    fn command(&self, hybrid: bool, k: &str) -> Command {
        let mut c = Command::new(env!("CARGO_BIN_EXE_guradb"));
        c.args([
            if hybrid { "hybrid" } else { "vector" },
            "--config",
            self.root.join("config.json").to_str().unwrap(),
            "--features",
            self.root.join("features.jsonl").to_str().unwrap(),
            "--features-sha256",
            &self.pin,
            "--query",
            self.root.join("query.json").to_str().unwrap(),
            "--top-k",
            k,
        ]);
        if hybrid {
            c.args(["--text-query", "fox"]);
        }
        c.stdin(Stdio::null());
        c
    }
    fn success(&self, hybrid: bool) -> Value {
        let p = self.command(hybrid, "20").output().unwrap();
        assert!(p.status.success(), "{}", String::from_utf8_lossy(&p.stderr));
        let v: Value = serde_json::from_slice(&p.stdout).unwrap();
        assert_eq!(v["source_sha256"], self.sha);
        assert_eq!(v["features_sha256"], self.pin);
        v
    }
}
fn rejects(p: Output, code: &str) {
    assert_eq!(p.status.code(), Some(1));
    assert!(p.stdout.is_empty());
    assert_eq!(
        serde_json::from_slice::<Value>(&p.stderr).unwrap()["code"],
        code
    );
}
#[test]
fn exact_geometry_and_opposing_bm25_rrf_ties() {
    let f = Fixture::new(
        &[("a", "red fox"), ("b", "fox fox fox"), ("c", "blue whale")],
        &[vec![2.0, 0.0], vec![0.0, 3.0], vec![-7.0, 0.0]],
    );
    let v = f.success(false);
    assert_eq!(v["hits"][0]["doc_id"], "a");
    assert_eq!(v["hits"][0]["score"], 1.0);
    assert_eq!(v["hits"][1]["score"], 0.0);
    assert_eq!(v["hits"][2]["score"], -1.0);
    let h = f.success(true);
    assert_eq!(h["hits"][0]["doc_id"], "a");
    assert_eq!(h["hits"][1]["doc_id"], "b");
    assert_eq!(h["hits"][0]["score"], h["hits"][1]["score"]);
    assert_eq!(h["hits"][0]["bm25_rank"], 2);
    assert_eq!(h["hits"][0]["vector_rank"], 1);
}
#[test]
fn pin_space_source_and_zero_reject_then_original_restores() {
    let f = Fixture::new(&[("a", "fox")], &[vec![1.0, 0.0]]);
    let path = f.root.join("features.jsonl");
    let original = fs::read(&path).unwrap();
    let mut changed = original.clone();
    changed.push(b' ');
    fs::write(&path, changed).unwrap();
    rejects(f.command(false, "1").output().unwrap(), "feature_changed");
    fs::write(&path, original).unwrap();
    let q = f.root.join("query.json");
    let original = fs::read(&q).unwrap();
    let mut v: Value = serde_json::from_slice(&original).unwrap();
    v["space"]["model_revision"] = json!("another");
    fs::write(&q, v.to_string()).unwrap();
    rejects(f.command(false, "1").output().unwrap(), "space_mismatch");
    let mut v: Value = serde_json::from_slice(&original).unwrap();
    v["source_sha256"] = json!("0".repeat(64));
    fs::write(&q, v.to_string()).unwrap();
    rejects(f.command(false, "1").output().unwrap(), "source_mismatch");
    let mut v: Value = serde_json::from_slice(&original).unwrap();
    v["vector"] = json!([0.0, -0.0]);
    fs::write(&q, v.to_string()).unwrap();
    rejects(f.command(false, "1").output().unwrap(), "invalid_vector");
    fs::write(q, original).unwrap();
    f.success(false);
}
#[test]
fn real_closed_output_pipe_exits_without_files_and_same_inputs_retry() {
    let text = "fox ".repeat(2048);
    let names: Vec<_> = (0..20).map(|i| format!("d{i:02}")).collect();
    let rows: Vec<_> = names.iter().map(|n| (n.as_str(), text.as_str())).collect();
    let mut f = Fixture::new(&rows, &vec![vec![1.0, 0.0]; 20]);
    let before: Vec<_> = [
        "records.parquet",
        "config.json",
        "features.jsonl",
        "query.json",
    ]
    .iter()
    .map(|n| fs::read(f.root.join(n)).unwrap())
    .collect();
    f.child = Some(
        f.command(true, "20")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    let child = f.child.as_mut().unwrap();
    let mut prefix = [0];
    child
        .stdout
        .as_mut()
        .unwrap()
        .read_exact(&mut prefix)
        .unwrap();
    assert_eq!(prefix, [b'{']);
    drop(child.stdout.take());
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            assert_eq!(status.code(), Some(1));
            break;
        }
        assert!(Instant::now() < deadline, "vector PID did not exit");
        std::thread::sleep(Duration::from_millis(10));
    }
    let mut error = String::new();
    child
        .stderr
        .take()
        .unwrap()
        .read_to_string(&mut error)
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&error).unwrap()["code"],
        "output_failed"
    );
    assert!(!PathBuf::from(format!("/proc/{}", child.id())).exists());
    f.child.take();
    for (i, name) in [
        "records.parquet",
        "config.json",
        "features.jsonl",
        "query.json",
    ]
    .iter()
    .enumerate()
    {
        assert_eq!(fs::read(f.root.join(name)).unwrap(), before[i]);
    }
    assert_eq!(fs::read_dir(&f.root).unwrap().count(), 4);
    assert_eq!(f.success(true)["hits"].as_array().unwrap().len(), 20);
}

#[test]
fn blank_feature_lines_preserve_full_document_identity_and_line_limits() {
    let mut f = Fixture::new(
        &[("a", "fox"), ("b", "blue")],
        &[vec![1.0, 0.0], vec![0.0, 1.0]],
    );
    let path = f.root.join("features.jsonl");
    let original = fs::read_to_string(&path).unwrap();
    let padded = original.lines().collect::<Vec<_>>().join("\n\n \t\n") + "\n\n";
    fs::write(&path, padded).unwrap();
    f.pin = hex::encode(Sha256::digest(fs::read(&path).unwrap()));
    assert_eq!(f.success(false)["hits"].as_array().unwrap().len(), 2);
    let huge = original + &" ".repeat(65537) + "\n";
    fs::write(&path, huge).unwrap();
    f.pin = hex::encode(Sha256::digest(fs::read(&path).unwrap()));
    rejects(f.command(false, "2").output().unwrap(), "resource_limit");
}
