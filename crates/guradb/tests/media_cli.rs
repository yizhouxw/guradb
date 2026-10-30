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

fn pcm16_fixture() -> Vec<u8> {
    // Two independently specified stereo frames: [-32768, 0], [1, 32767].
    hex::decode("524946462c00000057415645666d7420100000000100020044ac000010b10200040010006461746108000000008000000100ff7f").unwrap()
}
impl Fixture {
    fn typed(payload: Vec<u8>, kind: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "guradb-media-v2-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let (directory, extension) = if kind == "audio/wav" {
            ("audio", "wav")
        } else {
            ("images", "jpg")
        };
        fs::create_dir(root.join(directory)).unwrap();
        let path = format!("{directory}/000000397133.{extension}");
        fs::write(root.join(&path), &payload).unwrap();
        let schema = Arc::new(Schema::new(vec![
            Field::new("doc_id", DataType::Utf8, false),
            Field::new("text", DataType::Utf8, false),
            Field::new("text_version", DataType::Int64, false),
            Field::new("asset_id", DataType::Int64, false),
            Field::new("asset_path", DataType::Utf8, false),
            Field::new("asset_type", DataType::Utf8, false),
            Field::new("media_version", DataType::Int64, false),
            Field::new("media_bytes", DataType::Int64, false),
            Field::new("media_sha256", DataType::Utf8, false),
        ]));
        let hash = hex::encode(Sha256::digest(&payload));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(vec!["d1", "d2"])),
                Arc::new(StringArray::from(vec!["steam train whistle"; 2])),
                Arc::new(Int64Array::from(vec![1; 2])),
                Arc::new(Int64Array::from(vec![397133; 2])),
                Arc::new(StringArray::from(vec![path.as_str(); 2])),
                Arc::new(StringArray::from(vec![kind; 2])),
                Arc::new(Int64Array::from(vec![2; 2])),
                Arc::new(Int64Array::from(vec![payload.len() as i64; 2])),
                Arc::new(StringArray::from(vec![hash.as_str(); 2])),
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
        Self {
            root,
            sha,
            payload,
            child: None,
        }
    }
    fn run_args(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_guradb"))
            .args(args)
            .stdin(Stdio::null())
            .output()
            .unwrap()
    }
}
#[test]
fn typed_wav_full_bytes_metadata_wrong_type_format_and_retry() {
    let f = Fixture::typed(pcm16_fixture(), "audio/wav");
    f.success();
    let value: Value = serde_json::from_slice(&f.output().stdout).unwrap();
    assert_eq!(value["asset_type"], "audio/wav");
    assert_eq!(value["media_version"], 2);
    assert_eq!(value["asset_path"], "audio/000000397133.wav");
    assert!(value.get("image_path").is_none());
    assert_eq!(
        value["audio"],
        json!({"encoding":"pcm_s16le","sample_rate":44100,"channels":2,"bits_per_sample":16,"frames":2})
    );
    let path = f.root.join("audio/000000397133.wav");
    let mut changed = f.payload.clone();
    changed[20] = 3;
    fs::write(&path, &changed).unwrap();
    rejects(f.output(), "media_changed");
    fs::write(path, &f.payload).unwrap();
    f.success();
    let malformed = Fixture::typed(changed, "audio/wav");
    rejects(malformed.output(), "invalid_media_format");
    let wrong_type = Fixture::typed(pcm16_fixture(), "image/jpeg");
    rejects(wrong_type.output(), "invalid_media_format");
}
#[test]
fn typed_wav_owned_view_survives_source_removal_and_refuses_feature_view() {
    let f = Fixture::typed(pcm16_fixture(), "audio/wav");
    let config = f.root.join("config.json");
    let config = config.to_str().unwrap();
    let store = f.root.join("store");
    let store = store.to_str().unwrap();
    let prepare = f.run_args(&[
        "view",
        "prepare",
        "--store",
        store,
        "--config",
        config,
        "--request-id",
        "typed",
    ]);
    assert!(
        prepare.status.success(),
        "{}",
        String::from_utf8_lossy(&prepare.stderr)
    );
    let id: Value = serde_json::from_slice(&prepare.stdout).unwrap();
    let id = id["view_id"].as_str().unwrap();
    let published = f.run_args(&["view", "publish", "--store", store, "--request-id", "typed"]);
    assert!(
        published.status.success(),
        "{}",
        String::from_utf8_lossy(&published.stderr)
    );
    fs::remove_file(f.root.join("audio/000000397133.wav")).unwrap();
    let media_args = [
        "view",
        "media",
        "--store",
        store,
        "--view",
        id,
        "--asset-id",
        "397133",
    ];
    // The owned WAV and image directory share one three-asset budget.
    let images = f.root.join("store/objects").join(id).join("images");
    for extra in 397134..=397136 {
        fs::write(images.join(format!("{extra:012}.jpg")), []).unwrap();
    }
    rejects(f.run_args(&media_args), "resource_limit");
    for extra in 397134..=397136 {
        fs::remove_file(images.join(format!("{extra:012}.jpg"))).unwrap();
    }
    let output = f.run_args(&media_args);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["result"]["audio"]["frames"], 2);
    assert_eq!(
        hex::decode(value["result"]["bytes_hex"].as_str().unwrap()).unwrap(),
        f.payload
    );
    fs::write(f.root.join("audio/000000397133.wav"), &f.payload).unwrap();
    let other = f.root.join("feature-store");
    let other = other.to_str().unwrap();
    rejects(
        f.run_args(&[
            "view",
            "prepare",
            "--store",
            other,
            "--config",
            config,
            "--request-id",
            "bad",
            "--features",
            "/missing",
            "--features-sha256",
            &"0".repeat(64),
        ]),
        "unsupported_media_contract",
    );
}
#[test]
fn media_v2_is_not_an_image_feature_or_sample_corpus() {
    let f = Fixture::typed(pcm16_fixture(), "audio/wav");
    let config = f.root.join("config.json");
    let config = config.to_str().unwrap();
    rejects(
        f.run_args(&[
            "vector",
            "--config",
            config,
            "--features",
            "/missing",
            "--features-sha256",
            &"0".repeat(64),
            "--query",
            "/missing",
            "--top-k",
            "1",
        ]),
        "unsupported_media_contract",
    );
    let selection = f.root.join("selection.json");
    fs::write(
        &selection,
        json!({"format_version":1,"source_sha256":f.sha,"seed":0,"doc_ids":["d1","d2"]})
            .to_string(),
    )
    .unwrap();
    rejects(
        f.run_args(&[
            "sample",
            "--config",
            config,
            "--selection",
            selection.to_str().unwrap(),
        ]),
        "unsupported_media_contract",
    );
}
