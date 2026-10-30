//! One owned readonly CLI process. No database logic or result rewriting.
use serde_json::{json, Value};
use std::io::{self, Read};
use std::os::fd::AsRawFd;
use std::process::{Child, ExitStatus, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    mpsc::{self, Receiver, SyncSender, TryRecvError},
    Arc,
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

const STDOUT_LIMIT: usize = 2 * 1024 * 1024;
const STDERR_LIMIT: usize = 4 * 1024;
const WORK_LIMIT: Duration = Duration::from_secs(10);
const CLEANUP_LIMIT: Duration = Duration::from_secs(2);

type Captured = Result<Vec<u8>, &'static str>;
struct Capture {
    stdout: bool,
    result: Captured,
}

pub struct Worker {
    pub id: Value,
    child: Option<Child>,
    readers: Vec<JoinHandle<()>>,
    receive: Receiver<Capture>,
    stop: Arc<AtomicBool>,
    started: Instant,
    terminal_since: Option<Instant>,
    status: Option<ExitStatus>,
    stdout: Option<Captured>,
    stderr: Option<Captured>,
    failure: Option<&'static str>,
    finished: bool,
}

fn nonblocking<T: AsRawFd>(pipe: &T) -> io::Result<()> {
    // Owned pipe descriptors only; readers must be interruptible even if an
    // unexpected descendant inherited a writer. Never change parent stdio.
    let fd = pipe.as_raw_fd();
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    if flags == -1 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } == -1 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn capture<R: Read + Send + 'static>(
    mut pipe: R,
    stdout: bool,
    limit: usize,
    send: SyncSender<Capture>,
    stop: Arc<AtomicBool>,
) -> io::Result<JoinHandle<()>> {
    thread::Builder::new()
        .name(if stdout { "mcp-stdout" } else { "mcp-stderr" }.into())
        .spawn(move || {
            let mut bytes = Vec::with_capacity(limit + 1);
            let mut block = [0_u8; 8192];
            let result = loop {
                if stop.load(Ordering::Acquire) {
                    break Err("cancelled");
                }
                let count = block.len().min(limit + 1 - bytes.len());
                match pipe.read(&mut block[..count]) {
                    Ok(0) => break Ok(bytes),
                    Ok(size) => {
                        bytes.extend_from_slice(&block[..size]);
                        if bytes.len() > limit {
                            break Err("output_limit");
                        }
                    }
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(2))
                    }
                    Err(_) => break Err("worker_io"),
                }
            };
            // Exactly one terminal message per reader and two channel slots: a
            // worker that is dropped cannot leave a reader blocked on send.
            let _ = send.send(Capture { stdout, result });
        })
}

fn error(code: &str) -> (bool, String) {
    (
        true,
        json!({"code":code, "message":"MCP CLI worker failed within its resource bounds"})
            .to_string(),
    )
}

/// Cleanup could not be confirmed inside its original two-second window.
/// End this entire dedicated MCP supervisor session, rather than returning
/// to service with unknown worker state. Its launcher must remove the owned
/// container. This is not a claim to interrupt uninterruptible kernel I/O.
fn fail_session() -> ! {
    let message = b"MCP session terminated: worker cleanup deadline exceeded\n";
    // Best-effort, bounded stderr: a blocked logging consumer must not prevent
    // the fail-closed process exit. No user arguments or captured data appear.
    let flags = unsafe { libc::fcntl(libc::STDERR_FILENO, libc::F_GETFL) };
    if flags != -1
        && unsafe { libc::fcntl(libc::STDERR_FILENO, libc::F_SETFL, flags | libc::O_NONBLOCK) }
            != -1
    {
        unsafe {
            libc::write(libc::STDERR_FILENO, message.as_ptr().cast(), message.len());
        }
    }
    std::process::exit(1)
}

