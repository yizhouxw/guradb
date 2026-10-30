//! A versioned asset description lives inside the SHA-bound Parquet itself.
use crate::{source, Config, Error, Result, RESULT_LIMIT};
use arrow::{
    array::{Int64Array, StringArray},
    datatypes::{DataType, SchemaRef},
    record_batch::RecordBatch,
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::PathBuf};

pub const MEDIA_LIMIT: usize = 512 << 10;
#[derive(Clone, PartialEq, Eq)]
pub(crate) struct Asset {
    pub(crate) path: String,
    pub(crate) sha256: String,
    pub(crate) size: usize,
    pub(crate) version: i64,
    pub(crate) kind: String,
}
fn invalid() -> Error {
    Error::new(
        "invalid_media_binding",
        "invalid or conflicting asset description",
    )
}
fn index(schema: &SchemaRef, name: &str, data_type: DataType) -> Result<usize> {
    let fields: Vec<_> = schema
        .fields()
        .iter()
        .enumerate()
        .filter(|(_, f)| f.name() == name)
        .collect();
    if fields.len() != 1 || fields[0].1.data_type() != &data_type {
        return Err(Error::new(
            "unsupported_media_contract",
            "media requires the declared typed asset columns",
        ));
    }
    Ok(fields[0].0)
}
pub(crate) fn assets(schema: &SchemaRef, batches: &[RecordBatch]) -> Result<BTreeMap<i64, Asset>> {
    let v2 = version2(schema);
    if v2 {
        let allowed = [
            "doc_id",
            "text",
            "text_version",
            "asset_id",
            "asset_path",
            "asset_type",
            "media_version",
            "media_bytes",
            "media_sha256",
        ];
        if schema.fields().len() != 9
            || schema
                .fields()
                .iter()
                .any(|f| !allowed.contains(&f.name().as_str()))
        {
            return Err(invalid());
        }
    }
    let id = index(
        schema,
        if v2 { "asset_id" } else { "image_id" },
        DataType::Int64,
    )?;
    let path = index(
        schema,
        if v2 { "asset_path" } else { "image_path" },
        DataType::Utf8,
    )?;
    let kind = if v2 {
        Some(index(schema, "asset_type", DataType::Utf8)?)
    } else {
        None
    };
    let version = index(schema, "media_version", DataType::Int64)?;
    let size = index(schema, "media_bytes", DataType::Int64)?;
    let sha = index(schema, "media_sha256", DataType::Utf8)?;
    if batches.iter().map(RecordBatch::num_rows).sum::<usize>() > 200 {
        return Err(Error::new(
            "resource_limit",
            "media description exceeds 200 rows",
        ));
    }
    let mut result = BTreeMap::new();
    for batch in batches {
        let ids = batch
            .column(id)
            .as_any()
            .downcast_ref::<Int64Array>()
            .ok_or_else(invalid)?;
        let paths = batch
            .column(path)
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or_else(invalid)?;
        let versions = batch
            .column(version)
            .as_any()
            .downcast_ref::<Int64Array>()
            .ok_or_else(invalid)?;
        let sizes = batch
            .column(size)
            .as_any()
            .downcast_ref::<Int64Array>()
            .ok_or_else(invalid)?;
        let hashes = batch
            .column(sha)
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or_else(invalid)?;
        for row in 0..batch.num_rows() {
            if [id, path, version, size, sha]
                .iter()
                .any(|&i| batch.column(i).is_null(row))
            {
                return Err(invalid());
            }
            if versions.value(row) != if v2 { 2 } else { 1 } {
                return Err(Error::new(
                    "unsupported_media_contract",
                    "unknown media version",
                ));
            }
            let media_type = if let Some(index) = kind {
                if batch.column(index).is_null(row) {
                    return Err(invalid());
                }
                batch
                    .column(index)
                    .as_any()
                    .downcast_ref::<StringArray>()
                    .ok_or_else(invalid)?
                    .value(row)
            } else {
                "image/jpeg"
            };
            let (directory, extension) = match media_type {
                "image/jpeg" => ("images", "jpg"),
                "audio/wav" => ("audio", "wav"),
                _ => return Err(invalid()),
            };
            let key = ids.value(row);
            if !(1..=999_999_999_999).contains(&key)
                || paths.value(row) != format!("{directory}/{key:012}.{extension}")
            {
                return Err(invalid());
            }
            let count = usize::try_from(sizes.value(row)).map_err(|_| invalid())?;
            if count == 0 {
                return Err(invalid());
            }
            if count > MEDIA_LIMIT {
                return Err(Error::new("resource_limit", "bound media exceeds 512 KiB"));
            }
            let hash = hashes.value(row);
            if hash.len() != 64
                || !hash
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return Err(invalid());
            }
            let asset = Asset {
                path: paths.value(row).into(),
                sha256: hash.into(),
                size: count,
                version: if v2 { 2 } else { 1 },
                kind: media_type.into(),
            };
            if let Some(previous) = result.insert(key, asset.clone()) {
                if previous != asset {
                    return Err(invalid());
                }
            }
            if result.len() > 3 {
                return Err(Error::new(
                    "resource_limit",
                    "media description exceeds three assets",
                ));
            }
        }
    }
    Ok(result)
}

