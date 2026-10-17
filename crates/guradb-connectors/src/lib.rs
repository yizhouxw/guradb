use arrow::{
    datatypes::{DataType, Field, Schema, SchemaRef},
    record_batch::RecordBatch,
};
use bytes::Bytes;
use guradb_common::{manifest::Manifest, Error, Result};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

pub fn schema(manifest: &Manifest) -> SchemaRef {
    Arc::new(Schema::new(
        manifest
            .schema
            .iter()
            .map(|field| {
                let kind = match field.data_type.as_str() {
                    "int8" => DataType::Int64,
                    "bool" => DataType::Boolean,
                    _ => DataType::Utf8,
                };
                Field::new(&field.name, kind, field.nullable)
            })
            .collect::<Vec<_>>(),
    ))
}

pub async fn decode(
    bytes: Bytes,
    expected: &SchemaRef,
    budget: usize,
    cancel: &CancellationToken,
) -> Result<(Vec<RecordBatch>, usize)> {
    let invalid = || {
        Error::new(
            "source_invalid",
            "Parquet schema, footer or data is invalid/unsupported",
        )
    };
    let builder = ParquetRecordBatchReaderBuilder::try_new(bytes).map_err(|_| invalid())?;
    let actual = builder.schema();
    if actual.fields() != expected.fields() {
        return Err(invalid());
    }
    let mut uncompressed = 0usize;
    for group in builder.metadata().row_groups() {
        for column in group.columns() {
            let size = usize::try_from(column.uncompressed_size()).map_err(|_| invalid())?;
            uncompressed = uncompressed.checked_add(size).ok_or_else(invalid)?;
            if uncompressed > budget {
                return Err(Error::new(
                    "resource_limit",
                    "Parquet declared decode size exceeds budget",
                ));
            }
        }
    }
    let reader = builder
        .with_batch_size(4096)
        .build()
        .map_err(|_| invalid())?;
    let mut output = Vec::new();
    let mut used = 0usize;
    for batch in reader {
        if cancel.is_cancelled() {
            return Err(Error::new("cancelled", "query cancelled"));
        }
        let batch = batch.map_err(|_| invalid())?;
        for (field, array) in expected.fields().iter().zip(batch.columns()) {
            if !field.is_nullable() && array.null_count() != 0 {
                return Err(invalid());
            }
        }
        used = used
            .checked_add(batch.get_array_memory_size())
            .ok_or_else(invalid)?;
        if used > budget {
            return Err(Error::new(
                "resource_limit",
                "decoded Arrow buffers exceed budget",
            ));
        }
        output.push(batch);
        tokio::task::yield_now().await;
    }
    Ok((output, used))
}