impl Worker {
    pub fn start(id: Value, args: Vec<String>) -> io::Result<Self> {
        let child = std::process::Command::new(std::env::current_exe()?)
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let (send, receive) = mpsc::sync_channel(2);
        // Install ownership before any fallible pipe/thread setup. Drop cleans
        // a started child if fcntl or either reader spawn fails.
        let mut worker = Self {
            id,
            child: Some(child),
            readers: Vec::new(),
            receive,
            stop: Arc::new(AtomicBool::new(false)),
            started: Instant::now(),
            terminal_since: None,
            status: None,
            stdout: None,
            stderr: None,
            failure: None,
            finished: false,
        };
        let stdout = worker
            .child
            .as_mut()
            .expect("owned child")
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("worker stdout pipe missing"))?;
        let stderr = worker
            .child
            .as_mut()
            .expect("owned child")
            .stderr
            .take()
            .ok_or_else(|| io::Error::other("worker stderr pipe missing"))?;
        nonblocking(&stdout)?;
        nonblocking(&stderr)?;
        worker.readers.push(capture(
            stdout,
            true,
            STDOUT_LIMIT,
            send.clone(),
            worker.stop.clone(),
        )?);
        worker.readers.push(capture(
            stderr,
            false,
            STDERR_LIMIT,
            send,
            worker.stop.clone(),
        )?);
        Ok(worker)
    }

    fn terminate(&mut self, reason: &'static str) {
        if self.failure.is_none() {
            self.failure = Some(reason);
        }
        self.terminal_since.get_or_insert_with(Instant::now);
        self.stop.store(true, Ordering::Release);
        if let Some(child) = self.child.as_mut().filter(|_| self.status.is_none()) {
            let _ = child.kill();
        }
    }

    /// Called by the MCP loop every ~10ms. Never wait for a running child or
    /// reader here, so input cancellation continues to be serviced.
    pub fn poll(&mut self) -> Option<(bool, String)> {
        if self.finished {
            return None;
        }
        if self.status.is_none() {
            match self.child.as_mut()?.try_wait() {
                Ok(Some(status)) => {
                    self.status = Some(status);
                    self.terminal_since.get_or_insert_with(Instant::now);
                }
                Ok(None) => {}
                Err(_) => self.terminate("worker_io"),
            }
        }
        loop {
            match self.receive.try_recv() {
                Ok(captured) => {
                    if let Err(reason) = &captured.result {
                        self.terminate(reason);
                    }
                    if captured.stdout {
                        self.stdout = Some(captured.result);
                    } else {
                        self.stderr = Some(captured.result);
                    }
                }
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    if self.stdout.is_none() || self.stderr.is_none() {
                        self.terminate("worker_io");
                    }
                    break;
                }
            }
        }
        if self.status.is_none() && self.started.elapsed() >= WORK_LIMIT {
            self.terminate("timeout");
        }
        if self
            .terminal_since
            .is_some_and(|since| since.elapsed() >= CLEANUP_LIMIT)
            && (self.status.is_none()
                || self.stdout.is_none()
                || self.stderr.is_none()
                || !self.readers.iter().all(JoinHandle::is_finished))
        {
            self.terminate("worker_io");
            // cancel reuses this expired window; it performs a final
            // nonblocking reap/join attempt without granting another 2s.
            if !self.cancel() {
                fail_session();
            }
            return Some(error(self.failure.unwrap_or("worker_io")));
        }
        if self.status.is_none() || !self.readers.iter().all(JoinHandle::is_finished) {
            return None;
        }
        for reader in self.readers.drain(..) {
            let _ = reader.join();
        }
        // try_wait has reaped this exact child; Child is never replaced by a
        // numeric PID lookup and cannot signal an unrelated/reused process.
        self.child.take();
        self.finished = true;
        if let Some(reason) = self.failure {
            return Some(error(reason));
        }
        let raw = if self.status.as_ref()?.success() {
            self.stdout.take()
        } else {
            self.stderr.take()
        };
        let is_error = !self.status.as_ref()?.success();
        match raw {
            Some(Ok(bytes)) => match String::from_utf8(bytes) {
                Ok(text) if serde_json::from_str::<Value>(&text).is_ok() => Some((is_error, text)),
                _ => Some(error("worker_output")),
            },
            _ => Some(error("worker_output")),
        }
    }

    /// Bounded cleanup of only our Child/readers. False retains ownership and
    /// must terminate the session; retrying never refreshes the first window.
    pub fn cancel(&mut self) -> bool {
        if self.finished {
            return true;
        }
        let since = *self.terminal_since.get_or_insert_with(Instant::now);
        self.stop.store(true, Ordering::Release);
        if let Some(child) = self.child.as_mut().filter(|_| self.status.is_none()) {
            // Even an already exited child remains owned (or cached as reaped)
            // by Child. Do not use libc kill with a stored numeric PID.
            let _ = child.kill();
        }
        loop {
            if self.status.is_none() {
                if let Some(child) = self.child.as_mut() {
                    if let Ok(Some(status)) = child.try_wait() {
                        self.status = Some(status);
                    }
                }
            }
            if self.status.is_some() {
                self.child.take();
            }
            let mut index = 0;
            while index < self.readers.len() {
                if self.readers[index].is_finished() {
                    let reader = self.readers.swap_remove(index);
                    let _ = reader.join();
                } else {
                    index += 1;
                }
            }
            if self.child.is_none() && self.readers.is_empty() {
                self.finished = true;
                return true;
            }
            let remaining = CLEANUP_LIMIT.saturating_sub(since.elapsed());
            if remaining.is_zero() {
                // Keep the Child and unfinished JoinHandles in this Worker.
                // Drop will make one final check on the same expired window.
                return false;
            }
            thread::sleep(remaining.min(Duration::from_millis(2)));
        }
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        if !self.cancel() {
            fail_session();
        }
    }
}
