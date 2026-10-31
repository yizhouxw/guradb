use super::{
    metadata, reader,
    request::{Chunk, Range, Request},
    sparse::Sparse,
};
use arrow::{
    array::{BooleanArray, Int64Array, StringArray},
    datatypes::{DataType, Field, Schema},
    record_batch::RecordBatch,
};
use bytes::Bytes;
use parquet::{
    arrow::ArrowWriter,
    basic::{Compression, Encoding},
    file::{
        metadata::ParquetMetaData,
        properties::{WriterProperties, WriterVersion},
        reader::ChunkReader,
    },
    thrift::{TCompactOutputProtocol, TSerializable},
};
use sha2::{Digest, Sha256};
use std::{io::Read, sync::Arc};

fn digest(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
fn fixture(version: WriterVersion) -> (Vec<u8>, Request, Arc<ParquetMetaData>) {
    let schema = Arc::new(Schema::new(vec![
        Field::new("id", DataType::Int64, true),
        Field::new("text", DataType::Utf8, true),
        Field::new("flag", DataType::Boolean, true),
    ]));
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(Int64Array::from(vec![
                Some(i64::MIN),
                None,
                Some(i64::MAX),
                Some(0),
            ])),
            Arc::new(StringArray::from(vec![
                Some("snow雪"),
                Some("quote\""),
                None,
                Some(""),
            ])),
            Arc::new(BooleanArray::from(vec![
                Some(true),
                Some(false),
                None,
                Some(true),
            ])),
        ],
    )
    .unwrap();
    let props = WriterProperties::builder()
        .set_dictionary_enabled(false)
        .set_encoding(Encoding::PLAIN)
        .set_compression(Compression::UNCOMPRESSED)
        .set_writer_version(version)
        .set_data_page_row_count_limit(1)
        .set_write_batch_size(1)
        .set_max_row_group_size(2)
        .build();
    let mut bytes = Vec::new();
    let mut writer = ArrowWriter::try_new(&mut bytes, schema, Some(props)).unwrap();
    writer.write(&batch).unwrap();
    writer.close().unwrap();
    let builder = parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder::try_new(
        Bytes::from(bytes.clone()),
    )
    .unwrap();
    let md = builder.metadata().clone();
    let footer_len = u32::from_le_bytes(bytes[bytes.len() - 8..bytes.len() - 4].try_into().unwrap())
        as usize
        + 8;
    let part = |offset: usize, length: usize| Range {
        offset: offset as u64,
        length,
        sha256: digest(&bytes[offset..offset + length]),
    };
    let mut chunks = Vec::new();
    for (g, group) in md.row_groups().iter().enumerate() {
        for (c, col) in group.columns().iter().enumerate() {
            let (offset, length) = col.byte_range();
            chunks.push(Chunk {
                row_group: g,
                column: c,
                offset,
                length: length as usize,
                sha256: digest(&bytes[offset as usize..(offset + length) as usize]),
            });
        }
    }
    let request = Request {
        version: 1,
        origin: "http://127.0.0.1:38081".into(),
        object_key: "a/b.parquet".into(),
        etag: "\"v1\"".into(),
        object_bytes: bytes.len() as u64,
        source_sha256_provenance: digest(&bytes),
        header: part(0, 4),
        footer: part(bytes.len() - footer_len, footer_len),
        chunks,
        columns: vec![0, 1, 2],
        row_groups: vec![0, 1],
    };
    (bytes, request, md)
}
fn sparse(bytes: &[u8], r: &Request) -> Sparse {
    Sparse {
        length: bytes.len() as u64,
        segments: r
            .chunks
            .iter()
            .filter(|c| r.row_groups.contains(&c.row_group) && r.columns.contains(&c.column))
            .map(|c| {
                (
                    c.offset,
                    Bytes::copy_from_slice(&bytes[c.offset as usize..c.offset as usize + c.length]),
                )
            })
            .collect(),
        read_calls: Default::default(),
    }
}
#[test]
fn sparse_never_supplies_a_hole_or_crosses_one_during_later_reads() {
    let source = Sparse {
        length: 1000,
        segments: vec![
            (4, Bytes::from_static(b"abc")),
            (10, Bytes::from_static(b"xyz")),
        ],
        read_calls: Default::default(),
    };
    assert!(source.get_read(0).is_err());
    assert!(source.get_bytes(5, 3).is_err());
    assert!(source.get_bytes(u64::MAX, 1).is_err());
    assert!(source.get_bytes(4, usize::MAX).is_err());
    let mut stream = source.get_read(5).unwrap();
    let mut tail = [0; 2];
    stream.read_exact(&mut tail).unwrap();
    assert_eq!(&tail, b"bc");
    assert_eq!(
        stream.read(&mut [0]).unwrap_err().kind(),
        std::io::ErrorKind::UnexpectedEof
    );
    assert_eq!(source.get_bytes(10, 3).unwrap().as_ref(), b"xyz");
}
#[test]
fn real_v1_v2_pages_project_nullable_scalars_and_extremes_in_source_order() {
    for version in [WriterVersion::PARQUET_1_0, WriterVersion::PARQUET_2_0] {
        let (bytes, mut r, original) = fixture(version);
        // Verify the fixture really contains the two promised page formats,
        // rather than treating a writer property as format evidence.
        use parquet::{column::page::PageReader, file::serialized_reader::SerializedPageReader};
        let mut pages = SerializedPageReader::new(
            Arc::new(sparse(&bytes, &r)),
            original.row_group(0).column(0),
            2,
            None,
        )
        .unwrap();
        let page_type = pages.get_next_page().unwrap().unwrap().page_type();
        assert_eq!(
            page_type,
            match version {
                WriterVersion::PARQUET_1_0 => parquet::basic::PageType::DATA_PAGE,
                WriterVersion::PARQUET_2_0 => parquet::basic::PageType::DATA_PAGE_V2,
            }
        );
        r.columns = vec![0, 2];
        r.row_groups = vec![0, 1];
        r.validate().unwrap();
        let md = metadata::parse(
            &r,
            &bytes[r.footer.offset as usize..],
            &mut Default::default(),
        )
        .unwrap();
        let (_, rows, charged) =
            reader::decode(&r, md, sparse(&bytes, &r), &mut Default::default()).unwrap();
        assert_eq!(
            rows,
            serde_json::from_value::<Vec<Vec<serde_json::Value>>>(serde_json::json!([
                [i64::MIN.to_string(), true],
                [null, false],
                [i64::MAX.to_string(), null],
                ["0", true]
            ]))
            .unwrap()
        );
        assert!(charged > 0 && charged < crate::DECODE_LIMIT);
        // Dropping one selected segment cannot trigger a whole-buffer fallback.
        let mut missing = sparse(&bytes, &r);
        missing.segments.pop();
        let md = metadata::parse(
            &r,
            &bytes[r.footer.offset as usize..],
            &mut Default::default(),
        )
        .unwrap();
        assert_eq!(
            reader::decode(&r, md, missing, &mut Default::default())
                .unwrap_err()
                .code,
            "invalid_parquet_read"
        );
    }
}
#[test]
fn all_descriptors_and_all_footer_columns_are_required_even_when_unselected() {
    let (bytes, mut r, _) = fixture(WriterVersion::PARQUET_1_0);
    r.columns = vec![0];
    r.row_groups = vec![0];
    r.chunks.last_mut().unwrap().length -= 1;
    r.validate().unwrap();
    assert!(metadata::parse(
        &r,
        &bytes[r.footer.offset as usize..],
        &mut Default::default()
    )
    .is_err());
    r.chunks.pop();
    assert!(metadata::parse(
        &r,
        &bytes[r.footer.offset as usize..],
        &mut Default::default()
    )
    .is_err());
}
#[test]
fn strict_selection_overlap_and_planned_transfer_budget_fail_before_io() {
    let (_, mut r, _) = fixture(WriterVersion::PARQUET_1_0);
    for indices in [vec![], vec![0, 0], vec![1, 0], vec![8], vec![0, 1, 2, 3]] {
        r.columns = indices;
        assert!(r.validate().is_err());
    }
    r.columns = vec![0, 1, 2];
    r.chunks[1].offset = r.chunks[0].offset;
    assert!(r.validate().is_err());
    let (_, mut r, _) = fixture(WriterVersion::PARQUET_1_0);
    r.object_bytes = 700000;
    r.footer.offset = 699000;
    r.footer.length = 1000;
    for (i, c) in r.chunks.iter_mut().enumerate() {
        c.offset = 4 + i as u64 * 100000;
        c.length = 100000;
    }
    assert_eq!(r.validate().unwrap_err().code, "resource_limit");
}
#[test]
fn index_pages_that_the_official_reader_normally_skips_are_rejected() {
    use parquet::{
        column::page::PageReader,
        file::{reader::Length, serialized_reader::SerializedPageReader},
    };
    use std::sync::Mutex;
    struct Traced {
        inner: Sparse,
        starts: Arc<Mutex<Vec<u64>>>,
    }
    impl Length for Traced {
        fn len(&self) -> u64 {
            self.inner.len()
        }
    }
    impl ChunkReader for Traced {
        type T = super::sparse::SliceRead;
        fn get_read(&self, start: u64) -> parquet::errors::Result<Self::T> {
            self.starts.lock().unwrap().push(start);
            self.inner.get_read(start)
        }
        fn get_bytes(&self, start: u64, length: usize) -> parquet::errors::Result<Bytes> {
            self.inner.get_bytes(start, length)
        }
    }
    let (bytes, mut r, md) = fixture(WriterVersion::PARQUET_1_0);
    r.columns = vec![0];
    r.row_groups = vec![0];
    let old = md.row_group(0).column(0);
    let starts = Arc::new(Mutex::new(Vec::new()));
    let traced = Arc::new(Traced {
        inner: sparse(&bytes, &r),
        starts: starts.clone(),
    });
    let mut pages = SerializedPageReader::new(traced, old, 2, None).unwrap();
    while pages.get_next_page().unwrap().is_some() {}
    let starts = starts.lock().unwrap();
    assert_eq!(starts.len(), 2);
    let between = (starts[1] - old.data_page_offset() as u64) as usize;
    let original = &bytes[old.data_page_offset() as usize
        ..(old.data_page_offset() + old.compressed_size()) as usize];
    let header = parquet::format::PageHeader {
        type_: parquet::format::PageType::INDEX_PAGE,
        uncompressed_page_size: 0,
        compressed_page_size: 0,
        crc: None,
        data_page_header: None,
        index_page_header: None,
        dictionary_page_header: None,
        data_page_header_v2: None,
    };
    let mut encoded = Vec::new();
    header
        .write_to_out_protocol(&mut TCompactOutputProtocol::new(&mut encoded))
        .unwrap();
    for position in [0, between, original.len()] {
        let mut chunk = original[..position].to_vec();
        chunk.extend_from_slice(&encoded);
        chunk.extend_from_slice(&original[position..]);
        let column = old
            .clone()
            .into_builder()
            .set_total_compressed_size(chunk.len() as i64)
            .set_total_uncompressed_size(chunk.len() as i64)
            .build()
            .unwrap();
        let sparse = Sparse {
            length: r.object_bytes,
            segments: vec![(old.data_page_offset() as u64, Bytes::from(chunk))],
            read_calls: Default::default(),
        };
        // Demonstrate that the official API really accepts this INDEX page;
        // our stricter wrapper must reject it at front, middle, and tail.
        let mut official =
            SerializedPageReader::new(Arc::new(sparse.clone()), &column, 2, None).unwrap();
        let mut values = 0;
        while let Some(page) = official.get_next_page().unwrap() {
            values += page.num_values();
        }
        assert_eq!(values, 2);
        let group = md
            .row_group(0)
            .clone()
            .into_builder()
            .set_column_metadata(vec![
                column,
                md.row_group(0).column(1).clone(),
                md.row_group(0).column(2).clone(),
            ])
            .build()
            .unwrap();
        let adjusted = md
            .as_ref()
            .clone()
            .into_builder()
            .set_row_groups(vec![group, md.row_group(1).clone()])
            .build();
        let metadata = parquet::arrow::arrow_reader::ArrowReaderMetadata::try_new(
            Arc::new(adjusted),
            Default::default(),
        )
        .unwrap();
        assert_eq!(
            reader::decode(&r, metadata, sparse, &mut Default::default())
                .unwrap_err()
                .code,
            "invalid_parquet_read"
        );
    }
}