pub async fn read(config: Config, root: PathBuf, id: i64) -> Result<String> {
    let bytes = source::snapshot(&config.source, &config.sha256).await?;
    let (schema, batches) = source::decode(bytes)?;
    if version2(&schema) {
        crate::search::documents(&schema, &batches, &[])?;
    }
    let descriptions = assets(&schema, &batches)?;
    let asset = descriptions
        .get(&id)
        .ok_or_else(|| Error::new("asset_missing", "asset ID is absent from this input"))?;
    let bytes = checked_bytes(&root, asset)?;
    source::snapshot(&config.source, &config.sha256).await?;
    let mut result = asset.identity(id);
    result["source_sha256"] = json!(config.sha256);
    result["encoding"] = json!("hex");
    result["bytes_hex"] = json!(hex::encode(&bytes));
    if asset.kind == "audio/wav" {
        result["audio"] =
            serde_json::to_value(crate::wav::inspect(&bytes)?).map_err(|_| invalid())?;
    }
    let result = serde_json::to_string(&result)
        .map_err(|_| Error::new("output_failed", "cannot encode media evidence"))?;
    if result.len() > RESULT_LIMIT {
        return Err(Error::new(
            "resource_limit",
            "media output exceeds JSON budget",
        ));
    }
    Ok(result)
}

pub(crate) fn version2(schema: &SchemaRef) -> bool {
    schema
        .fields()
        .iter()
        .any(|f| ["asset_id", "asset_path", "asset_type"].contains(&f.name().as_str()))
}
pub(crate) fn reject_v2(schema: &SchemaRef) -> Result<()> {
    if version2(schema) {
        return Err(Error::new(
            "unsupported_media_contract",
            "media v2 is unavailable to features, vector, hybrid and sample",
        ));
    }
    Ok(())
}
impl Asset {
    pub(crate) fn identity(&self, id: i64) -> serde_json::Value {
        if self.version == 1 {
            json!({"asset_id":id.to_string(),"image_path":self.path,"media_sha256":self.sha256,"media_bytes":self.size,"media_version":1})
        } else {
            json!({"asset_id":id.to_string(),"asset_path":self.path,"asset_type":self.kind,"media_sha256":self.sha256,"media_bytes":self.size,"media_version":2})
        }
    }
}
pub(crate) fn checked_bytes(root: &std::path::Path, asset: &Asset) -> Result<Vec<u8>> {
    let (directory, file) = asset.path.split_once('/').ok_or_else(invalid)?;
    let bytes = crate::media_path::read_typed(root, directory, file, asset.size)?;
    if hex::encode(Sha256::digest(&bytes)) != asset.sha256 {
        return Err(Error::new(
            "media_changed",
            "media SHA differs from bound input",
        ));
    }
    if asset.version == 2 {
        if asset.kind == "audio/wav" {
            crate::wav::inspect(&bytes)?;
        } else if !bytes.starts_with(&[0xff, 0xd8, 0xff]) || !bytes.ends_with(&[0xff, 0xd9]) {
            return Err(Error::new("invalid_media_format", "invalid JPEG signature"));
        }
    }
    Ok(bytes)
}
