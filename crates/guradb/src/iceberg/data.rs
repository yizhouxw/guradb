use super::{invalid, metadata::Metadata};
use crate::Result;
use arrow::datatypes::DataType;
use bytes::Bytes;
use parquet::{
    arrow::arrow_reader::{ArrowReaderOptions, ParquetRecordBatchReaderBuilder},
    basic::{Compression, Repetition, Type},
};

pub fn validate(bytes: Bytes, meta: &Metadata, expected_rows: usize) -> Result<usize> {
    let builder = ParquetRecordBatchReaderBuilder::try_new_with_options(
        bytes,
        ArrowReaderOptions::new().with_skip_arrow_metadata(true),
    )
    .map_err(|_| invalid())?;
    let schema = builder.schema();
    let physical = builder.parquet_schema().root_schema();
    let fields = physical.get_fields();
    if fields.len() != meta.fields.len()
        || schema.fields().len() != fields.len()
        || builder.metadata().file_metadata().num_rows() != expected_rows as i64
    {
        return Err(invalid());
    }
    for ((expected, physical), arrow) in meta.fields.iter().zip(fields).zip(schema.fields()) {
        let info = physical.get_basic_info();
        let (kind, scalar) = match expected.kind.as_str() {
            "long" => (Type::INT64, DataType::Int64),
            "string" => (Type::BYTE_ARRAY, DataType::Utf8),
            "boolean" => (Type::BOOLEAN, DataType::Boolean),
            _ => return Err(invalid()),
        };
        if !physical.is_primitive()
            || !info.has_id()
            || info.id() != expected.id
            || info.name() != expected.name
            || physical.get_physical_type() != kind
            || arrow.data_type() != &scalar
            || arrow.name() != &expected.name
            || arrow.is_nullable() == expected.required
            || info.repetition()
                != if expected.required {
                    Repetition::REQUIRED
                } else {
                    Repetition::OPTIONAL
                }
        {
            return Err(invalid());
        }
    }
    for group in builder.metadata().row_groups() {
        for column in group.columns() {
            if !matches!(
                column.compression(),
                Compression::UNCOMPRESSED | Compression::SNAPPY
            ) {
                return Err(invalid());
            }
        }
    }
    crate::source::declared_size(builder.metadata())
}
