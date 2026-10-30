//! Complete validation of the already supported immutable view input.
//! This module does not copy, admit, publish or mutate a managed operation.
use super::{capture, state};
use crate::{features as feature_input, source, Config, Error, Result};
use arrow::datatypes::DataType;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::Path;

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Column {
    pub name: String,
    pub kind: String,
    pub nullable: bool,
}

pub struct Input {
    pub config: Config,
    pub schema_id: String,
    pub columns: Vec<Column>,
    pub record: state::Record,
    pub rows: usize,
    pub assets: usize,
}

/// Inspect every row/asset and, when supplied, the complete pinned feature set.
/// The media origin is config.parent, exactly as in the existing view capture.
/// Source and optional feature bytes remain caller-owned at this point; the
/// later capture must validate again before it can claim durable owned data.
///
/// Schema identity is lowercase hex SHA256 of these exact bytes:
/// b"guradb-schema-v1\n" followed by serde_json::to_vec(&columns), no trailing LF.
/// The JSON is a compact UTF8 array in physical schema column order. Each
/// element has fields in declaration order: name, kind, nullable. kind is one
/// of the fixed strings "Int64", "Boolean", "Utf8"; Arrow metadata is excluded.
/// Renaming, reordering, type or nullable changes therefore alter the identity.
/// This does not broaden capture::validate's existing generic media layout.
pub async fn inspect(
    path: &Path,
    features: Option<(&Path, &str)>,
    request_id: &str,
) -> Result<Input> {
    if !state::request(request_id) {
        return Err(Error::new("invalid_config", "invalid input request ID"));
    }
    let config = capture::config(path).await?;
    let origin = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let (snapshot, assets, ids) = capture::validate(&config, origin).await?;
    let (schema, batches) = source::decode(snapshot)?;
    let row_count: usize = batches.iter().map(|batch| batch.num_rows()).sum();
    if row_count != ids.len() || !(1..=200).contains(&row_count) || assets.len() > 3 {
        return Err(Error::new(
            "invalid_view_input",
            "validated input must retain every source row and asset",
        ));
    }
    let columns: Vec<Column> = schema
        .fields()
        .iter()
        .map(|field| {
            let kind = match field.data_type() {
                DataType::Int64 => "Int64",
                DataType::Boolean => "Boolean",
                DataType::Utf8 => "Utf8",
                _ => {
                    return Err(Error::new(
                        "unsupported_schema",
                        "managed input supports only Int64, Boolean and Utf8",
                    ));
                }
            };
            Ok(Column {
                name: field.name().clone(),
                kind: kind.into(),
                nullable: field.is_nullable(),
            })
        })
        .collect::<Result<_>>()?;
    drop(batches);
    let encoded = serde_json::to_vec(&columns)
        .map_err(|_| Error::new("invalid_view_input", "cannot encode ordered input schema"))?;
    let mut digest = Sha256::new();
    digest.update(b"guradb-schema-v1\n");
    digest.update(&encoded);
    let schema_id = hex::encode(digest.finalize());
    let bound = if let Some((path, pin)) = features {
        let loaded = feature_input::load(path, pin, &config.sha256, &ids).await?;
        feature_input::snapshot(path, pin).await?;
        Some(state::BoundFeatures {
            sha256: pin.into(),
            space: loaded.space,
        })
    } else {
        None
    };
    source::snapshot(&config.source, &config.sha256).await?;
    let record = state::Record {
        source_sha256: bound.as_ref().map(|_| config.sha256.clone()),
        id: bound.as_ref().map_or_else(
            || config.sha256.clone(),
            |features| state::identity(&config.sha256, &features.sha256),
        ),
        features: bound,
        request_id: request_id.into(),
        published: false,
    };
    if !record.valid() {
        return Err(Error::new(
            "invalid_view_input",
            "invalid bound input identity",
        ));
    }
    Ok(Input {
        config,
        schema_id,
        columns,
        record,
        rows: ids.len(),
        assets: assets.len(),
    })
}