#[test]
fn hostile_page_statistics_lengths_reject_before_the_allocating_official_reader() {
    let (bytes, mut r, md) = fixture(WriterVersion::PARQUET_1_0);
    r.columns = vec![0];
    r.row_groups = vec![0];
    // A concrete V1 PageHeader with a Statistics.max binary length u32::MAX.
    // There is no matching allocation or giant fixture: only this small header.
    let hostile = vec![
        0x15, 0, 0x15, 0, 0x15, 0, 0x2c, 0x15, 2, 0x15, 0, 0x15, 6, 0x15, 6, 0x1c, 0x18, 0xff,
        0xff, 0xff, 0xff, 0x0f, 0, 0, 0,
    ];
    r.chunks[0].length = hostile.len();
    let mut source = sparse(&bytes, &r);
    source.segments[0].1 = Bytes::from(hostile);
    let calls = source.read_calls.clone();
    let metadata =
        parquet::arrow::arrow_reader::ArrowReaderMetadata::try_new(md, Default::default()).unwrap();
    assert_eq!(
        reader::decode(&r, metadata, source, &mut Default::default())
            .unwrap_err()
            .code,
        "invalid_parquet_read"
    );
    assert_eq!(
        calls.load(std::sync::atomic::Ordering::Relaxed),
        0,
        "official allocating page parser must never be invoked"
    );
}

