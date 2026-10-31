use super::{invalid, request::Request, sparse::Sparse};
use crate::Result;
use arrow::{
    array::{Array, BooleanArray, Int64Array, StringArray},
    datatypes::DataType,
};
use parquet::{
    arrow::{
        arrow_reader::{ArrowReaderMetadata, ParquetRecordBatchReaderBuilder},
        ProjectionMask,
    },
    basic::Encoding,
    column::page::{Page, PageReader},
    file::{reader::ChunkReader, serialized_reader::SerializedPageReader},
};
use serde_json::{json, Value};
use std::sync::{atomic::Ordering, Arc};

pub(super) fn decode(
    r: &Request,
    metadata: ArrowReaderMetadata,
    sparse: Sparse,
    budget: &mut super::bounded::Budget,
) -> Result<(Vec<Value>, Vec<Vec<Value>>, usize)> {
    let md = metadata.metadata();
    let sparse = Arc::new(sparse);
    for g in &r.row_groups {
        let group = md.row_group(*g);
        for c in &r.columns {
            let part = r.chunk(*g, *c)?;
            let raw = sparse
                .get_bytes(part.offset, part.length)
                .map_err(|_| invalid())?;
            super::pages::validate(&raw, budget)?;
            let mut pages = SerializedPageReader::new(
                sparse.clone(),
                group.column(*c),
                group.num_rows() as usize,
                None,
            )
            .map_err(|_| invalid())?;
            let mut values = 0u64;
            loop {
                let before = sparse.read_calls.load(Ordering::Relaxed);
                let next = pages.get_next_page().map_err(|_| invalid())?;
                // This locked official reader obtains one get_read per page,
                // but silently skips INDEX_PAGE. Reject those hidden skips,
                // including a trailing/empty index page, without a new parser.
                if sparse.read_calls.load(Ordering::Relaxed) - before != usize::from(next.is_some())
                {
                    return Err(invalid());
                }
                let Some(page) = next else {
                    break;
                };
                let (buf, count) = match &page {
                    Page::DataPage {
                        buf,
                        num_values,
                        encoding: Encoding::PLAIN,
                        def_level_encoding: Encoding::RLE,
                        rep_level_encoding: Encoding::RLE,
                        ..
                    } => (buf, *num_values),
                    Page::DataPageV2 {
                        buf,
                        num_values,
                        encoding: Encoding::PLAIN,
                        num_nulls,
                        num_rows,
                        def_levels_byte_len,
                        rep_levels_byte_len,
                        ..
                    } if num_rows == num_values
                        && num_nulls <= num_values
                        && *rep_levels_byte_len == 0
                        && *def_levels_byte_len as usize <= buf.len() =>
                    {
                        (buf, *num_values)
                    }
                    _ => return Err(invalid()),
                };
                if buf.len() > part.length {
                    return Err(invalid());
                }
                if count == 0 {
                    return Err(invalid());
                }
                values = values.checked_add(count as u64).ok_or_else(invalid)?;
                if values > group.num_rows() as u64 {
                    return Err(invalid());
                }
            }
            if values != group.num_rows() as u64 {
                return Err(invalid());
            }
        }
    }
    // Page buffers above are dropped before Arrow starts. Conservatively charge
    // all inspected page bytes plus every retained Arrow allocation together.
    let columns = r.columns.iter().map(|i| {
        let f = metadata.schema().field(*i);
        json!({"name": f.name(), "type": match f.data_type() { DataType::Int64 => "int8", DataType::Utf8 => "text", _ => "bool" }})
    }).collect();
    let expected_rows: usize = r
        .row_groups
        .iter()
        .map(|g| md.row_group(*g).num_rows() as usize)
        .sum();
    let mask = ProjectionMask::leaves(md.file_metadata().schema_descr(), r.columns.clone());
    let reader = ParquetRecordBatchReaderBuilder::new_with_metadata((*sparse).clone(), metadata)
        .with_projection(mask)
        .with_row_groups(r.row_groups.clone())
        .with_batch_size(200)
        .build()
        .map_err(|_| invalid())?;
    let mut rows = Vec::new();
    for batch in reader {
        let batch = batch.map_err(|_| invalid())?;
        budget.charge(batch.get_array_memory_size())?;
        for row in 0..batch.num_rows() {
            let mut output = Vec::new();
            for array in batch.columns() {
                let value = if array.is_null(row) {
                    Value::Null
                } else {
                    match array.data_type() {
                        DataType::Int64 => json!(array
                            .as_any()
                            .downcast_ref::<Int64Array>()
                            .ok_or_else(invalid)?
                            .value(row)
                            .to_string()),
                        DataType::Utf8 => json!(array
                            .as_any()
                            .downcast_ref::<StringArray>()
                            .ok_or_else(invalid)?
                            .value(row)),
                        DataType::Boolean => json!(array
                            .as_any()
                            .downcast_ref::<BooleanArray>()
                            .ok_or_else(invalid)?
                            .value(row)),
                        _ => return Err(invalid()),
                    }
                };
                output.push(value);
            }
            rows.push(output);
            if rows.len() > expected_rows {
                return Err(invalid());
            }
        }
    }
    if rows.len() != expected_rows {
        return Err(invalid());
    }
    Ok((columns, rows, budget.used()))
}
