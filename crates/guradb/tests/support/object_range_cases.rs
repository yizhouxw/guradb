//! Private real TCP/CLI tests, independent of the public reference fixture.
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
struct Input {
    root: PathBuf,
    child: Option<Child>,
}
impl Input {
    fn new(value: Value) -> Self {
        let root = std::env::temp_dir().join(format!(
            "guradb-range-{}-{}",
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
            "object-range",
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
struct Server {
    port: u16,
    stop: Arc<AtomicBool>,
    thread: Option<thread::JoinHandle<()>>,
    requests: Arc<Mutex<Vec<Vec<u8>>>>,
    ready: mpsc::Receiver<()>,
}
impl Server {
    fn new(packet: Vec<u8>, hold: bool) -> Self {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        listener.set_nonblocking(true).unwrap();
        let port = listener.local_addr().unwrap().port();
        let stop = Arc::new(AtomicBool::new(false));
        let requests = Arc::new(Mutex::new(Vec::new()));
        let flag = stop.clone();
        let log = requests.clone();
        let (tx, ready) = mpsc::channel();
        let thread = thread::spawn(move || {
            let until = Instant::now() + Duration::from_secs(5);
            while !flag.load(Ordering::SeqCst) && Instant::now() < until {
                match listener.accept() {
                    Ok((mut s, _)) => {
                        s.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
                        s.set_write_timeout(Some(Duration::from_secs(1))).unwrap();
                        let mut request = Vec::new();
                        let mut b = [0];
                        while request.len() < 16384 && !request.ends_with(b"\r\n\r\n") {
                            if s.read_exact(&mut b).is_err() {
                                return;
                            }
                            request.push(b[0]);
                        }
                        log.lock().unwrap().push(request);
                        let _ = s.write_all(&packet);
                        let _ = tx.send(());
                        while hold && !flag.load(Ordering::SeqCst) {
                            thread::sleep(Duration::from_millis(10));
                        }
                        return;
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(5))
                    }
                    Err(_) => return,
                }
            }
        });
        Self {
            port,
            stop,
            thread: Some(thread),
            requests,
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
fn request(port: u16) -> Value {
    json!({"version":1,"origin":format!("http://127.0.0.1:{port}"),"object_key":"a/file.bin","etag":"\"v1\"","object_bytes":8,"offset":2,"length":3,"range_sha256":hex::encode(Sha256::digest(b"abc"))})
}
fn header(extra: &str) -> String {
    format!("HTTP/1.1 206 Partial Content\r\nETag: \"v1\"\r\nContent-Range: bytes 2-4/8\r\nContent-Length: 3\r\n{extra}\r\n")
}
fn packet(head: &str, body: &[u8]) -> Vec<u8> {
    let mut v = head.as_bytes().to_vec();
    v.extend(body);
    v
}
fn rejected(out: Output, code: Option<&str>) {
    assert!(!out.status.success());
    assert!(out.stdout.is_empty());
    let v: Value = serde_json::from_slice(&out.stderr).unwrap();
    if let Some(c) = code {
        assert_eq!(v["code"], c);
    }
}

#[test]
fn one_get_exact_range_accepts_unconsumed_tail_and_then_recovers() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    for tail in [b"".as_slice(), b"UNCONSUMED TAIL".as_slice()] {
        let mut bytes = b"abc".to_vec();
        bytes.extend(tail);
        let server = Server::new(
            packet(
                &header("cOnTeNt-EnCoDiNg: IDENTITY\r\nContent-Type: application/octet-stream\r\n"),
                &bytes,
            ),
            false,
        );
        let input = Input::new(request(server.port));
        let out = input.run();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        let v: Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(v["bytes_hex"], "616263");
        assert_eq!(v["verification"], "range_only");
        assert_eq!(v["request_count"], 1);
        let log = server.requests.lock().unwrap();
        assert_eq!(log.len(), 1);
        let sent = std::str::from_utf8(&log[0]).unwrap();
        assert!(sent.starts_with("GET /objects/a/file.bin HTTP/1.1\r\n"));
        for required in [
            "Range: bytes=2-4\r\n",
            "If-Match: \"v1\"\r\n",
            "Accept-Encoding: identity\r\n",
            "Connection: close\r\n",
        ] {
            assert!(sent.contains(required));
        }
    }
}
#[test]
fn malformed_or_wrong_responses_never_publish_bytes() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let normal = header("");
    let bad = [
        normal.replace("206 Partial Content", "200 OK"),
        normal.replace("\"v1\"", "W/\"v1\""),
        normal.replace("2-4/8", "2-4/9"),
        normal.replace("Length: 3", "Length: 4"),
        header("eTaG: \"v1\"\r\n"),
        header("cOnTeNt-LeNgTh: 3\r\n"),
        header("Content-Encoding: identity\r\ncOnTeNt-EnCoDiNg: identity\r\n"),
        header(
            "Content-Type: application/octet-stream\r\ncOnTeNt-TyPe: application/octet-stream\r\n",
        ),
        header("Transfer-Encoding: chunked\r\n"),
        header("Trailer: digest\r\n"),
        header("Content-Encoding: gzip\r\n"),
        header("Content-Type: MuLtIpArT/byteranges\r\n"),
        header("Upgrade: websocket\r\n"),
        header("Connection: Upgrade\r\n"),
        header("Connection: keep-alive\r\n"),
        header("Connection: close\r\ncOnNeCtIoN: close\r\n"),
        header("Content-Type: application/octet-stream, multipart/byteranges\r\n"),
        header("Content-Type: application/octet-stream; boundary=x\r\n"),
        header("X-Value: a\tb\r\n"),
        header("X-Value: \u{0080}\r\n"),
        header(" folded: header\r\n"),
        normal.replacen("\r\n", "\n", 1),
        header(&format!("X-Large: {}\r\n", "x".repeat(16384))),
    ];
    for head in bad {
        let server = Server::new(packet(&head, b"abc"), false);
        let input = Input::new(request(server.port));
        rejected(input.run(), Some("invalid_http_response"));
    }
    for body in [b"ab".as_slice(), b"abd".as_slice()] {
        let server = Server::new(packet(&normal, body), false);
        let input = Input::new(request(server.port));
        rejected(input.run(), None);
    }
    let server = Server::new(packet(&normal, b"abc"), false);
    assert!(Input::new(request(server.port)).run().status.success());
}
#[test]
fn strict_input_rejects_types_uris_keys_versions_and_links_before_connect() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    for (field, value) in [
        ("version", json!(2)),
        ("version", json!(true)),
        ("origin", json!("http://localhost:38081")),
        ("origin", json!("http://127.0.0.1:38081/")),
        ("origin", json!("http://127.0.0.1:80")),
        ("origin", json!("http://user@127.0.0.1:38081")),
        ("object_key", json!("../secret")),
        ("object_key", json!("a/%2e%2e")),
        ("object_key", json!("a//b")),
        ("etag", json!("W/\"v1\"")),
        ("etag", json!("\"a\",\"b\"")),
        ("object_bytes", json!(false)),
        ("offset", json!(u64::MAX)),
        ("length", json!(0)),
        ("length", json!(1.5)),
        ("length", json!(524289)),
        ("range_sha256", json!("A".repeat(64))),
        ("timeout_ms", json!(1)),
    ] {
        let mut r = request(38081);
        r[field] = value;
        rejected(Input::new(r).run(), Some("invalid_object_range"));
    }
    let input = Input::new(request(38081));
    fs::write(
        input.root.join("request.json"),
        "{\"version\":1,\"version\":1}",
    )
    .unwrap();
    rejected(input.run(), Some("invalid_object_range"));
    let target = input.root.join("request.json");
    fs::remove_file(&target).unwrap();
    let elsewhere = input.root.join("elsewhere");
    fs::write(&elsewhere, request(38081).to_string()).unwrap();
    std::os::unix::fs::symlink(elsewhere, &target).unwrap();
    rejected(input.run(), Some("invalid_object_range"));
}
#[test]
fn real_body_deadline_and_sigint_close_owned_connection() {
    let _window = super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    for interrupt in [false, true] {
        let server = Server::new(header("").into_bytes(), true);
        let mut input = Input::new(request(server.port));
        let started = Instant::now();
        input.child = Some(
            input
                .command()
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .unwrap(),
        );
        server.ready.recv_timeout(Duration::from_secs(5)).unwrap();
        if interrupt {
            assert!(Command::new("kill")
                .args(["-INT", &input.child.as_ref().unwrap().id().to_string()])
                .status()
                .unwrap()
                .success());
        }
        let end = Instant::now() + Duration::from_secs(12);
        let status = loop {
            if let Some(s) = input.child.as_mut().unwrap().try_wait().unwrap() {
                break s;
            }
            assert!(Instant::now() < end, "range child did not terminate");
            thread::sleep(Duration::from_millis(10));
        };
        assert_eq!(status.code(), Some(if interrupt { 130 } else { 124 }));
        if !interrupt {
            assert!(started.elapsed() >= Duration::from_secs(9));
        }
        let child = input.child.take().unwrap();
        let pid = child.id();
        let out = child.wait_with_output().unwrap();
        assert!(out.stdout.is_empty());
        assert!(!PathBuf::from(format!("/proc/{pid}")).exists());
        let error: Value = serde_json::from_slice(&out.stderr).unwrap();
        assert_eq!(
            error["code"],
            if interrupt { "cancelled" } else { "timeout" }
        );
    }
    let server = Server::new(packet(&header(""), b"abc"), false);
    assert!(Input::new(request(server.port)).run().status.success());
}
