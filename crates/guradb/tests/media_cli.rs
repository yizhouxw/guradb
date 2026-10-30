//! Real process byte-evidence regressions; public-JPEG truth is independently
//! checked from the original ZIP outside this synthetic binary fixture.
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
    os::unix::fs::symlink,
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
    payload: Vec<u8>,
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
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "guradb-media-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        fs::create_dir(root.join("images")).unwrap();
        let payload: Vec<_> = (0..200_576).map(|i| (i % 251) as u8).collect();
        fs::write(root.join("images/000000397133.jpg"), &payload).unwrap();
        let schema = Arc::new(Schema::new(vec![
            Field::new("image_id", DataType::Int64, false),
            Field::new("image_path", DataType::Utf8, false),
            Field::new("media_version", DataType::Int64, false),
            Field::new("media_bytes", DataType::Int64, false),
            Field::new("media_sha256", DataType::Utf8, false),
        ]));
        let hash = hex::encode(Sha256::digest(&payload));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(Int64Array::from(vec![397133, 397133])),
                Arc::new(StringArray::from(vec!["images/000000397133.jpg"; 2])),
                Arc::new(Int64Array::from(vec![1; 2])),
                Arc::new(Int64Array::from(vec![payload.len() as i64; 2])),
                Arc::new(StringArray::from(vec![hash.as_str(); 2])),
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
        Self {
            root,
            sha,
            payload,
            child: None,
        }
    }
    fn command(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_guradb"));
        command.args([
            "media",
            "--config",
            self.root.join("config.json").to_str().unwrap(),
            "--asset-id",
            "397133",
            "--source-sha256",
            &self.sha,
        ]);
        command.stdin(Stdio::null());
        command
    }
    fn output(&self) -> Output {
        self.command().output().unwrap()
    }
    fn success(&self) {
        let out = self.output();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        let value: Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(value["asset_id"], "397133");
        assert_eq!(value["source_sha256"], self.sha);
        assert_eq!(value["media_bytes"], self.payload.len());
        assert_eq!(
            hex::decode(value["bytes_hex"].as_str().unwrap()).unwrap(),
            self.payload
        );
    }
}
fn rejects(output: Output, code: &str) {
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert_eq!(
        serde_json::from_slice::<Value>(&output.stderr).unwrap()["code"],
        code
    );
}
#[test]
fn exact_bytes_bound_to_input_and_replaced_media_reject_then_recover() {
    let fixture = Fixture::new();
    fixture.success();
    let path = fixture.root.join("images/000000397133.jpg");
    let mut changed = fixture.payload.clone();
    changed[17] ^= 1;
    fs::write(&path, changed).unwrap();
    rejects(fixture.output(), "media_changed");
    fs::write(&path, &fixture.payload).unwrap();
    fixture.success();
    fs::remove_file(path).unwrap();
    rejects(fixture.output(), "media_invalid");
}
#[test]
fn file_and_directory_symlinks_refused_and_user_output_untouched() {
    let fixture = Fixture::new();
    let path = fixture.root.join("images/000000397133.jpg");
    let outside = fixture.root.join("outside.jpg");
    fs::write(&outside, &fixture.payload).unwrap();
    fs::remove_file(&path).unwrap();
    symlink(&outside, &path).unwrap();
    rejects(fixture.output(), "media_invalid");
    fs::remove_file(&path).unwrap();
    fs::write(&path, &fixture.payload).unwrap();
    fs::rename(fixture.root.join("images"), fixture.root.join("elsewhere")).unwrap();
    symlink(fixture.root.join("elsewhere"), fixture.root.join("images")).unwrap();
    rejects(fixture.output(), "media_invalid");
    let saved = fixture.root.join("saved.jpg");
    fs::write(&saved, b"existing user output").unwrap();
    rejects(
        fixture
            .command()
            .args(["--output", saved.to_str().unwrap()])
            .output()
            .unwrap(),
        "invalid_config",
    );
    assert_eq!(fs::read(saved).unwrap(), b"existing user output");
}
#[test]
fn real_sigint_during_blocked_media_stdout_has_no_file_artifacts_then_retry() {
    let mut fixture = Fixture::new();
    let before: Vec<_> = fs::read_dir(&fixture.root)
        .unwrap()
        .map(|p| p.unwrap().file_name())
        .collect();
    fixture.child = Some(
        fixture
            .command()
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    let child = fixture.child.as_mut().unwrap();
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
        assert!(Instant::now() < deadline, "media PID did not terminate");
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
    fixture.child.take();
    let after: Vec<_> = fs::read_dir(&fixture.root)
        .unwrap()
        .map(|p| p.unwrap().file_name())
        .collect();
    assert_eq!(before, after);
    fixture.success();
}
