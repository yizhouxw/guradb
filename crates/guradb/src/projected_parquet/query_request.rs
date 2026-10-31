//! The SQL source describes the entire object; physical selections are errors.
use super::request::{read_raw, Chunk, Range, Request};
use crate::Result;
use serde::Deserialize;
use std::path::Path;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    version: u32,
    origin: String,
    object_key: String,
    etag: String,
    object_bytes: u64,
    source_sha256_provenance: String,
    header: Range,
    footer: Range,
    chunks: Vec<Chunk>,
}
pub(super) fn read(path: &Path, argv_bytes: usize) -> Result<(Request, u16)> {
    let raw = read_raw(path)?;
    if argv_bytes.checked_add(raw.len()).is_none_or(|n| n > 65536) {
        return Err(super::limit());
    }
    let source: Source = serde_json::from_slice(&raw).map_err(|_| super::invalid())?;
    let request = Request {
        version: source.version,
        origin: source.origin,
        object_key: source.object_key,
        etag: source.etag,
        object_bytes: source.object_bytes,
        source_sha256_provenance: source.source_sha256_provenance,
        header: source.header,
        footer: source.footer,
        chunks: source.chunks,
        columns: Vec::new(),
        row_groups: Vec::new(),
    };
    let port = request.validate_descriptor()?;
    Ok((request, port))
}
