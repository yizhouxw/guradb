use super::*;
use bytes::Bytes;

fn dataset() -> Arc<Dataset> {
    Arc::new(Dataset {
        manifest: Manifest {
            schema: vec![
                Column {
                    name: "record_id".into(),
                    r#type: "text".into(),
                },
                Column {
                    name: "rank".into(),
                    r#type: "int8".into(),
                },
                Column {
                    name: "active".into(),
                    r#type: "bool".into(),
                },
            ],
        },
    })
}

#[test]
fn whitelist_retains_projection_filter_order_and_limit() {
    let prepared = sql::prepare("SELECT record_id AS id, rank FROM records WHERE active = true AND rank >= 1 ORDER BY rank DESC LIMIT 2", dataset()).unwrap();
    assert_eq!(prepared.columns.len(), 2);
    assert_eq!(prepared.columns[0].name, "id");
    assert_eq!(prepared.sql_limit, Some(2));
    assert_eq!(prepared.order.len(), 1);
    assert!(prepared.filter.is_some());
}

#[test]
fn unsupported_features_cannot_open_other_sources_or_execute_functions() {
    for statement in [
        "DELETE FROM records",
        "SELECT * FROM other",
        "SELECT count(*) FROM records",
        "SELECT * FROM records JOIN other USING(record_id)",
        "SELECT * FROM records; SELECT * FROM records",
        "SELECT * FROM records LIMIT 1 OFFSET 1",
        "SELECT * FROM records WHERE rank = $1",
        "SELECT rank + 1 FROM records",
        "SELECT * FROM records GROUP BY record_id",
        "SELECT DISTINCT record_id FROM records",
        "SELECT * FROM records WHERE active = 'true'",
        "SELECT * FROM records WHERE rank = (SELECT 1)",
    ] {
        assert!(
            sql::prepare(statement, dataset()).is_err(),
            "accepted {statement}"
        );
    }
}

#[test]
fn corruption_is_rejected_before_engine() {
    assert!(source::decode(Bytes::from_static(b"not parquet")).is_err());
    assert!(source::decode(Bytes::new()).is_err());
}

#[test]
fn config_rejects_unused_platform_fields_and_invalid_json() {
    assert!(
        serde_json::from_str::<Config>(r#"{"source":"x","sha256":"y","pg_listen":"x"}"#).is_err()
    );
    assert!(serde_json::from_str::<Config>("{}").is_err());
}
