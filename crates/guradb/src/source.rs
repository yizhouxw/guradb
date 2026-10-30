use crate::{Error, Result, DECODE_LIMIT, SOURCE_LIMIT};
use arrow::{
    datatypes::{DataType, SchemaRef},
    record_batch::RecordBatch,
};
use bytes::Bytes;
use parquet::{
    arrow::arrow_reader::{ArrowReaderOptions, ParquetRecordBatchReaderBuilder},
    file::metadata::ParquetMetaData,
};
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

/// Operation-wide declaration and retained Arrow buffer limits are independent.
#[derive(Default)]
pub struct DecodeBudget {
    declared: usize,
    buffers: usize,
}
impl DecodeBudget {
    pub fn declare(&mut self, amount: usize) -> Result<()> {
        charge(
            &mut self.declared,
            amount,
            "Parquet decode size exceeds budget",
        )
    }
    fn retain(&mut self, amount: usize) -> Result<()> {
        charge(&mut self.buffers, amount, "Arrow buffers exceed budget")
    }
}
fn charge(total: &mut usize, amount: usize, message: &str) -> Result<()> {
    let next = total
        .checked_add(amount)
        .filter(|n| *n <= DECODE_LIMIT)
        .ok_or_else(|| Error::new("resource_limit", message))?;
    *total = next;
    Ok(())
}

pub fn declared_size(metadata: &ParquetMetaData) -> Result<usize> {
    let invalid = || Error::new("source_invalid", "invalid or unsupported Parquet");
    let mut declared = 0usize;
    for group in metadata.row_groups() {
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
    Ok(declared)
}

pub fn decode(bytes: Bytes) -> Result<(SchemaRef, Vec<RecordBatch>)> {
    decode_with_options(bytes, false, &mut DecodeBudget::default(), true)
}

/// Caller preflights every Iceberg physical schema/declaration into one budget
/// before decoding any file. Direct inputs continue to use a fresh budget.
pub fn decode_iceberg(
    bytes: Bytes,
    budget: &mut DecodeBudget,
) -> Result<(SchemaRef, Vec<RecordBatch>)> {
    decode_with_options(bytes, true, budget, false)
}

fn decode_with_options(
    bytes: Bytes,
    physical: bool,
    budget: &mut DecodeBudget,
    declare: bool,
) -> Result<(SchemaRef, Vec<RecordBatch>)> {
    let invalid = || Error::new("source_invalid", "invalid or unsupported Parquet");
    let builder = ParquetRecordBatchReaderBuilder::try_new_with_options(
        bytes,
        ArrowReaderOptions::new().with_skip_arrow_metadata(physical),
    )
    .map_err(|_| invalid())?;
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
    let declared = declared_size(builder.metadata())?;
    if declare {
        budget.declare(declared)?;
    }
    let reader = builder
        .with_batch_size(4096)
        .build()
        .map_err(|_| invalid())?;
    let mut batches = Vec::new();
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
        // Check each decoded batch before retaining it in the complete result;
        // the second file cannot independently collect another full allowance.
        budget.retain(batch.get_array_memory_size())?;
        batches.push(batch);
    }
    if batches.is_empty() {
        batches.push(RecordBatch::new_empty(schema.clone()));
    }
    Ok((schema, batches))
}

#[cfg(test)]
mod budget_tests {
    use super::*;
    use arrow::{
        array::StringArray,
        datatypes::{Field, Schema},
    };
    use parquet::arrow::ArrowWriter;
    use std::sync::Arc;

    fn repeated_text() -> Bytes {
        let schema = Arc::new(Schema::new(vec![Field::new("text", DataType::Utf8, true)]));
        let value = "x".repeat(65536);
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![Arc::new(StringArray::from(vec![value.as_str(); 512]))],
        )
        .unwrap();
        let mut bytes = Vec::new();
        {
            let mut writer = ArrowWriter::try_new(&mut bytes, schema, None).unwrap();
            writer.write(&batch).unwrap();
            writer.close().unwrap();
        }
        Bytes::from(bytes)
    }

    #[test]
    fn declarations_are_shared_and_reject_before_decode_can_start() {
        let bytes = repeated_text();
        let builder = ParquetRecordBatchReaderBuilder::try_new(bytes.clone()).unwrap();
        let declared = declared_size(builder.metadata()).unwrap();
        assert!(declared > 0 && declared < DECODE_LIMIT);
        let mut budget = DecodeBudget::default();
        budget.declare(DECODE_LIMIT - declared + 1).unwrap();
        assert_eq!(budget.declare(declared).unwrap_err().code, "resource_limit");
        assert_eq!(budget.buffers, 0);
        // Exhausting another operation's budget never changes direct reads.
        assert_eq!(
            decode(bytes)
                .unwrap()
                .1
                .iter()
                .map(|b| b.num_rows())
                .sum::<usize>(),
            512
        );
    }

    #[test]
    fn two_dictionary_files_share_actual_arrow_buffers_not_two_allowances() {
        let bytes = repeated_text();
        let builder = ParquetRecordBatchReaderBuilder::try_new(bytes.clone()).unwrap();
        let declared = declared_size(builder.metadata()).unwrap();
        let mut budget = DecodeBudget::default();
        budget.declare(declared).unwrap();
        budget.declare(declared).unwrap();
        let (_, first) = decode_iceberg(bytes.clone(), &mut budget).unwrap();
        let retained = first
            .iter()
            .map(RecordBatch::get_array_memory_size)
            .sum::<usize>();
        assert!(retained > DECODE_LIMIT / 2 && retained < DECODE_LIMIT);
        assert_eq!(budget.buffers, retained);
        assert_eq!(
            decode_iceberg(bytes, &mut budget).unwrap_err().code,
            "resource_limit"
        );
        assert_eq!(budget.buffers, retained);
        assert_eq!(first.iter().map(|b| b.num_rows()).sum::<usize>(), 512);
    }
}
