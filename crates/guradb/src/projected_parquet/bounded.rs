//! Allocation guard around the existing official Compact protocol. Shared,
//! unbuffered transport makes the pre-allocation peek observe the same bytes.
use crate::Result;
use parquet::thrift::TSerializable;
use std::{
    cell::RefCell,
    io::{self, Cursor, Read},
    rc::Rc,
};
use thrift::protocol::*;
const ITEM_BYTES: usize = 2048;
#[derive(Default)]
pub(super) struct Budget {
    used: usize,
    exceeded: bool,
}
impl Budget {
    pub fn charge(&mut self, bytes: usize) -> Result<()> {
        match self
            .used
            .checked_add(bytes)
            .filter(|n| *n <= crate::DECODE_LIMIT)
        {
            Some(total) => {
                self.used = total;
                Ok(())
            }
            None => {
                self.exceeded = true;
                Err(super::limit())
            }
        }
    }
    pub fn used(&self) -> usize {
        self.used
    }
}
fn invalid() -> thrift::Error {
    thrift::Error::Protocol(thrift::ProtocolError {
        kind: thrift::ProtocolErrorKind::InvalidData,
        message: "invalid bounded Parquet metadata".into(),
    })
}
#[derive(Clone)]
struct Transport<'a>(Rc<RefCell<Cursor<&'a [u8]>>>);
impl Read for Transport<'_> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        self.0.borrow_mut().read(out)
    }
}
struct Bounded<'a, 'b> {
    transport: Transport<'a>,
    inner: TCompactInputProtocol<Transport<'a>>,
    budget: &'b mut Budget,
    depth: usize,
}
impl Bounded<'_, '_> {
    fn allocate(&mut self, bytes: usize) -> thrift::Result<()> {
        self.budget.charge(bytes).map_err(|_| invalid())
    }
    fn enter(&mut self) -> thrift::Result<()> {
        if self.depth >= 32 {
            return Err(invalid());
        }
        self.depth += 1;
        self.allocate(ITEM_BYTES)
    }
    fn leave(&mut self) -> thrift::Result<()> {
        self.depth = self.depth.checked_sub(1).ok_or_else(invalid)?;
        Ok(())
    }
    fn count(&mut self, count: i32, multiplier: usize) -> thrift::Result<()> {
        let count = usize::try_from(count).map_err(|_| invalid())?;
        let items = count.checked_mul(multiplier).ok_or_else(invalid)?;
        let cursor = self.transport.0.borrow();
        let remaining = cursor
            .get_ref()
            .len()
            .saturating_sub(cursor.position() as usize);
        // Each encoded item needs at least one byte, including empty structs.
        if items > remaining {
            return Err(invalid());
        }
        drop(cursor);
        self.allocate(items.checked_mul(ITEM_BYTES).ok_or_else(invalid)?)
    }
    fn binary_length(&self) -> thrift::Result<usize> {
        let cursor = self.transport.0.borrow();
        let raw = cursor.get_ref();
        let start = cursor.position() as usize;
        let mut length = 0u32;
        for i in 0..5 {
            let byte = *raw.get(start + i).ok_or_else(invalid)?;
            if i == 4 && byte & 0xf0 != 0 {
                return Err(invalid());
            }
            length |= ((byte & 127) as u32) << (7 * i);
            if byte & 128 == 0 {
                let length = length as usize;
                if (start + i + 1)
                    .checked_add(length)
                    .is_none_or(|end| end > raw.len())
                {
                    return Err(invalid());
                }
                return Ok(length);
            }
        }
        Err(invalid())
    }
}
impl TInputProtocol for Bounded<'_, '_> {
    fn read_message_begin(&mut self) -> thrift::Result<TMessageIdentifier> {
        Err(invalid())
    }
    fn read_message_end(&mut self) -> thrift::Result<()> {
        Err(invalid())
    }
    fn read_struct_begin(&mut self) -> thrift::Result<Option<TStructIdentifier>> {
        self.enter()?;
        self.inner.read_struct_begin()
    }
    fn read_struct_end(&mut self) -> thrift::Result<()> {
        self.inner.read_struct_end()?;
        self.leave()
    }
    fn read_field_begin(&mut self) -> thrift::Result<TFieldIdentifier> {
        self.allocate(32)?;
        self.inner.read_field_begin()
    }
    fn read_field_end(&mut self) -> thrift::Result<()> {
        self.inner.read_field_end()
    }
    fn read_bool(&mut self) -> thrift::Result<bool> {
        self.inner.read_bool()
    }
    fn read_bytes(&mut self) -> thrift::Result<Vec<u8>> {
        let length = self.binary_length()?;
        self.allocate(length)?;
        self.inner.read_bytes()
    }
    fn read_string(&mut self) -> thrift::Result<String> {
        String::from_utf8(self.read_bytes()?).map_err(|_| invalid())
    }
    fn read_i8(&mut self) -> thrift::Result<i8> {
        self.inner.read_i8()
    }
    fn read_i16(&mut self) -> thrift::Result<i16> {
        self.inner.read_i16()
    }
    fn read_i32(&mut self) -> thrift::Result<i32> {
        self.inner.read_i32()
    }
    fn read_i64(&mut self) -> thrift::Result<i64> {
        self.inner.read_i64()
    }
    fn read_double(&mut self) -> thrift::Result<f64> {
        self.inner.read_double()
    }
    fn read_byte(&mut self) -> thrift::Result<u8> {
        self.inner.read_byte()
    }
    fn read_list_begin(&mut self) -> thrift::Result<TListIdentifier> {
        let value = self.inner.read_list_begin()?;
        self.count(value.size, 1)?;
        if value.size != 0 && matches!(value.element_type, TType::Stop | TType::Void) {
            return Err(invalid());
        }
        self.enter()?;
        Ok(value)
    }
    fn read_list_end(&mut self) -> thrift::Result<()> {
        self.inner.read_list_end()?;
        self.leave()
    }
    fn read_set_begin(&mut self) -> thrift::Result<TSetIdentifier> {
        let value = self.inner.read_set_begin()?;
        self.count(value.size, 1)?;
        if value.size != 0 && matches!(value.element_type, TType::Stop | TType::Void) {
            return Err(invalid());
        }
        self.enter()?;
        Ok(value)
    }
    fn read_set_end(&mut self) -> thrift::Result<()> {
        self.inner.read_set_end()?;
        self.leave()
    }
    fn read_map_begin(&mut self) -> thrift::Result<TMapIdentifier> {
        let value = self.inner.read_map_begin()?;
        self.count(value.size, 2)?;
        if value.size != 0
            && (value
                .key_type
                .is_none_or(|t| matches!(t, TType::Stop | TType::Void))
                || value
                    .value_type
                    .is_none_or(|t| matches!(t, TType::Stop | TType::Void)))
        {
            return Err(invalid());
        }
        self.enter()?;
        Ok(value)
    }
    fn read_map_end(&mut self) -> thrift::Result<()> {
        self.inner.read_map_end()?;
        self.leave()
    }
    // Do not delegate skip: the trait defaults recurse through Self, retaining
    // all string, binary, container and depth checks for unknown fields too.
}
pub(super) fn parse<T: TSerializable>(raw: &[u8], budget: &mut Budget) -> Result<(T, usize)> {
    let transport = Transport(Rc::new(RefCell::new(Cursor::new(raw))));
    let inner = TCompactInputProtocol::new(transport.clone());
    let mut protocol = Bounded {
        transport: transport.clone(),
        inner,
        budget,
        depth: 0,
    };
    let result = T::read_from_in_protocol(&mut protocol);
    let position = transport.0.borrow().position() as usize;
    if protocol.depth != 0 || result.is_err() {
        return Err(if protocol.budget.exceeded {
            super::limit()
        } else {
            super::invalid()
        });
    }
    Ok((result.map_err(|_| super::invalid())?, position))
}
pub(super) fn footer(raw: &[u8], budget: &mut Budget) -> Result<()> {
    let before = budget.used();
    let (metadata, used) = parse::<parquet::format::FileMetaData>(raw, budget)?;
    if used != raw.len() {
        return Err(super::invalid());
    }
    // The public conversion drops raw encryption fields and uses the schema
    // descriptor for column_type(), so check these before that information is
    // lost. Flat schema shape is also checked before its recursive converter.
    if !(2..=9).contains(&metadata.schema.len())
        || metadata.schema[0].type_.is_some()
        || metadata.schema[0].num_children != Some((metadata.schema.len() - 1) as i32)
        || metadata.schema[1..]
            .iter()
            .any(|f| f.type_.is_none() || f.num_children.is_some_and(|n| n != 0))
        || metadata.encryption_algorithm.is_some()
        || metadata.footer_signing_key_metadata.is_some()
        || metadata.row_groups.iter().any(|group| {
            group.columns.iter().enumerate().any(|(i, column)| {
                column.crypto_metadata.is_some()
                    || column.encrypted_column_metadata.is_some()
                    || column.meta_data.as_ref().is_none_or(|m| {
                        metadata
                            .schema
                            .get(i + 1)
                            .is_none_or(|field| field.type_.as_ref() != Some(&m.type_))
                    })
            })
        })
    {
        return Err(super::invalid());
    }
    drop(metadata);
    // The official conversion will parse the same immutable bytes once more.
    budget.charge(budget.used() - before)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn item_charge_covers_all_generated_footer_container_element_types() {
        use parquet::format::*;
        let sizes = [
            size_of::<SchemaElement>(),
            size_of::<RowGroup>(),
            size_of::<ColumnChunk>(),
            size_of::<ColumnMetaData>(),
            size_of::<KeyValue>(),
            size_of::<PageEncodingStats>(),
            size_of::<SortingColumn>(),
            size_of::<ColumnOrder>(),
            size_of::<PageLocation>(),
        ];
        assert!(sizes.into_iter().all(|size| size <= ITEM_BYTES));
    }
}

