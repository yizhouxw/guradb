use crate::{Error, Result, DECODE_LIMIT, SOURCE_LIMIT};
use arrow::{
    datatypes::{DataType, SchemaRef},
    record_batch::RecordBatch,
};
use bytes::Bytes;
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use sha2::{Digest, Sha256};
use std::path::Path;
use tokio::io::AsyncReadExt;

pub async fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    // Inspect before open so a FIFO/device cannot block an async filesystem
    // worker; this alpha assumes the trusted operator controls the directory.
    let metadata = tokio::fs::metadata(path)
        .await
        .map_err(|_| Error::new("source_invalid", "source is unavailable"))?;
    if !metadata.is_file() || metadata.len() > maximum as u64 {
        return Err(Error::new(
            "resource_limit",
            "source must be a bounded regular file",
        ));
    }
    let file = tokio::fs::File::open(path)
        .await
        .map_err(|_| Error::new("source_invalid", "cannot open source"))?;
    if !file
        .metadata()
        .await
        .map_err(|_| Error::new("source_invalid", "cannot inspect source"))?
        .is_file()
    {
        return Err(Error::new("source_invalid", "source is not a regular file"));
    }
    let mut bytes = Vec::new();
    file.take((maximum + 1) as u64)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| Error::new("source_invalid", "cannot read source"))?;
    if bytes.len() > maximum {
        return Err(Error::new("resource_limit", "source exceeds byte limit"));
    }
    Ok(bytes)
}

pub async fn snapshot(path: &Path, expected: &str) -> Result<Bytes> {
    let bytes = read_bounded(path, SOURCE_LIMIT).await?;
    if hex::encode(Sha256::digest(&bytes)) != expected {
        return Err(Error::new(
            "source_changed",
            "source SHA256 differs from config",
        ));
    }
    Ok(Bytes::from(bytes))
}

pub fn decode(bytes: Bytes) -> Result<(SchemaRef, Vec<RecordBatch>)> {
    let invalid = || Error::new("source_invalid", "invalid or unsupported Parquet");
    let builder = ParquetRecordBatchReaderBuilder::try_new(bytes).map_err(|_| invalid())?;
    let schema = builder.schema().clone();
    if schema.fields().is_empty()
        || schema.fields().len() > 64
        || schema.fields().iter().any(|f| {
            !matches!(
                f.data_type(),
                DataType::Int64 | DataType::Utf8 | DataType::Boolean
            )
        })
    {
        return Err(invalid());
    }
    let mut declared = 0usize;
    for group in builder.metadata().row_groups() {
        for column in group.columns() {
            declared = declared
                .checked_add(usize::try_from(column.uncompressed_size()).map_err(|_| invalid())?)
                .ok_or_else(invalid)?;
            if declared > DECODE_LIMIT {
                return Err(Error::new(
                    "resource_limit",
                    "Parquet decode size exceeds budget",
                ));
            }
        }
    }
    let reader = builder
        .with_batch_size(4096)
        .build()
        .map_err(|_| invalid())?;
    let mut batches = Vec::new();
    let mut used = 0usize;
    for batch in reader {
        let batch = batch.map_err(|_| invalid())?;
        if schema
            .fields()
            .iter()
            .zip(batch.columns())
            .any(|(field, array)| !field.is_nullable() && array.null_count() != 0)
        {
            return Err(invalid());
        }
        used = used
            .checked_add(batch.get_array_memory_size())
            .ok_or_else(invalid)?;
        if used > DECODE_LIMIT {
            return Err(Error::new("resource_limit", "Arrow buffers exceed budget"));
        }
        batches.push(batch);
    }
    if batches.is_empty() {
        batches.push(RecordBatch::new_empty(schema.clone()));
    }
    Ok((schema, batches))
}
