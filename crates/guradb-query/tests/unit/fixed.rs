use arrow::{
    array::StringArray,
    datatypes::{DataType, Field, Schema},
    record_batch::RecordBatch,
};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

fn batch(values: Vec<Option<&str>>) -> RecordBatch {
    let schema = Arc::new(Schema::new(vec![Field::new(
        "record_id",
        DataType::Utf8,
        false,
    )]));
    RecordBatch::try_new(schema, vec![Arc::new(StringArray::from(values))]).unwrap()
}

#[tokio::test]
async fn identity_is_global_not_projected_or_physical() {
    let cancel = CancellationToken::new();
    super::validate_records(
        &[
            batch(vec![Some("a"), Some("数据库")]),
            batch(vec![Some("b")]),
        ],
        1024,
        &cancel,
    )
    .await
    .unwrap();
    for batches in [
        vec![batch(vec![Some("a")]), batch(vec![Some("a")])],
        vec![batch(vec![Some("")])],
    ] {
        assert_eq!(
            super::validate_records(&batches, 1024, &cancel)
                .await
                .unwrap_err()
                .code,
            "source_invalid"
        );
    }
    assert_eq!(
        super::validate_records(&[batch(vec![Some("a")])], 1, &cancel)
            .await
            .unwrap_err()
            .code,
        "resource_limit"
    );
    cancel.cancel();
    assert_eq!(
        super::validate_records(&[batch(vec![Some("a")])], 1024, &cancel)
            .await
            .unwrap_err()
            .code,
        "cancelled"
    );
}

#[test]
fn explicit_version_and_identity_schema_required() {
    let fixture = crate::fixture::Fixture::new();
    let data = fixture.catalog.get("documents").unwrap();
    let mut request = guradb_common::protocol::FixedQueryRequest {
        dataset_id: crate::fixture::DATASET.into(),
        data_revision_id: data.context.data_revision_id.clone(),
        read_view_id: "view".into(),
        sql: "SELECT id FROM documents".into(),
        parameters: vec![],
        timeout_ms: None,
        max_rows: None,
    };
    let allowed = vec![crate::fixture::DATASET.into()];
    assert_eq!(
        super::prepare(&request, &fixture.catalog, &[])
            .err()
            .unwrap()
            .code,
        "not_found"
    );
    request.data_revision_id = "latest".into();
    assert_eq!(
        super::prepare(&request, &fixture.catalog, &allowed)
            .err()
            .unwrap()
            .code,
        "view_unavailable"
    );
    request.data_revision_id = data.context.data_revision_id.clone();
    assert_eq!(
        super::prepare(&request, &fixture.catalog, &allowed)
            .err()
            .unwrap()
            .code,
        "unsupported"
    );
}
