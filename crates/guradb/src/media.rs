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
            "media requires the version 1 typed asset columns",
        ));
    }
    Ok(fields[0].0)
}
pub(crate) fn assets(schema: &SchemaRef, batches: &[RecordBatch]) -> Result<BTreeMap<i64, Asset>> {
    let id = index(schema, "image_id", DataType::Int64)?;
    let path = index(schema, "image_path", DataType::Utf8)?;
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
            if versions.value(row) != 1 {
                return Err(Error::new(
                    "unsupported_media_contract",
                    "unknown media version",
                ));
            }
            let key = ids.value(row);
            if !(1..=999_999_999_999).contains(&key)
                || paths.value(row) != format!("images/{key:012}.jpg")
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
    let descriptions = assets(&schema, &batches)?;
    let asset = descriptions
        .get(&id)
        .ok_or_else(|| Error::new("asset_missing", "asset ID is absent from this input"))?;
    let file_name = format!("{id:012}.jpg");
    let bytes = crate::media_path::read(&root, &file_name, asset.size)?;
    if hex::encode(Sha256::digest(&bytes)) != asset.sha256 {
        return Err(Error::new(
            "media_changed",
            "media SHA differs from bound input",
        ));
    }
    source::snapshot(&config.source, &config.sha256).await?;
    let result = serde_json::to_string(&json!({"media_version":1,"asset_id":id.to_string(),"source_sha256":config.sha256,
        "image_path":asset.path,"media_sha256":asset.sha256,"media_bytes":bytes.len(),"encoding":"hex","bytes_hex":hex::encode(&bytes)}))
        .map_err(|_| Error::new("output_failed", "cannot encode media evidence"))?;
    if result.len() > RESULT_LIMIT {
        return Err(Error::new(
            "resource_limit",
            "media output exceeds JSON budget",
        ));
    }
    Ok(result)
}
