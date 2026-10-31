use super::{invalid, limit, request::Request};
use crate::Result;
use arrow::datatypes::DataType;
use parquet::{
    arrow::arrow_reader::{ArrowReaderMetadata, ArrowReaderOptions},
    basic::{Compression, Encoding},
    file::metadata::ParquetMetaDataReader,
};
use std::{collections::BTreeSet, sync::Arc};

pub(super) fn parse(
    r: &Request,
    footer: &[u8],
    budget: &mut super::bounded::Budget,
) -> Result<ArrowReaderMetadata> {
    if footer.len() < 9 || &footer[footer.len() - 4..] != b"PAR1" {
        return Err(invalid());
    }
    let n = u32::from_le_bytes(
        footer[footer.len() - 8..footer.len() - 4]
            .try_into()
            .map_err(|_| invalid())?,
    ) as usize;
    if n.checked_add(8) != Some(footer.len()) {
        return Err(invalid());
    }
    super::bounded::footer(&footer[..n], budget)?;
    let md = ParquetMetaDataReader::decode_metadata(&footer[..n]).map_err(|_| invalid())?;
    let file = md.file_metadata();
    let desc = file.schema_descr();
    let fields = desc.root_schema().get_fields();
    if !matches!(file.version(), 1 | 2)
        || !(1..=200).contains(&file.num_rows())
        || !(1..=4).contains(&md.num_row_groups())
        || fields.is_empty()
        || fields.len() > 8
        || desc.num_columns() != fields.len()
        || fields.iter().any(|f| !f.is_primitive())
        || desc
            .columns()
            .iter()
            .any(|c| c.max_rep_level() != 0 || c.max_def_level() > 1)
    {
        return Err(invalid());
    }
    let mut names = BTreeSet::new();
    for f in fields {
        let name = f.name();
        if name.is_empty()
            || name.len() > 128
            || !names.insert(name)
            || !name
                .bytes()
                .enumerate()
                .all(|(i, b)| b == b'_' || b.is_ascii_alphabetic() || (i > 0 && b.is_ascii_digit()))
        {
            return Err(invalid());
        }
    }
    if r.chunks.len() != md.num_row_groups() * fields.len()
        || r.columns.iter().any(|c| *c >= fields.len())
        || r.row_groups.iter().any(|g| *g >= md.num_row_groups())
    {
        return Err(invalid());
    }
    let mut rows = 0i64;
    let mut declared = 0usize;
    for (g, group) in md.row_groups().iter().enumerate() {
        if group.num_rows() <= 0 || group.num_rows() > 200 || group.num_columns() != fields.len() {
            return Err(invalid());
        }
        rows = rows.checked_add(group.num_rows()).ok_or_else(invalid)?;
        let before_group = declared;
        for (c, column) in group.columns().iter().enumerate() {
            let expected = r.chunk(g, c)?;
            if column.file_path().is_some()
                || column.compression() != Compression::UNCOMPRESSED
                || column.dictionary_page_offset().is_some()
                || column.index_page_offset().is_some()
                || column.encodings().is_empty()
                || column
                    .encodings()
                    .iter()
                    .any(|e| !matches!(e, Encoding::PLAIN | Encoding::RLE))
                || column.num_values() != group.num_rows()
                || column.data_page_offset() < 4
                || column.compressed_size() <= 0
                || column.uncompressed_size() != column.compressed_size()
                || column.data_page_offset() as u64 != expected.offset
                || column.compressed_size() as u64 != expected.length as u64
            {
                return Err(invalid());
            }
            declared = declared
                .checked_add(usize::try_from(column.uncompressed_size()).map_err(|_| invalid())?)
                .ok_or_else(limit)?;
            if declared > crate::DECODE_LIMIT {
                return Err(limit());
            }
        }
        if group.total_byte_size() < 0
            || group.total_byte_size() as u64 != (declared - before_group) as u64
        {
            return Err(invalid());
        }
    }
    if rows != file.num_rows() {
        return Err(invalid());
    }
    let metadata = ArrowReaderMetadata::try_new(
        Arc::new(md),
        ArrowReaderOptions::new().with_skip_arrow_metadata(true),
    )
    .map_err(|_| invalid())?;
    if metadata.schema().fields().iter().any(|f| {
        !matches!(
            f.data_type(),
            DataType::Int64 | DataType::Utf8 | DataType::Boolean
        )
    }) {
        return Err(invalid());
    }
    Ok(metadata)
}
