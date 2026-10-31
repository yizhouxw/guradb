use super::request::Request;
use crate::{Error, Result};
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    net::{Ipv4Addr, SocketAddr, TcpStream},
    time::Instant,
};

fn invalid() -> Error {
    Error::new(
        "invalid_http_response",
        "invalid or unsupported fixed range response",
    )
}
fn io_error() -> Error {
    Error::new("object_range_io", "range connection or transfer failed")
}
fn remaining(deadline: Instant) -> Result<std::time::Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|d| !d.is_zero())
        .ok_or_else(io_error)
}
pub(super) fn get(r: &Request, port: u16, deadline: Instant) -> Result<(Vec<u8>, usize)> {
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let mut socket =
        TcpStream::connect_timeout(&address, remaining(deadline)?).map_err(|_| io_error())?;
    let request = format!("GET /objects/{} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nRange: bytes={}-{}\r\nIf-Match: {}\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n",r.object_key,port,r.offset,r.end(),r.etag);
    let mut sent = 0;
    while sent < request.len() {
        socket
            .set_write_timeout(Some(remaining(deadline)?))
            .map_err(|_| io_error())?;
        let n = socket
            .write(&request.as_bytes()[sent..])
            .map_err(|_| io_error())?;
        if n == 0 {
            return Err(io_error());
        }
        sent += n;
    }
    // Read no body ahead: every header byte is bounded and parsed only once.
    let mut head = Vec::new();
    while !head.ends_with(b"\r\n\r\n") {
        if head.len() == 16384 {
            return Err(invalid());
        }
        socket
            .set_read_timeout(Some(remaining(deadline)?))
            .map_err(|_| io_error())?;
        let mut byte = [0];
        socket.read_exact(&mut byte).map_err(|_| io_error())?;
        head.push(byte[0]);
    }
    validate(&head, r)?;
    let mut body = vec![0; r.length];
    let mut received = 0;
    while received < body.len() {
        socket
            .set_read_timeout(Some(remaining(deadline)?))
            .map_err(|_| io_error())?;
        let n = socket.read(&mut body[received..]).map_err(|_| io_error())?;
        if n == 0 {
            return Err(io_error());
        }
        received += n;
    }
    // Content-Length ends this message. Never reuse the connection, wait for
    // EOF, probe a tail byte, or certify bytes outside the requested range.
    drop(socket);
    Ok((body, head.len()))
}
fn validate(head: &[u8], r: &Request) -> Result<()> {
    if !head.starts_with(b"HTTP/1.1 ") {
        return Err(invalid());
    }
    for (i, b) in head.iter().enumerate() {
        if (*b == b'\r' && head.get(i + 1) != Some(&b'\n'))
            || (*b == b'\n' && (i == 0 || head.get(i - 1) != Some(&b'\r')))
        {
            return Err(invalid());
        }
    }
    if head.windows(2).any(|b| b == b"\n " || b == b"\n\t") {
        return Err(invalid());
    }
    let mut storage = [httparse::EMPTY_HEADER; 64];
    let mut response = httparse::Response::new(&mut storage);
    let used = response.parse(head).map_err(|_| invalid())?;
    if used != httparse::Status::Complete(head.len())
        || response.version != Some(1)
        || response.code != Some(206)
    {
        return Err(invalid());
    }
    let mut fields = BTreeMap::new();
    for h in response.headers.iter() {
        let name = h.name.to_ascii_lowercase();
        let value = std::str::from_utf8(h.value)
            .map_err(|_| invalid())?
            .trim_matches([' ', '\t']);
        if !value.bytes().all(|b| (0x20..=0x7e).contains(&b)) {
            return Err(invalid());
        }
        match name.as_str() {
            "transfer-encoding" | "trailer" | "location" | "upgrade" => return Err(invalid()),
            "etag" | "content-range" | "content-length" | "content-encoding" | "content-type"
            | "connection" => {
                if fields.insert(name, value).is_some() {
                    return Err(invalid());
                }
            }
            _ => (),
        }
    }
    let expected = format!("bytes {}-{}/{}", r.offset, r.end(), r.object_bytes);
    if fields.get("etag").copied() != Some(r.etag.as_str())
        || fields.get("content-range").copied() != Some(expected.as_str())
        || fields.get("content-length").copied() != Some(r.length.to_string().as_str())
        || fields
            .get("content-encoding")
            .is_some_and(|s| !s.eq_ignore_ascii_case("identity"))
        || fields
            .get("content-type")
            .is_some_and(|s| !s.eq_ignore_ascii_case("application/octet-stream"))
        || fields
            .get("connection")
            .is_some_and(|s| !s.eq_ignore_ascii_case("close"))
    {
        return Err(invalid());
    }
    Ok(())
}
