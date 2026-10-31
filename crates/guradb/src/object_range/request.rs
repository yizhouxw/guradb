use crate::{Error, Result};
use serde::Deserialize;
use std::{fs::OpenOptions, io::Read, os::unix::fs::OpenOptionsExt, path::Path};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub version: u32,
    pub origin: String,
    pub object_key: String,
    pub etag: String,
    pub object_bytes: u64,
    pub offset: u64,
    pub length: usize,
    pub range_sha256: String,
}
pub(super) fn invalid() -> Error {
    Error::new(
        "invalid_object_range",
        "invalid or unsupported fixed range request",
    )
}
impl Request {
    pub(super) fn read(path: &Path) -> Result<(Self, u16)> {
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
            .open(path)
            .map_err(|_| invalid())?;
        let info = file.metadata().map_err(|_| invalid())?;
        if !info.is_file() || info.len() > 16384 {
            return Err(invalid());
        }
        let mut raw = Vec::new();
        file.take(16385)
            .read_to_end(&mut raw)
            .map_err(|_| invalid())?;
        if raw.len() > 16384 {
            return Err(invalid());
        }
        let r: Self = serde_json::from_slice(&raw).map_err(|_| invalid())?;
        let port = r.validate()?;
        Ok((r, port))
    }
    fn validate(&self) -> Result<u16> {
        let uri = self.origin.parse::<http::Uri>().map_err(|_| invalid())?;
        let port = uri.port_u16().ok_or_else(invalid)?;
        let key = &self.object_key;
        let tag = self.etag.as_bytes();
        if self.version != 1
            || port < 1024
            || self.origin != format!("http://127.0.0.1:{port}")
            || key.is_empty()
            || key.len() > 4096
            || key.split('/').count() > 16
            || key.split('/').any(|s| {
                s.is_empty()
                    || s.len() > 255
                    || matches!(s, "." | "..")
                    || !s
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
            })
            || !(3..=128).contains(&tag.len())
            || tag.first() != Some(&b'"')
            || tag.last() != Some(&b'"')
            || !tag[1..tag.len() - 1]
                .iter()
                .all(|&b| (0x21..=0x7e).contains(&b) && !matches!(b, b'"' | b'\\'))
            || self.object_bytes == 0
            || self.object_bytes > 32 << 20
            || self.length == 0
            || self.length > 512 << 10
            || self
                .offset
                .checked_add(self.length as u64)
                .is_none_or(|end| end > self.object_bytes)
            || self.range_sha256.len() != 64
            || !self
                .range_sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(invalid());
        }
        Ok(port)
    }
    pub(super) fn end(&self) -> u64 {
        self.offset + self.length as u64 - 1
    }
}
