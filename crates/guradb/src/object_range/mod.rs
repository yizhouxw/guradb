//! One conditional GET of a fixed local object's bounded byte range.
pub(crate) mod http;
pub(crate) mod request;
use crate::{Error, Result, RESULT_LIMIT};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    path::Path,
    time::{Duration, Instant},
};
pub async fn entry(args: Vec<String>) {
    crate::operation(Duration::from_secs(10), move || run(args)).await;
}
fn run(args: Vec<String>) -> Result<String> {
    let deadline = Instant::now() + Duration::from_secs(10);
    if args.len() != 4 || args[2] != "--request" {
        return Err(request::invalid());
    }
    let (r, port) = request::Request::read(Path::new(&args[3]))?;
    let (body, header_bytes) = http::get(&r, port, deadline)?;
    let hash = hex::encode(Sha256::digest(&body));
    if hash != r.range_sha256 {
        return Err(Error::new(
            "range_mismatch",
            "range bytes differ from expected SHA256",
        ));
    }
    let result = json!({"backend":"local-http-range-v1","origin":r.origin,"object_key":r.object_key,"etag":r.etag,"declared_object_bytes":r.object_bytes,"offset":r.offset,"length":r.length,"range_sha256":hash,"request_count":1,"response_status":206,"header_bytes":header_bytes,"encoding":"hex","bytes_hex":hex::encode(body),"verification":"range_only"});
    let out = serde_json::to_string(&result)
        .map_err(|_| Error::new("output_failed", "cannot encode range result"))?;
    if out.len() > RESULT_LIMIT {
        return Err(Error::new("resource_limit", "range output exceeds budget"));
    }
    Ok(out)
}