#[test]
fn raw_footer_fields_lost_by_conversion_are_rejected_for_unselected_columns() {
    let (bytes, mut request, _) = fixture(WriterVersion::PARQUET_1_0);
    request.columns = vec![1];
    request.row_groups = vec![0];
    let start = request.footer.offset as usize;
    let metadata_bytes = &bytes[start..bytes.len() - 8];
    let (original, _) = super::bounded::parse::<parquet::format::FileMetaData>(
        metadata_bytes,
        &mut Default::default(),
    )
    .unwrap();
    for case in 0..4 {
        let mut raw = original.clone();
        match case {
            0 => {
                raw.row_groups[0].columns[0]
                    .meta_data
                    .as_mut()
                    .unwrap()
                    .type_ = parquet::format::Type::BYTE_ARRAY
            }
            1 => raw.row_groups[0].columns[0].encrypted_column_metadata = Some(vec![1]),
            2 => raw.footer_signing_key_metadata = Some(vec![1]),
            _ => raw.schema[0].type_ = Some(parquet::format::Type::INT64),
        }
        let mut footer = Vec::new();
        raw.write_to_out_protocol(&mut TCompactOutputProtocol::new(&mut footer))
            .unwrap();
        let length = footer.len() as u32;
        footer.extend(length.to_le_bytes());
        footer.extend(b"PAR1");
        assert_eq!(
            metadata::parse(&request, &footer, &mut Default::default())
                .err()
                .unwrap()
                .code,
            "invalid_parquet_read"
        );
    }
}
