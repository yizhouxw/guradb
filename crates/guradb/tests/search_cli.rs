//! Real search-process regressions; independent corpus/math/media oracles are
//! maintained separately from this author regression fixture.
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
impl Fixture {
    fn new(rows: &[(&str, &str)], version: i64) -> Self {
        let root = std::env::temp_dir().join(format!(
            "guradb-search-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let source = root.join("records.parquet");
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
                Arc::new(Int64Array::from(vec![version; rows.len()])),
            ],
        )
        .unwrap();
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
        Self {
            root,
            sha,
            child: None,
        }
    }
    fn command(&self, query: &str, k: &str) -> Command {
        let mut c = Command::new(env!("CARGO_BIN_EXE_guradb"));
        c.args([
            "search",
            "--config",
            self.root.join("config.json").to_str().unwrap(),
            "--query",
            query,
            "--top-k",
            k,
        ]);
        c.stdin(Stdio::null());
        c
    }
    fn success(&self, query: &str, k: &str) -> Value {
        let p = self.command(query, k).output().unwrap();
        assert!(p.status.success(), "{}", String::from_utf8_lossy(&p.stderr));
        let v: Value = serde_json::from_slice(&p.stdout).unwrap();
        assert_eq!(v["source_sha256"], self.sha);
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
fn one_doc_closed_form_score_and_analyzer_query_dedup() {
    let f = Fixture::new(&[("only", "FOX")], 1);
    let x = f.success("Fox fox", "10");
    // For N=df=tf=dl=avgdl=1, normalization is one and score is ln(4/3).
    assert!((x["hits"][0]["score"].as_f64().unwrap() - 0.28768207245178085).abs() < 1e-12);
    assert_eq!(x["hits"][0]["text"], "FOX");
    assert_eq!(x["terms"].as_array().unwrap().len(), 1);
    assert_eq!(x["terms"][0]["df"], 1);
    assert_eq!(x["avgdl"], 1.0);
    assert_eq!(x, f.success("fox", "10"));
    assert_eq!(f.success("fo", "10")["hits"], json!([]));
}
#[test]
fn stable_ties_top_k_no_match_and_tf_ranking() {
    let f = Fixture::new(
        &[("z", "fox fox"), ("a", "fox fox"), ("blue", "blue whale")],
        1,
    );
    let all = f.success("FOX", "20");
    assert_eq!(all["hits"][0]["doc_id"], "a");
    assert_eq!(all["hits"][1]["doc_id"], "z");
    assert_eq!(all["hits"][0]["score"], all["hits"][1]["score"]);
    let one = f.success("fox", "1");
    assert_eq!(one["hits"].as_array().unwrap().len(), 1);
    assert_eq!(one["truncated"], true);
    assert_eq!(f.success("unknown", "1")["truncated"], false);
    let tf = Fixture::new(
        &[("a", "red fox"), ("b", "fox fox fox"), ("c", "blue whale")],
        1,
    );
    let ranked = tf.success("fox", "2");
    assert_eq!(ranked["hits"][0]["doc_id"], "b");
    assert_eq!(ranked["hits"][1]["doc_id"], "a");
}
#[test]
fn duplicate_ids_unknown_version_and_illegal_query_refuse_without_output() {
    let f = Fixture::new(&[("x", "fox"), ("x", "blue")], 1);
    rejects(
        f.command("fox", "1").output().unwrap(),
        "invalid_search_input",
    );
    let f = Fixture::new(&[("x", "fox")], 2);
    rejects(
        f.command("fox", "1").output().unwrap(),
        "unsupported_search_contract",
    );
    let f = Fixture::new(&[("x", "fox")], 1);
    for q in ["", "!!!", "中文", "a b c d e f g h i"] {
        rejects(f.command(q, "1").output().unwrap(), "invalid_search_query");
    }
    rejects(f.command("fox", "0").output().unwrap(), "invalid_config");
    fs::write(
        f.root.join("config.json"),
        json!({"source":"records.parquet","sha256":"0".repeat(64)}).to_string(),
    )
    .unwrap();
    rejects(f.command("fox", "1").output().unwrap(), "source_changed");
}
#[test]
fn real_blocked_search_stdout_sigint_exits_and_same_corpus_retries() {
    let text = "fox ".repeat(2048);
    let keys: Vec<_> = (0..20).map(|i| format!("d{i:02}")).collect();
    let rows: Vec<_> = keys.iter().map(|k| (k.as_str(), text.as_str())).collect();
    let mut f = Fixture::new(&rows, 1);
    let source_before = fs::read(f.root.join("records.parquet")).unwrap();
    f.child = Some(
        f.command("fox", "20")
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
    assert!(Command::new("kill")
        .args(["-INT", &child.id().to_string()])
        .status()
        .unwrap()
        .success());
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            assert_eq!(status.code(), Some(130));
            break;
        }
        assert!(Instant::now() < deadline, "search PID failed to exit");
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
        "cancelled"
    );
    assert!(!PathBuf::from(format!("/proc/{}", child.id())).exists());
    f.child.take();
    assert_eq!(
        fs::read(f.root.join("records.parquet")).unwrap(),
        source_before
    );
    assert_eq!(fs::read_dir(&f.root).unwrap().count(), 2);
    assert_eq!(f.success("fox", "20")["hits"].as_array().unwrap().len(), 20);
}
