use super::*;
use arrow::array::{ArrayRef, BooleanArray, Int64Array, StringArray};
use parquet::arrow::ArrowWriter;

#[tokio::test]
async fn parquet_truth_schema_cancellation_and_budgets() {
    let expected = Arc::new(Schema::new(vec![
        Field::new("id", DataType::Int64, false),
        Field::new("title", DataType::Utf8, true),
        Field::new("active", DataType::Boolean, true),
    ]));
    let arrays: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from(vec![1, i64::MAX])),
        Arc::new(StringArray::from(vec![Some("数据库"), None])),
        Arc::new(BooleanArray::from(vec![Some(true), None])),
    ];
    let batch = RecordBatch::try_new(expected.clone(), arrays).unwrap();
    let mut raw = Vec::new();
    let mut writer = ArrowWriter::try_new(&mut raw, expected.clone(), None).unwrap();
    writer.write(&batch).unwrap();
    writer.close().unwrap();
    let bytes = Bytes::from(raw);
    let cancel = CancellationToken::new();
    let (decoded, size) = decode(bytes.clone(), &expected, 1 << 20, &cancel)
        .await
        .unwrap();
    assert_eq!(decoded[0], batch);
    assert!(size > 0);
    assert_eq!(
        decode(bytes.clone(), &expected, 1, &cancel)
            .await
            .unwrap_err()
            .code,
        "resource_limit"
    );
    let wrong = Arc::new(Schema::new(vec![Field::new("id", DataType::Utf8, true)]));
    assert_eq!(
        decode(bytes.clone(), &wrong, 1 << 20, &cancel)
            .await
            .unwrap_err()
            .code,
        "source_invalid"
    );
    let metadata = ParquetRecordBatchReaderBuilder::try_new(bytes.clone()).unwrap();
    let declared = metadata
        .metadata()
        .row_groups()
        .iter()
        .flat_map(|r| r.columns())
        .map(|c| c.uncompressed_size() as usize)
        .sum::<usize>();
    let result = decode(
        bytes.clone(),
        &expected,
        declared + 1,
        &CancellationToken::new(),
    )
    .await;
    assert!(result.is_err());
    let (offset, size) = metadata.metadata().row_group(0).column(0).byte_range();
    let mut damaged = bytes.to_vec();
    damaged[offset as usize..(offset + size) as usize].fill(0);
    assert!(decode(
        Bytes::from(damaged),
        &expected,
        1 << 20,
        &CancellationToken::new()
    )
    .await
    .is_err());
    cancel.cancel();
    assert_eq!(
        decode(bytes, &expected, 1 << 20, &cancel)
            .await
            .unwrap_err()
            .code,
        "cancelled"
    );
    assert_eq!(
        decode(
            Bytes::from_static(b"broken"),
            &expected,
            1 << 20,
            &CancellationToken::new()
        )
        .await
        .unwrap_err()
        .code,
        "source_invalid"
    );
    let manifest: Manifest = serde_json::from_value(serde_json::json!({"schema_version":1,"dataset_id":"d","table_name":"t","schema":[{"name":"id","data_type":"int8","nullable":false},{"name":"title","data_type":"text","nullable":true},{"name":"active","data_type":"bool","nullable":true}],"backend":{"kind":"local","root":"/tmp"},"files":[],"retention_mode":"best-effort"})).unwrap();
    assert_eq!(schema(&manifest), expected);
}
