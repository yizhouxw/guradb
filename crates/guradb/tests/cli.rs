//! Real process/pipe tests. No product sleep hook or simulated cancellation.
use arrow::{
    array::StringArray,
    datatypes::{DataType, Field, Schema},
    record_batch::RecordBatch,
};
use parquet::arrow::ArrowWriter;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Arc,
    time::{Duration, Instant},
};

struct Scope {
    directory: PathBuf,
    child: Option<Child>,
}
impl Drop for Scope {
    fn drop(&mut self) {
        if let Some(child) = self.child.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
        let _ = fs::remove_dir_all(&self.directory);
    }
}

fn setup(timeout: u64) -> (Scope, PathBuf) {
    let directory =
        std::env::temp_dir().join(format!("guradb-cli-{}-{timeout}", std::process::id()));
    fs::create_dir(&directory).unwrap();
    let source = directory.join("wide.parquet");
    let schema = Arc::new(Schema::new(vec![Field::new(
        "title",
        DataType::Utf8,
        false,
    )]));
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![Arc::new(StringArray::from(vec!["x".repeat(1500); 1000]))],
    )
    .unwrap();
    let mut writer =
        ArrowWriter::try_new(fs::File::create(&source).unwrap(), schema, None).unwrap();
    writer.write(&batch).unwrap();
    writer.close().unwrap();
    let digest = hex::encode(Sha256::digest(fs::read(&source).unwrap()));
    let config = directory.join("config.json");
    fs::write(
        &config,
        json!({"source": "wide.parquet", "sha256":digest, "timeout_ms":timeout}).to_string(),
    )
    .unwrap();
    (
        Scope {
            directory,
            child: None,
        },
        config,
    )
}

fn start(scope: &mut Scope, config: &Path) {
    scope.child = Some(
        Command::new(env!("CARGO_BIN_EXE_guradb"))
            .args([
                "query",
                "--config",
                config.to_str().unwrap(),
                "--sql",
                "SELECT * FROM records",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap(),
    );
}

fn await_exit(child: &mut Child, expected: i32) {
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            assert_eq!(status.code(), Some(expected));
            break;
        }
        assert!(
            Instant::now() < deadline,
            "real CLI PID {} did not terminate",
            child.id()
        );
        std::thread::sleep(Duration::from_millis(10)); // bounded test polling only
    }
    let mut error = String::new();
    child
        .stderr
        .take()
        .unwrap()
        .read_to_string(&mut error)
        .unwrap();
    let code = match expected {
        124 => "timeout",
        130 => "cancelled",
        _ => "output_failed",
    };
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&error).unwrap()["code"],
        code
    );
    assert!(
        !std::path::Path::new(&format!("/proc/{}", child.id())).exists(),
        "exited PID remains live"
    );
}

#[test]
fn real_timeout_terminates_while_output_consumer_stops_reading() {
    let (mut scope, config) = setup(300);
    start(&mut scope, &config);
    let child = scope.child.as_mut().unwrap();
    let mut prefix = [0];
    child
        .stdout
        .as_mut()
        .unwrap()
        .read_exact(&mut prefix)
        .unwrap();
    assert_eq!(prefix, [b'{']);
    // Keep the pipe open without draining it. More than 1MiB of actual result
    // cannot fit in its kernel buffer; the process must enforce its deadline.
    await_exit(child, 124);
}

#[test]
fn real_sigint_terminates_blocked_output_and_releases_process() {
    let (mut scope, config) = setup(5000);
    start(&mut scope, &config);
    let child = scope.child.as_mut().unwrap();
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
    await_exit(child, 130);
}

#[test]
fn closed_output_pipe_fails_and_releases_process() {
    let (mut scope, config) = setup(5001);
    start(&mut scope, &config);
    let child = scope.child.as_mut().unwrap();
    drop(child.stdout.take());
    await_exit(child, 1);
}

#[test]
fn changed_open_input_rejects_then_original_bytes_can_run_again() {
    let (mut scope, config) = setup(6000);
    let source = scope.directory.join("wide.parquet");
    let schema = Arc::new(Schema::new(vec![Field::new(
        "title",
        DataType::Utf8,
        false,
    )]));
    let values: Vec<_> = (0..60_000)
        .map(|i| format!("{i:06}{}", "x".repeat(250)))
        .collect();
    let batch =
        RecordBatch::try_new(schema.clone(), vec![Arc::new(StringArray::from(values))]).unwrap();
    let mut writer =
        ArrowWriter::try_new(fs::File::create(&source).unwrap(), schema, None).unwrap();
    writer.write(&batch).unwrap();
    writer.close().unwrap();
    let original = fs::read(&source).unwrap();
    let digest = hex::encode(Sha256::digest(&original));
    fs::write(
        &config,
        json!({"source":"wide.parquet", "sha256":digest, "timeout_ms":6000}).to_string(),
    )
    .unwrap();
    start(&mut scope, &config);
    let child = scope.child.as_mut().unwrap();
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let open = fs::read_dir(format!("/proc/{}/fd", child.id()))
            .unwrap()
            .filter_map(|p| p.ok())
            .any(|p| fs::read_link(p.path()).is_ok_and(|path| path == source));
        if open {
            break;
        }
        assert!(
            child.try_wait().unwrap().is_none(),
            "process exited before observing its real source FD"
        );
        assert!(Instant::now() < deadline, "source FD was not observed");
        std::thread::yield_now();
    }
    assert!(Command::new("kill")
        .args(["-STOP", &child.id().to_string()])
        .status()
        .unwrap()
        .success());
    // Change the real local source while this PID holds its input FD, without
    // adding a delay/injection option to production. SHA256 must reject it.
    use std::io::Write;
    fs::OpenOptions::new()
        .append(true)
        .open(&source)
        .unwrap()
        .write_all(b"changed")
        .unwrap();
    assert!(Command::new("kill")
        .args(["-CONT", &child.id().to_string()])
        .status()
        .unwrap()
        .success());
    let output = scope.child.take().unwrap().wait_with_output().unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&output.stderr).unwrap()["code"],
        "source_changed"
    );
    fs::write(&source, original).unwrap();
    let retry = Command::new(env!("CARGO_BIN_EXE_guradb"))
        .args([
            "query",
            "--config",
            config.to_str().unwrap(),
            "--sql",
            "SELECT title FROM records LIMIT 1",
        ])
        .output()
        .unwrap();
    assert!(
        retry.status.success(),
        "{}",
        String::from_utf8_lossy(&retry.stderr)
    );
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&retry.stdout).unwrap()["source_sha256"],
        digest
    );
}
