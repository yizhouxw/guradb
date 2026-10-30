//! Finite stdio protocol transport; data execution remains the same Rust CLI.
mod tools;
mod worker;
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    io::Read,
    path::Path,
    sync::atomic::{AtomicI32, Ordering},
    time::{Duration, Instant},
};
use worker::Worker;
const REQUEST: usize = 65536;
const RESPONSE: usize = 2 << 20;
static SIGNAL: AtomicI32 = AtomicI32::new(0);
extern "C" fn interrupt(sig: i32) {
    SIGNAL.store(sig, Ordering::Relaxed);
}
fn valid_id(id: &Value) -> bool {
    id.as_i64().is_some() || id.as_u64().is_some() || id.as_str().is_some_and(|s| s.len() <= 128)
}
fn initialize_params(params: &Value) -> bool {
    let Some(p) = params.as_object() else {
        return false;
    };
    if p.len() != 3
        || p.keys().any(|k| {
            !matches!(
                k.as_str(),
                "protocolVersion" | "capabilities" | "clientInfo"
            )
        })
    {
        return false;
    }
    let Some(version) = p["protocolVersion"].as_str() else {
        return false;
    };
    if version.len() != 10
        || !version.bytes().enumerate().all(|(i, b)| {
            if i == 4 || i == 7 {
                b == b'-'
            } else {
                b.is_ascii_digit()
            }
        })
    {
        return false;
    }
    let Some(info) = p["clientInfo"].as_object() else {
        return false;
    };
    if info
        .keys()
        .any(|k| !matches!(k.as_str(), "name" | "version" | "title"))
        || !["name", "version"].iter().all(|k| {
            info.get(*k)
                .and_then(Value::as_str)
                .is_some_and(|s| !s.is_empty() && s.len() <= 128)
        })
        || info.get("title").is_some_and(|v| !v.is_string())
    {
        return false;
    }
    p["capabilities"].as_object().is_some_and(|c| {
        c.iter().all(|(k, v)| {
            matches!(
                k.as_str(),
                "roots" | "sampling" | "elicitation" | "experimental"
            ) && v.is_object()
        })
    })
}
struct Pending {
    bytes: Vec<u8>,
    offset: usize,
    since: Instant,
}
struct Server {
    store: String,
    phase: u8,
    ids: HashSet<String>,
    messages: usize,
    total: usize,
    pending: Option<Pending>,
    worker: Option<Worker>,
}
impl Server {
    fn send(&mut self, value: Value) -> Result<(), &'static str> {
        let mut bytes = serde_json::to_vec(&value).map_err(|_| "cannot encode response")?;
        bytes.push(b'\n');
        if self.pending.is_some() || bytes.len() > RESPONSE || self.total + bytes.len() > 8 << 20 {
            return Err("response/queue/session output bound");
        }
        self.total += bytes.len();
        self.pending = Some(Pending {
            bytes,
            offset: 0,
            since: Instant::now(),
        });
        Ok(())
    }
    fn error(&mut self, id: Value, code: i32, message: &str) -> Result<(), &'static str> {
        self.send(json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}}))
    }
    fn result(&mut self, id: Value, result: Value) -> Result<(), &'static str> {
        self.send(json!({"jsonrpc":"2.0","id":id,"result":result}))
    }
    fn message(&mut self, bytes: &[u8]) -> Result<(), &'static str> {
        self.messages += 1;
        if self.messages > 32 {
            return Err("session message limit");
        }
        let value: Value = match serde_json::from_slice(bytes) {
            Ok(value) => value,
            Err(_) => return self.error(Value::Null, -32700, "invalid JSON"),
        };
        let Some(o) = value.as_object() else {
            return self.error(Value::Null, -32600, "one JSON-RPC object required");
        };
        let id = o.get("id").cloned();
        if o.get("jsonrpc") != Some(&json!("2.0"))
            || o.keys()
                .any(|k| !matches!(k.as_str(), "jsonrpc" | "id" | "method" | "params"))
        {
            return self.error(
                id.filter(valid_id).unwrap_or(Value::Null),
                -32600,
                "invalid JSON-RPC fields",
            );
        }
        let Some(method) = o
            .get("method")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
        else {
            return self.error(
                id.filter(valid_id).unwrap_or(Value::Null),
                -32600,
                "method string required",
            );
        };
        let params = o.get("params").cloned().unwrap_or(json!({}));
        if id.is_none() {
            return match method {
                "notifications/initialized"
                    if self.phase == 1 && params.as_object().is_some_and(|p| p.is_empty()) =>
                {
                    self.phase = 2;
                    Ok(())
                }
                "notifications/cancelled" if self.phase == 2 => {
                    let p = params.as_object().ok_or("invalid cancellation")?;
                    if p.keys()
                        .any(|k| !matches!(k.as_str(), "requestId" | "reason"))
                        || !p.get("requestId").is_some_and(valid_id)
                        || p.get("reason").is_some_and(|v| !v.is_string())
                    {
                        return Err("invalid cancellation fields");
                    }
                    if self.worker.as_ref().is_some_and(|w| w.id == p["requestId"]) {
                        if let Some(mut w) = self.worker.take() {
                            if !w.cancel() {
                                return Err("worker cleanup incomplete");
                            }
                        }
                    }
                    Ok(())
                }
                _ => Err("unsupported notification or lifecycle"),
            };
        }
        let id = id.unwrap();
        if !(id.as_i64().is_some()
            || id.as_u64().is_some()
            || id.as_str().is_some_and(|s| s.len() <= 128))
            || !self.ids.insert(id.to_string())
        {
            return self.error(Value::Null, -32600, "invalid or duplicate request ID");
        }
        if method == "initialize" {
            if self.phase != 0 {
                return self.error(id, -32600, "already initialized");
            }
            if !initialize_params(&params) {
                return self.error(id, -32602, "invalid initialize parameters");
            }
            self.phase = 1;
            return self.result(id,json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"guradb-local-preview","version":env!("CARGO_PKG_VERSION")}}));
        }
        if method == "ping" && self.phase > 0 {
            if !params.as_object().is_some_and(|p| p.is_empty()) {
                return self.error(id, -32602, "ping parameters unsupported");
            }
            return self.result(id, json!({}));
        }
        if self.phase != 2 {
            return self.error(
                id,
                -32600,
                "initialize and initialized notification required",
            );
        }
        match method {
            "tools/list" => {
                if !params.as_object().is_some_and(|p| p.is_empty()) {
                    return self.error(id, -32602, "pagination/extra list parameters unsupported");
                }
                self.result(id, tools::list())
            }
            "tools/call" => {
                if self.worker.is_some() {
                    return self.error(id, -32001, "single request already in flight");
                }
                match tools::command(&params,&self.store) {
                    Ok(args) => match Worker::start(id.clone(),args) {
                        Ok(w) => {self.worker=Some(w);Ok(())},
                        Err(_) => self.result(id,json!({"isError":true,"content":[{"type":"text","text":"{\"code\":\"execution_failed\",\"message\":\"cannot start Rust worker\"}"}]})),
                    },
                    Err(e) => self.error(id,-32602,e),
                }
            }
            _ => self.error(id, -32601, "unsupported method"),
        }
    }
    fn tick(&mut self) -> Result<(), &'static str> {
        if let Some(w) = self.worker.as_mut() {
            if let Some((error, text)) = w.poll() {
                let id = w.id.clone();
                self.worker.take();
                self.result(
                    id,
                    json!({"isError":error,"content":[{"type":"text","text":text}]}),
                )?;
            }
        }
        if let Some(out) = self.pending.as_mut() {
            if out.since.elapsed() >= Duration::from_secs(5) {
                return Err("stdout write timeout");
            }
            let bytes = &out.bytes[out.offset..];
            // Raw nonblocking fd writes have no hidden LineWriter buffer.
            let count = unsafe { libc::write(1, bytes.as_ptr().cast(), bytes.len()) };
            let wrote = if count < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                Ok(count as usize)
            };
            match wrote {
                Ok(0) => return Err("stdout closed"),
                Ok(n) => {
                    out.offset += n;
                    if out.offset == out.bytes.len() {
                        self.pending = None;
                    }
                }
                Err(e)
                    if e.kind() == std::io::ErrorKind::WouldBlock
                        || e.kind() == std::io::ErrorKind::Interrupted => {}
                Err(_) => return Err("stdout failed"),
            }
        }
        Ok(())
    }
}
pub fn entry(args: &[String]) -> i32 {
    if args.len() != 4 || args[2] != "--store" {
        eprintln!("MCP requires --store <existing local store>");
        return 1;
    }
    let store = Path::new(&args[3]);
    if !store.is_absolute()
        || !std::fs::symlink_metadata(store)
            .is_ok_and(|m| m.is_dir() && !m.file_type().is_symlink())
    {
        eprintln!("MCP requires an absolute nonlinked local store directory");
        return 1;
    }
    // This process owns its stdio pipes; nonblocking writes permit cancellation
    // while the client stops reading. Child worker pipes are separate.
    unsafe {
        for fd in [0, 1] {
            let flags = libc::fcntl(fd, libc::F_GETFL);
            if flags < 0 || libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) < 0 {
                return 1;
            }
        }
        libc::signal(libc::SIGINT, interrupt as *const () as usize);
        libc::signal(libc::SIGTERM, interrupt as *const () as usize);
    }
    let mut server = Server {
        store: store.to_string_lossy().into_owned(),
        phase: 0,
        ids: HashSet::new(),
        messages: 0,
        total: 0,
        pending: None,
        worker: None,
    };
    let began = Instant::now();
    let mut activity = Instant::now();
    let mut partial = None;
    let mut input = Vec::new();
    let mut code = 0;
    loop {
        let sig = SIGNAL.load(Ordering::Relaxed);
        if sig != 0 {
            code = 128 + sig;
            break;
        }
        if began.elapsed() >= Duration::from_secs(60)
            || partial.is_some_and(|p: Instant| p.elapsed() >= Duration::from_secs(10))
            || (server.worker.is_none()
                && server.pending.is_none()
                && activity.elapsed() >= Duration::from_secs(10))
        {
            code = 124;
            break;
        }
        let mut chunk = [0u8; 8192];
        match std::io::stdin().read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => {
                activity = Instant::now();
                if input.is_empty() {
                    partial = Some(activity);
                }
                input.extend_from_slice(&chunk[..n]);
                if input.len() > REQUEST {
                    code = 1;
                    break;
                }
                while let Some(pos) = input.iter().position(|b| *b == b'\n') {
                    let line: Vec<_> = input.drain(..=pos).collect();
                    if server.message(&line[..line.len() - 1]).is_err() {
                        code = 1;
                        break;
                    }
                    partial = if input.is_empty() {
                        None
                    } else {
                        Some(Instant::now())
                    };
                }
                if code != 0 {
                    break;
                }
            }
            Err(e)
                if e.kind() == std::io::ErrorKind::WouldBlock
                    || e.kind() == std::io::ErrorKind::Interrupted => {}
            Err(_) => {
                code = 1;
                break;
            }
        }
        if server.tick().is_err() {
            code = 1;
            break;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    if let Some(mut w) = server.worker.take() {
        if !w.cancel() {
            code = 1;
        }
    }
    code
}

#[cfg(test)]
mod tests;
