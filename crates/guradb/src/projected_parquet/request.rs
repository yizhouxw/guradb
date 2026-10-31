use crate::{object_range::request::Request as RangeRequest, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet, fs::OpenOptions, io::Read, os::unix::fs::OpenOptionsExt, path::Path,
};

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Range {
    pub offset: u64,
    pub length: usize,
    pub sha256: String,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Chunk {
    pub row_group: usize,
    pub column: usize,
    pub offset: u64,
    pub length: usize,
    pub sha256: String,
}
impl Chunk {
    pub fn range(&self) -> Range {
        Range {
            offset: self.offset,
            length: self.length,
            sha256: self.sha256.clone(),
        }
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub version: u32,
    pub origin: String,
    pub object_key: String,
    pub etag: String,
    pub object_bytes: u64,
    pub source_sha256_provenance: String,
    pub header: Range,
    pub footer: Range,
    pub chunks: Vec<Chunk>,
    pub columns: Vec<usize>,
    pub row_groups: Vec<usize>,
}
pub(super) fn sha(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn ordered(values: &[usize], max_len: usize, upper: usize) -> bool {
    !values.is_empty()
        && values.len() <= max_len
        && values.iter().all(|v| *v < upper)
        && values.windows(2).all(|v| v[0] < v[1])
}
pub(super) fn read_raw(path: &Path) -> Result<Vec<u8>> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(path)
        .map_err(|_| super::invalid())?;
    let info = file.metadata().map_err(|_| super::invalid())?;
    if !info.is_file() || info.len() > 16384 {
        return Err(super::invalid());
    }
    let mut raw = Vec::new();
    file.take(16385)
        .read_to_end(&mut raw)
        .map_err(|_| super::invalid())?;
    if raw.len() > 16384 {
        return Err(super::invalid());
    }
    Ok(raw)
}
impl Request {
    pub fn read(path: &Path) -> Result<(Self, u16)> {
        let raw = read_raw(path)?;
        let r: Self = serde_json::from_slice(&raw).map_err(|_| super::invalid())?;
        let port = r.validate()?;
        Ok((r, port))
    }
    pub fn range_request(&self, part: &Range) -> RangeRequest {
        RangeRequest {
            version: self.version,
            origin: self.origin.clone(),
            object_key: self.object_key.clone(),
            etag: self.etag.clone(),
            object_bytes: self.object_bytes,
            offset: part.offset,
            length: part.length,
            range_sha256: part.sha256.clone(),
        }
    }
    pub(super) fn validate(&self) -> Result<u16> {
        if !ordered(&self.columns, 3, 8) || !ordered(&self.row_groups, 2, 4) {
            return Err(super::invalid());
        }
        let port = self.validate_descriptor()?;
        self.validate_plan()?;
        Ok(port)
    }
    pub(super) fn validate_descriptor(&self) -> Result<u16> {
        let port = self
            .range_request(&self.header)
            .validate()
            .map_err(|_| super::invalid())?;
        if !sha(&self.source_sha256_provenance)
            || self.header.offset != 0
            || self.header.length != 4
            || self.footer.offset < 4
            || self.footer.length <= 8
            || self.footer.offset.checked_add(self.footer.length as u64) != Some(self.object_bytes)
            || self.chunks.is_empty()
            || self.chunks.len() > 32
        {
            return Err(super::invalid());
        }
        self.range_request(&self.footer)
            .validate()
            .map_err(|_| super::invalid())?;
        let mut ids = BTreeSet::new();
        let mut spans = Vec::new();
        for c in &self.chunks {
            if c.row_group >= 4
                || c.column >= 8
                || !ids.insert((c.row_group, c.column))
                || c.length == 0
                || !sha(&c.sha256)
                || c.offset < 4
                || c.offset
                    .checked_add(c.length as u64)
                    .is_none_or(|e| e > self.footer.offset)
            {
                return Err(super::invalid());
            }
            spans.push((c.offset, c.offset + c.length as u64));
        }
        spans.sort_unstable();
        if spans.windows(2).any(|v| v[0].1 > v[1].0) {
            return Err(super::invalid());
        }
        Ok(port)
    }
    pub(super) fn validate_plan(&self) -> Result<()> {
        let mut payload = self
            .header
            .length
            .checked_add(self.footer.length)
            .ok_or_else(super::invalid)?;
        for g in &self.row_groups {
            for col in &self.columns {
                let c = self.chunk(*g, *col)?;
                payload = payload.checked_add(c.length).ok_or_else(super::invalid)?;
            }
        }
        if 2 + self.row_groups.len() * self.columns.len() > 8 || payload > 512 << 10 {
            return Err(super::limit());
        }
        Ok(())
    }
    pub fn chunk(&self, group: usize, column: usize) -> Result<&Chunk> {
        self.chunks
            .iter()
            .find(|c| c.row_group == group && c.column == column)
            .ok_or_else(super::invalid)
    }
}
