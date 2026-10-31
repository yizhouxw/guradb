//! Decode the page header with the official bounded protocol before invoking
//! the allocating serialized reader over exactly these immutable chunk bytes.
use super::{
    bounded::{self, Budget},
    invalid,
};
use crate::Result;
use parquet::format::{PageHeader, PageType};
pub(super) fn validate(raw: &[u8], budget: &mut Budget) -> Result<()> {
    let mut position = 0usize;
    let mut pages = 0;
    while position < raw.len() {
        pages += 1;
        if pages > 200 {
            return Err(invalid());
        }
        let before = budget.used();
        let (header, length) = bounded::parse::<PageHeader>(&raw[position..], budget)?;
        let compressed = usize::try_from(header.compressed_page_size).map_err(|_| invalid())?;
        if header.uncompressed_page_size != header.compressed_page_size
            || compressed > crate::DECODE_LIMIT
        {
            return Err(invalid());
        }
        match header.type_ {
            PageType::DATA_PAGE => {
                if header.data_page_header_v2.is_some()
                    || header.dictionary_page_header.is_some()
                    || header.index_page_header.is_some()
                {
                    return Err(invalid());
                }
                let data = header.data_page_header.as_ref().ok_or_else(invalid)?;
                if !(1..=200).contains(&data.num_values) {
                    return Err(invalid());
                }
            }
            PageType::DATA_PAGE_V2 => {
                if header.data_page_header.is_some()
                    || header.dictionary_page_header.is_some()
                    || header.index_page_header.is_some()
                {
                    return Err(invalid());
                }
                let data = header.data_page_header_v2.as_ref().ok_or_else(invalid)?;
                if !(1..=200).contains(&data.num_values)
                    || data.num_rows != data.num_values
                    || !(0..=data.num_values).contains(&data.num_nulls)
                    || data.repetition_levels_byte_length != 0
                    || data.definition_levels_byte_length < 0
                    || data.definition_levels_byte_length as usize > compressed
                {
                    return Err(invalid());
                }
            }
            _ => return Err(invalid()),
        }
        let allocation = budget.used() - before;
        drop(header);
        budget.charge(allocation)?;
        // Reserve the actual uncompressed buffer before the old parser copies.
        budget.charge(compressed)?;
        position = position
            .checked_add(length)
            .and_then(|p| p.checked_add(compressed))
            .filter(|p| *p <= raw.len())
            .ok_or_else(invalid)?;
    }
    if pages == 0 {
        return Err(invalid());
    }
    Ok(())
}
