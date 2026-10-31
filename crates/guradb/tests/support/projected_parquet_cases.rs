//! Real multi-GET/CLI tests. These engineering rows are not product oracles.
use arrow::{
    array::{ArrayRef, BooleanArray, Int64Array, StringArray},
    datatypes::{DataType, Field, Schema},
    record_batch::RecordBatch,
};
use bytes::Bytes;
use parquet::{
    arrow::{arrow_reader::ParquetRecordBatchReaderBuilder, ArrowWriter},
    basic::{Compression, Encoding},
    file::properties::{WriterProperties, WriterVersion},
    schema::types::ColumnPath,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{Read, Write},
    net::TcpListener,
    path::PathBuf,
    process::{Child, Command, Output, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
static NEXT: AtomicUsize = AtomicUsize::new(0);
fn sha(raw: &[u8]) -> String {
    hex::encode(Sha256::digest(raw))
}
fn fixture(version: WriterVersion, count: usize, bad_codec: bool) -> Vec<u8> {
    let schema = Arc::new(Schema::new(vec![
        Field::new("number", DataType::Int64, true),
        Field::new("text", DataType::Utf8, true),
        Field::new("flag", DataType::Boolean, true),
    ]));
    let arrays: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from(
            (0..count)
                .map(|i| match i % 4 {
                    0 => Some(i64::MIN),
                    1 => None,
                    2 => Some(i64::MAX),
                    _ => Some(0),
                })
                .collect::<Vec<_>>(),
        )),
        Arc::new(StringArray::from(
            (0..count)
                .map(|i| match i % 4 {
                    0 => Some("雪/quote\""),
                    1 => Some(""),
                    2 => None,
                    _ => Some("last"),
                })
                .collect::<Vec<_>>(),
        )),
        Arc::new(BooleanArray::from(
            (0..count)
                .map(|i| match i % 4 {
                    0 => Some(true),
                    1 => Some(false),
                    2 => None,
                    _ => Some(true),
                })
                .collect::<Vec<_>>(),
        )),
    ];
    let mut props = WriterProperties::builder()
        .set_dictionary_enabled(false)
        .set_encoding(Encoding::PLAIN)
        .set_compression(Compression::UNCOMPRESSED)
        .set_writer_version(version)
        .set_max_row_group_size(count.div_ceil(4));
    if bad_codec {
        props = props.set_column_compression(ColumnPath::from("flag"), Compression::SNAPPY);
    }
    let mut bytes = Vec::new();
    let mut writer = ArrowWriter::try_new(&mut bytes, schema.clone(), Some(props.build())).unwrap();
    writer
        .write(&RecordBatch::try_new(schema, arrays).unwrap())
        .unwrap();
    writer.close().unwrap();
    bytes
}
fn request(bytes: &[u8], port: u16, columns: Vec<usize>, groups: Vec<usize>) -> Value {
    let builder = ParquetRecordBatchReaderBuilder::try_new(Bytes::copy_from_slice(bytes)).unwrap();
    let md = builder.metadata();
    let n = bytes.len();
    let footer = u32::from_le_bytes(bytes[n - 8..n - 4].try_into().unwrap()) as usize + 8;
    let range = |offset: usize, length: usize| json!({"offset":offset,"length":length,"sha256":sha(&bytes[offset..offset+length])});
    let mut chunks = Vec::new();
    for (g, group) in md.row_groups().iter().enumerate() {
        for (c, col) in group.columns().iter().enumerate() {
            let (offset, length) = col.byte_range();
            let mut part = range(offset as usize, length as usize);
            part["row_group"] = json!(g);
            part["column"] = json!(c);
            chunks.push(part);
        }
    }
    json!({"version":1,"origin":format!("http://127.0.0.1:{port}"),"object_key":"synthetic/table.parquet","etag":"\"fixed-v1\"","object_bytes":n,"source_sha256_provenance":sha(bytes),"header":range(0,4),"footer":range(n-footer,footer),"chunks":chunks,"columns":columns,"row_groups":groups})
}
struct Input {
    root: PathBuf,
    child: Option<Child>,
}
impl Input {
    fn new(value: &Value) -> Self {
        let root = std::env::temp_dir().join(format!(
            "guradb-projection-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("request.json"), value.to_string()).unwrap();
        Self { root, child: None }
    }
    fn command(&self) -> Command {
        let mut c = Command::new(env!("CARGO_BIN_EXE_guradb"));
        c.args([
            "parquet-read",
            "--request",
            self.root.join("request.json").to_str().unwrap(),
        ])
        .stdin(Stdio::null());
        c
    }
    fn run(&self) -> Output {
        self.command().output().unwrap()
    }
}
impl Drop for Input {
    fn drop(&mut self) {
        if let Some(c) = &mut self.child {
            let _ = c.kill();
            let _ = c.wait();
        }
        let _ = fs::remove_dir_all(&self.root);
    }
}
#[derive(Clone, Copy)]
enum Mode {
    Normal,
    WrongVersion,
    CorruptFooter,
    LargeHeaders,
    HoldThird,
}
struct Server {
    port: u16,
    stop: Arc<AtomicBool>,
    thread: Option<thread::JoinHandle<()>>,
    ranges: Arc<Mutex<Vec<(usize, usize)>>>,
    ready: mpsc::Receiver<()>,
}
impl Server {
    fn new(bytes: Vec<u8>, mode: Mode) -> Self {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        listener.set_nonblocking(true).unwrap();
        let port = listener.local_addr().unwrap().port();
        let stop = Arc::new(AtomicBool::new(false));
        let flag = stop.clone();
        let ranges = Arc::new(Mutex::new(Vec::new()));
        let log = ranges.clone();
        let (tx, ready) = mpsc::channel();
        let thread = thread::spawn(move || {
            let until = Instant::now() + Duration::from_secs(15);
            while !flag.load(Ordering::SeqCst) && Instant::now() < until {
                let mut socket = match listener.accept() {
                    Ok((s, _)) => s,
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(2));
                        continue;
                    }
                    Err(_) => return,
                };
                socket
                    .set_read_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                socket
                    .set_write_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                let mut raw = Vec::new();
                let mut one = [0];
                while !raw.ends_with(b"\r\n\r\n") && raw.len() < 16384 {
                    if socket.read_exact(&mut one).is_err() {
                        return;
                    }
                    raw.push(one[0]);
                }
                let text = std::str::from_utf8(&raw).unwrap();
                assert!(text.starts_with("GET /objects/synthetic/table.parquet HTTP/1.1\r\n"));
                assert!(text.contains("If-Match: \"fixed-v1\"\r\n"));
                assert!(text.contains("Accept-Encoding: identity\r\n"));
                let range = text
                    .lines()
                    .find_map(|l| l.strip_prefix("Range: bytes="))
                    .unwrap();
                let (start, end) = range.split_once('-').unwrap();
                let start: usize = start.parse().unwrap();
                let end: usize = end.parse().unwrap();
                let number = {
                    let mut l = log.lock().unwrap();
                    l.push((start, end));
                    l.len()
                };
                let tag = if matches!(mode, Mode::WrongVersion) && number == 3 {
                    "\"other\""
                } else {
                    "\"fixed-v1\""
                };
                let extra = if matches!(mode, Mode::LargeHeaders) {
                    format!("X-Padding: {}\r\n", "x".repeat(15000))
                } else {
                    String::new()
                };
                let header=format!("HTTP/1.1 206 Partial Content\r\nETag: {tag}\r\nContent-Range: bytes {start}-{end}/{}\r\nContent-Length: {}\r\n{extra}\r\n",bytes.len(),end-start+1);
                if socket.write_all(header.as_bytes()).is_err() {
                    continue;
                }
                if matches!(mode, Mode::HoldThird) && number == 3 {
                    let _ = tx.send(());
                    while !flag.load(Ordering::SeqCst) && Instant::now() < until {
                        thread::sleep(Duration::from_millis(5));
                    }
                    return;
                }
                let mut payload = bytes[start..=end].to_vec();
                if matches!(mode, Mode::CorruptFooter) && number == 2 {
                    payload[0] ^= 1;
                }
                let _ = socket.write_all(&payload);
            }
        });
        Self {
            port,
            stop,
            thread: Some(thread),
            ranges,
            ready,
        }
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        self.thread.take().unwrap().join().unwrap();
    }
}
fn rejected(out: Output, code: &str) {
    assert!(!out.status.success());
    assert!(out.stdout.is_empty());
    let error: Value = serde_json::from_slice(&out.stderr).unwrap();
    assert_eq!(error["code"], code);
}
fn projected_ranges(r: &Value) -> Vec<(usize, usize)> {
    let mut ranges = vec![&r["header"], &r["footer"]];
    for g in r["row_groups"].as_array().unwrap() {
        for col in r["columns"].as_array().unwrap() {
            ranges.push(
                r["chunks"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|c| c["row_group"] == *g && c["column"] == *col)
                    .unwrap(),
            );
        }
    }
    ranges
        .into_iter()
        .map(|p| {
            let start = p["offset"].as_u64().unwrap() as usize;
            (start, start + p["length"].as_u64().unwrap() as usize - 1)
        })
        .collect()
}
#[test]
fn real_http_projection_v1_v2_reads_only_selected_chunks_and_returns_typed_nulls() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    for version in [WriterVersion::PARQUET_1_0, WriterVersion::PARQUET_2_0] {
        let bytes = fixture(version, 8, false);
        let server = Server::new(bytes.clone(), Mode::Normal);
        let r = request(&bytes, server.port, vec![0, 1, 2], vec![0, 3]);
        let expected = projected_ranges(&r);
        let out = Input::new(&r).run();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        let result: Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(result["source_rows"], 8);
        assert_eq!(result["decoded_rows"], 4);
        assert_eq!(
            result["rows"],
            json!([
                [i64::MIN.to_string(), "雪/quote\"", true],
                [null, "", false],
                [i64::MAX.to_string(), null, null],
                ["0", "last", true]
            ])
        );
        assert_eq!(result["request_count"], 8);
        assert_eq!(result["verification"], "selected_ranges_only");
        assert_eq!(result["unread_content_verified"], false);
        assert_eq!(*server.ranges.lock().unwrap(), expected);
        let sum: usize = expected.iter().map(|(s, e)| e - s + 1).sum();
        assert_eq!(result["payload_bytes"], sum);
    }
}
#[test]
fn wrong_versions_footer_hash_and_cumulative_headers_stop_without_retry() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let bytes = fixture(WriterVersion::PARQUET_1_0, 8, false);
    for (mode, code, count) in [
        (Mode::WrongVersion, "invalid_http_response", 3),
        (Mode::CorruptFooter, "range_mismatch", 2),
        (Mode::LargeHeaders, "invalid_http_response", 5),
    ] {
        let server = Server::new(bytes.clone(), mode);
        let r = request(&bytes, server.port, vec![0, 1, 2], vec![0, 3]);
        rejected(Input::new(&r).run(), code);
        assert_eq!(server.ranges.lock().unwrap().len(), count);
    }
    let server = Server::new(bytes.clone(), Mode::Normal);
    let r = request(&bytes, server.port, vec![1], vec![0]);
    assert!(Input::new(&r).run().status.success());
    assert_eq!(server.ranges.lock().unwrap().len(), 3);
}
#[test]
fn unselected_codec_full_source_row_bound_and_descriptor_mismatch_reject_before_data() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    for (rows, bad_codec, mismatch) in [(8, true, false), (201, false, false), (8, false, true)] {
        let bytes = fixture(WriterVersion::PARQUET_1_0, rows, bad_codec);
        let server = Server::new(bytes.clone(), Mode::Normal);
        let mut r = request(&bytes, server.port, vec![0], vec![0]);
        if mismatch {
            let c = r["chunks"].as_array_mut().unwrap().last_mut().unwrap();
            c["length"] = json!(c["length"].as_u64().unwrap() - 1);
        }
        rejected(Input::new(&r).run(), "invalid_parquet_read");
        assert_eq!(server.ranges.lock().unwrap().len(), 2);
    }
}
#[test]
fn strict_requests_and_payload_plan_fail_without_any_network_access() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let bytes = fixture(WriterVersion::PARQUET_1_0, 8, false);
    let original = request(&bytes, 38081, vec![0, 1, 2], vec![0, 3]);
    for (field, value) in [
        ("version", json!(1.0)),
        ("columns", json!([])),
        ("columns", json!([1, 0])),
        ("row_groups", json!([0, 0])),
        ("source_sha256_provenance", json!("A".repeat(64))),
        ("object_key", json!("../escape")),
        ("timeout_ms", json!(1000)),
    ] {
        let mut r = original.clone();
        r[field] = value;
        rejected(Input::new(&r).run(), "invalid_parquet_read");
    }
    let mut r = original.clone();
    r["chunks"][1]["offset"] = r["chunks"][0]["offset"].clone();
    rejected(Input::new(&r).run(), "invalid_parquet_read");
    let mut r = original;
    r["object_bytes"] = json!(2000000);
    r["footer"]["offset"] = json!(1999000);
    r["footer"]["length"] = json!(1000);
    for (i, c) in r["chunks"].as_array_mut().unwrap().iter_mut().enumerate() {
        c["offset"] = json!(4 + i * 100000);
        c["length"] = json!(100000);
    }
    rejected(Input::new(&r).run(), "resource_limit");
}
#[test]
fn real_deadline_and_sigint_terminate_mid_operation_and_recovery_succeeds() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let bytes = fixture(WriterVersion::PARQUET_1_0, 8, false);
    for interrupt in [false, true] {
        let server = Server::new(bytes.clone(), Mode::HoldThird);
        let r = request(&bytes, server.port, vec![0], vec![0]);
        let mut input = Input::new(&r);
        input.child = Some(
            input
                .command()
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .unwrap(),
        );
        server.ready.recv_timeout(Duration::from_secs(3)).unwrap();
        let child = input.child.as_mut().unwrap();
        let pid = child.id();
        if interrupt {
            assert_eq!(unsafe { libc::kill(pid as i32, libc::SIGINT) }, 0);
        }
        let deadline = Instant::now() + Duration::from_secs(if interrupt { 3 } else { 12 });
        let status = loop {
            if let Some(s) = child.try_wait().unwrap() {
                break s;
            }
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        };
        assert_eq!(status.code(), Some(if interrupt { 130 } else { 124 }));
        let mut output = Vec::new();
        child
            .stdout
            .take()
            .unwrap()
            .read_to_end(&mut output)
            .unwrap();
        assert!(output.is_empty());
        let mut error = String::new();
        child
            .stderr
            .take()
            .unwrap()
            .read_to_string(&mut error)
            .unwrap();
        let error: Value = serde_json::from_str(&error).unwrap();
        assert_eq!(
            error["code"],
            if interrupt { "cancelled" } else { "timeout" }
        );
        assert!(!std::path::Path::new(&format!("/proc/{pid}")).exists());
        assert_eq!(server.ranges.lock().unwrap().len(), 3);
    }
    let server = Server::new(bytes.clone(), Mode::Normal);
    let r = request(&bytes, server.port, vec![0], vec![0]);
    assert!(Input::new(&r).run().status.success());
}