#[cfg(test)]
mod adversarial_tests {
    use super::*;
    struct Probe;
    impl TSerializable for Probe {
        fn read_from_in_protocol<T: TInputProtocol>(p: &mut T) -> thrift::Result<Self> {
            p.read_struct_begin()?;
            loop {
                let field = p.read_field_begin()?;
                if field.field_type == TType::Stop {
                    break;
                }
                p.skip(field.field_type)?;
                p.read_field_end()?;
            }
            p.read_struct_end()?;
            Ok(Self)
        }
        fn write_to_out_protocol<T: TOutputProtocol>(&self, _: &mut T) -> thrift::Result<()> {
            Err(invalid())
        }
    }
    #[test]
    fn unknown_field_skip_uses_bounded_strings_containers_and_depth() {
        let mut budget = Budget::default();
        // Unknown short list is legal; default skip traverses wrapper methods.
        assert!(parse::<Probe>(&[0x19, 0x25, 2, 4, 0], &mut budget).is_ok());
        assert!(budget.used() > 2 * ITEM_BYTES);
        for raw in [
            vec![0x18, 0xff, 0xff, 0xff, 0xff, 0x0f, 0],
            vec![0x19, 0xfc, 0xff, 0xff, 0xff, 0xff, 0x07, 0],
            vec![0x1a, 0xfc, 0xff, 0xff, 0xff, 0xff, 0x0f, 0],
            vec![0x1b, 0xff, 0xff, 0xff, 0xff, 0x0f, 0x55, 0],
        ] {
            let mut budget = Budget::default();
            assert!(parse::<Probe>(&raw, &mut budget).is_err());
            assert!(budget.used() < 16384);
        }
        let mut nested = vec![0x1c; 34];
        nested.extend(vec![0; 35]);
        assert!(parse::<Probe>(&nested, &mut Budget::default()).is_err());
    }
    #[test]
    fn footer_huge_negative_and_heap_amplified_counts_fail_before_generated_vec() {
        for ending in [0x07, 0x0f] {
            let raw = [0x15, 2, 0x19, 0xfc, 0xff, 0xff, 0xff, 0xff, ending, 0];
            let mut budget = Budget::default();
            assert!(footer(&raw, &mut budget).is_err());
            assert!(budget.used() < 16384);
        }
        // 40,000 empty encoded structs fit in 40KiB, but their conservative
        // generated-element charge exceeds the shared 64MiB before allocation.
        let mut raw = vec![0x15, 2, 0x19, 0xfc, 0xc0, 0xb8, 2];
        raw.extend(vec![0; 40001]);
        let mut budget = Budget::default();
        let error = footer(&raw, &mut budget).unwrap_err();
        assert_eq!(error.code, "resource_limit");
    }
    #[test]
    fn footer_page_and_arrow_work_share_one_budget_without_phase_reset() {
        let mut budget = Budget::default();
        budget.charge(crate::DECODE_LIMIT - ITEM_BYTES).unwrap();
        assert!(parse::<Probe>(&[0], &mut budget).is_err());
        assert!(budget.exceeded);
    }
}
