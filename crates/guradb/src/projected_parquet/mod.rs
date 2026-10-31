//! Explicit local HTTP projection. Whole-source SHA is provenance only.
mod bounded;
mod metadata;
mod pages;
mod reader;
mod request;
mod sparse;
#[cfg(test)]
mod tests;
use crate::{Error, Result};
use bytes::Bytes;
use request::{Range, Request};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    path::Path,
    time::{Duration, Instant},
};

fn invalid() -> Error {
    Error::new(
        "invalid_parquet_read",
        "invalid or unsupported projected Parquet input",
    )
}
fn limit() -> Error {
    Error::new(
        "resource_limit",
        "projected Parquet operation exceeds budget",
    )
}
pub async fn entry(args: Vec<String>) {
    crate::operation(Duration::from_secs(10), move || run(args)).await;
}
struct Transfer {
    deadline: Instant,
    port: u16,
    payload: usize,
    headers: usize,
    ranges: Vec<Value>,
}
impl Transfer {
    fn get(
        &mut self,
        r: &Request,
        part: &Range,
        kind: &str,
        identity: Option<(usize, usize)>,
    ) -> Result<Bytes> {
        if self.ranges.len() >= 8
            || self
                .payload
                .checked_add(part.length)
                .is_none_or(|n| n > 512 << 10)
        {
            return Err(limit());
        }
        let allowance = (64usize << 10)
            .checked_sub(self.headers)
            .ok_or_else(limit)?;
        let (body, headers) = crate::object_range::http::get_limited(
            &r.range_request(part),
            self.port,
            self.deadline,
            allowance,
        )?;
        if hex::encode(Sha256::digest(&body)) != part.sha256 {
            return Err(Error::new(
                "range_mismatch",
                "range bytes differ from expected SHA256",
            ));
        }
        self.payload += body.len();
        self.headers += headers;
        let mut record =
            json!({"kind":kind,"offset":part.offset,"length":body.len(),"sha256":part.sha256});
        if let Some((g, c)) = identity {
            record["row_group"] = json!(g);
            record["column"] = json!(c);
        }
        self.ranges.push(record);
        Ok(Bytes::from(body))
    }
}
fn run(args: Vec<String>) -> Result<String> {
    let deadline = Instant::now() + Duration::from_secs(10);
    if args.len() != 4 || args[2] != "--request" {
        return Err(invalid());
    }
    let (r, port) = Request::read(Path::new(&args[3]))?;
    let mut transfer = Transfer {
        deadline,
        port,
        payload: 0,
        headers: 0,
        ranges: Vec::new(),
    };
    let head = transfer.get(&r, &r.header, "header", None)?;
    if head.as_ref() != b"PAR1" {
        return Err(invalid());
    }
    let footer = transfer.get(&r, &r.footer, "footer", None)?;
    let mut decode_budget = bounded::Budget::default();
    let metadata = metadata::parse(&r, &footer, &mut decode_budget)?;
    let source_rows = metadata.metadata().file_metadata().num_rows();
    let mut sparse = sparse::Sparse {
        length: r.object_bytes,
        segments: Vec::new(),
        read_calls: Default::default(),
    };
    for g in &r.row_groups {
        for c in &r.columns {
            let part = r.chunk(*g, *c)?.range();
            let bytes = transfer.get(&r, &part, "chunk", Some((*g, *c)))?;
            sparse.segments.push((part.offset, bytes));
        }
    }
    let (columns, rows, decode_bytes) = reader::decode(&r, metadata, sparse, &mut decode_budget)?;
    let result = json!({"backend":"local-http-projected-parquet-v1","origin":r.origin,"object_key":r.object_key,"etag":r.etag,
        "declared_object_bytes":r.object_bytes,"source_sha256_provenance":r.source_sha256_provenance,
        "columns":columns,"decoded_rows":rows.len(),"rows":rows,"source_rows":source_rows,
        "selected_columns":r.columns,"selected_row_groups":r.row_groups,"read_ranges":transfer.ranges,
        "request_count":transfer.ranges.len(),"payload_bytes":transfer.payload,"header_bytes":transfer.headers,
        "decode_charged_bytes":decode_bytes,"verification":"selected_ranges_only","unread_content_verified":false});
    let output = serde_json::to_string(&result).map_err(|_| invalid())?;
    if output.len() > crate::RESULT_LIMIT {
        return Err(limit());
    }
    Ok(output)
}
