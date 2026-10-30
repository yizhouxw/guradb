//! Explicit local fixed Iceberg snapshot; no catalog, discovery or writes.
mod data;
mod manifest;
mod metadata;
mod path;
#[cfg(test)]
mod tests;

use crate::{Column, Dataset, Error, Manifest, Result};
use bytes::Bytes;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    path::PathBuf,
    sync::Arc,
    time::Duration,
};

const METADATA_LIMIT: usize = 256 << 10;
const MANIFEST_LIMIT: usize = 512 << 10;
const CHAIN_LIMIT: usize = 2 << 20;
fn invalid() -> Error {
    Error::new(
        "unsupported",
        "invalid or unsupported local Iceberg snapshot",
    )
}
fn hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
fn digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
struct Request {
    root: PathBuf,
    metadata: String,
    metadata_sha: String,
    snapshot: i64,
    expected_readset: Option<String>,
    sql: Option<String>,
}
fn request(args: &[String]) -> Result<Request> {
    let query = args.get(2).is_some_and(|v| v == "query");
    if (!query && args.get(2).is_none_or(|v| v != "inspect"))
        || args.len() != if query { 15 } else { 11 }
    {
        return Err(invalid());
    }
    let mut values = BTreeMap::new();
    for pair in args[3..].chunks_exact(2) {
        if values.insert(pair[0].as_str(), pair[1].as_str()).is_some() {
            return Err(invalid());
        }
    }
    let take = |key| values.get(key).copied().ok_or_else(invalid);
    let metadata = take("--metadata")?.to_string();
    path::relative(&metadata)?;
    let metadata_sha = take("--metadata-sha256")?.to_string();
    let snapshot = take("--snapshot")?.parse::<i64>().map_err(|_| invalid())?;
    if !digest(&metadata_sha) || snapshot <= 0 {
        return Err(invalid());
    }
    let (expected_readset, sql) = if query {
        let pin = take("--readset-sha256")?;
        if !digest(pin) {
            return Err(invalid());
        }
        (Some(pin.to_string()), Some(take("--sql")?.to_string()))
    } else {
        (None, None)
    };
    Ok(Request {
        root: PathBuf::from(take("--table-root")?),
        metadata,
        metadata_sha,
        snapshot,
        expected_readset,
        sql,
    })
}
pub async fn entry(args: Vec<String>) {
    let request = match request(&args) {
        Ok(r) => r,
        Err(e) => crate::fail(e, 1),
    };
    crate::operation(Duration::from_secs(10), move || {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .map_err(|_| Error::new("execution_failed", "cannot start Iceberg query runtime"))?;
        runtime.block_on(run(request))
    })
    .await;
}
struct Captured {
    sha: String,
    limit: usize,
}
struct Readset {
    root: path::Root,
    files: BTreeMap<String, Captured>,
    chain_bytes: usize,
}
impl Readset {
    fn read(&mut self, relative: &str, limit: usize, data: bool) -> Result<Vec<u8>> {
        if self.files.len() == 6 || self.files.contains_key(relative) {
            return Err(invalid());
        }
        let bytes = self.root.read(relative, limit)?;
        if !data {
            self.chain_bytes = self
                .chain_bytes
                .checked_add(bytes.len())
                .ok_or_else(invalid)?;
            if self.chain_bytes > CHAIN_LIMIT {
                return Err(Error::new(
                    "resource_limit",
                    "Iceberg metadata chain exceeds byte budget",
                ));
            }
        }
        self.files.insert(
            relative.into(),
            Captured {
                sha: hash(&bytes),
                limit,
            },
        );
        Ok(bytes)
    }
    fn pin(&self, meta: &metadata::Metadata) -> String {
        let mut digest = Sha256::new();
        digest.update(format!(
            "guradb-iceberg-readset-v1\n{}\n{}\n{}\n",
            meta.uuid, meta.snapshot, meta.schema_id
        ));
        for (path, file) in &self.files {
            digest.update(path.as_bytes());
            digest.update(b"\0");
            digest.update(file.sha.as_bytes());
            digest.update(b"\n");
        }
        hex::encode(digest.finalize())
    }
    fn recheck(&self) -> Result<()> {
        for (path, file) in &self.files {
            let bytes = self.root.read(path, file.limit)?;
            if hash(&bytes) != file.sha {
                return Err(Error::new(
                    "source_changed",
                    "Iceberg readset changed while executing",
                ));
            }
        }
        Ok(())
    }
}
#[derive(serde::Serialize)]
struct SourceFile {
    path: String,
    sha256: String,
    size_bytes: usize,
    record_count: usize,
}
fn source_identity(uuid: &str, files: &[SourceFile]) -> Result<String> {
    if files.len() == 1 {
        return Ok(files[0].sha256.clone());
    }
    if files.len() != 2 || files[0].path >= files[1].path {
        return Err(invalid());
    }
    let mut digest = Sha256::new();
    digest.update(format!("guradb-iceberg-data-files-v1\n{uuid}\n"));
    for file in files {
        digest.update(file.path.as_bytes());
        digest.update(b"\0");
        digest.update(file.sha256.as_bytes());
        digest.update(b"\n");
    }
    Ok(hex::encode(digest.finalize()))
}
async fn run(request: Request) -> Result<String> {
    let mut readset = Readset {
        root: path::Root::open(&request.root)?,
        files: BTreeMap::new(),
        chain_bytes: 0,
    };
    let bytes = readset.read(&request.metadata, METADATA_LIMIT, false)?;
    if hash(&bytes) != request.metadata_sha {
        return Err(Error::new(
            "source_changed",
            "Iceberg metadata SHA differs from requested pin",
        ));
    }
    let meta = metadata::parse(&bytes, request.snapshot)?;
    let list = readset.read(&meta.manifest_list, METADATA_LIMIT, false)?;
    let manifests = manifest::list(&list, &meta)?;
    let mut references: HashSet<String> = readset.files.keys().cloned().collect();
    let mut live = Vec::new();
    let mut entries = 0;
    for manifest in manifests {
        if !references.insert(manifest.path.clone()) {
            return Err(invalid());
        }
        let bytes = readset.read(&manifest.path, MANIFEST_LIMIT, false)?;
        if bytes.len() != manifest.length {
            return Err(invalid());
        }
        let files = manifest::entries(&bytes, &meta, &manifest.counts)?;
        entries += files.len();
        if entries > 64 {
            return Err(Error::new(
                "resource_limit",
                "Iceberg snapshot exceeds entry budget",
            ));
        }
        for file in files {
            if !references.insert(file.path.clone()) {
                return Err(invalid());
            }
            if file.status != 2 {
                live.push(file);
            }
        }
    }
    if live.is_empty() || live.len() > 2 {
        return Err(invalid());
    }
    live.sort_by(|a, b| a.path.cmp(&b.path));
    let mut source_files = Vec::new();
    let mut captured = Vec::new();
    let mut source_bytes = 0usize;
    for file in live {
        let remaining = crate::SOURCE_LIMIT
            .checked_sub(source_bytes)
            .ok_or_else(invalid)?;
        let bytes = readset.read(&file.path, remaining, true)?;
        source_bytes = source_bytes.checked_add(bytes.len()).ok_or_else(invalid)?;
        source_files.push(SourceFile {
            path: file.path,
            sha256: hash(&bytes),
            size_bytes: bytes.len(),
            record_count: file.rows,
        });
        captured.push((Bytes::from(bytes), file.size));
    }
    let source_sha = source_identity(&meta.uuid, &source_files)?;
    let readset_sha = readset.pin(&meta);
    if request
        .expected_readset
        .as_ref()
        .is_some_and(|pin| pin != &readset_sha)
    {
        return Err(Error::new(
            "source_changed",
            "Iceberg complete readset differs from requested pin",
        ));
    }
    let mut budget = crate::source::DecodeBudget::default();
    for ((bytes, size), file) in captured.iter().zip(&source_files) {
        if bytes.len() != *size {
            return Err(invalid());
        }
        budget.declare(data::validate(bytes.clone(), &meta, file.record_count)?)?;
    }
    let mut batches = Vec::new();
    let mut schema = None;
    let mut rows = 0usize;
    for ((bytes, _), file) in captured.into_iter().zip(&source_files) {
        let (current, decoded) = crate::source::decode_iceberg(bytes, &mut budget)?;
        if decoded.iter().map(|b| b.num_rows()).sum::<usize>() != file.record_count {
            return Err(invalid());
        }
        if schema.as_ref().is_some_and(|previous| previous != &current) {
            return Err(invalid());
        }
        rows = rows.checked_add(file.record_count).ok_or_else(invalid)?;
        schema = Some(current);
        batches.extend(decoded);
    }
    let schema = schema.ok_or_else(invalid)?;
    let mut output: Value = if let Some(sql) = request.sql {
        let columns = meta
            .fields
            .iter()
            .map(|field| Column {
                name: field.name.clone(),
                r#type: match field.kind.as_str() {
                    "long" => "int8",
                    "boolean" => "bool",
                    _ => "text",
                }
                .into(),
            })
            .collect();
        let dataset = Arc::new(Dataset {
            manifest: Manifest { schema: columns },
        });
        let plan = crate::sql::prepare(&sql, dataset)?;
        let result = crate::execution::execute(plan, schema, batches, &source_sha).await?;
        serde_json::from_str(&result).map_err(|_| invalid())?
    } else {
        json!({"source_sha256": source_sha, "record_count": rows})
    };
    if source_files.len() == 2 {
        output["source_identity"] = json!("iceberg-data-files-v1");
        output["source_files"] = json!(source_files);
    }
    output["table_uuid"] = json!(meta.uuid);
    output["snapshot_id"] = json!(meta.snapshot);
    output["schema_id"] = json!(meta.schema_id);
    output["metadata_sha256"] = json!(request.metadata_sha);
    output["readset_sha256"] = json!(readset_sha);
    output["readset"] = json!(readset
        .files
        .iter()
        .map(|(path, file)| json!({"path": path,"sha256": file.sha}))
        .collect::<Vec<_>>());
    let output = serde_json::to_string(&output).map_err(|_| invalid())?;
    if output.len() > crate::RESULT_LIMIT {
        return Err(Error::new(
            "resource_limit",
            "Iceberg result exceeds output budget",
        ));
    }
    readset.recheck()?;
    Ok(output)
}