#[test]
fn a_large_unselected_column_is_never_transferred_and_selecting_it_fails_before_get() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let schema = Arc::new(Schema::new(vec![
        Field::new("number", DataType::Int64, true),
        Field::new("text", DataType::Utf8, true),
    ]));
    let text = "x".repeat(600000);
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(Int64Array::from(vec![7, 8])),
            Arc::new(StringArray::from(vec![text.as_str(), text.as_str()])),
        ],
    )
    .unwrap();
    let properties = WriterProperties::builder()
        .set_dictionary_enabled(false)
        .set_encoding(Encoding::PLAIN)
        .set_compression(Compression::UNCOMPRESSED)
        .set_statistics_enabled(parquet::file::properties::EnabledStatistics::None)
        .build();
    let mut bytes = Vec::new();
    let mut writer = ArrowWriter::try_new(&mut bytes, schema, Some(properties)).unwrap();
    writer.write(&batch).unwrap();
    writer.close().unwrap();
    let server = Server::new(bytes.clone(), Mode::Normal);
    let mut r = request(&bytes, server.port, vec![0], vec![0]);
    let large = r["chunks"][1]["length"].as_u64().unwrap();
    assert!(large > 512 << 10);
    let out = Input::new(&r).run();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let result: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(result["rows"], json!([["7"], ["8"]]));
    assert_eq!(result["request_count"], 3);
    assert_eq!(*server.ranges.lock().unwrap(), projected_ranges(&r));
    r["columns"] = json!([1]);
    rejected(Input::new(&r).run(), "resource_limit");
    assert_eq!(
        server.ranges.lock().unwrap().len(),
        3,
        "over-budget selection must make no new GET"
    );
}

#[path = "projected_sql_cases.rs"]
mod query_cases;
