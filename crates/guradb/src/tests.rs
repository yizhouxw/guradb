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
        "SELECT DISTINCT ON (record_id) record_id FROM records",
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

#[test]
fn substring_like_is_a_bounded_typed_literal_whitelist() {
    for keyword in ["kitchen", "O''Brien", "厨房", &"x".repeat(128)] {
        assert!(sql::prepare(
            &format!("SELECT * FROM records WHERE record_id LIKE '%{keyword}%'"),
            dataset()
        )
        .is_ok());
    }
    for predicate in [
        "rank LIKE '%1%'",
        "active LIKE '%true%'",
        "record_id LIKE rank",
        "record_id LIKE 'kitchen'",
        "record_id LIKE '%%'",
        "record_id LIKE '%a_b%'",
        "record_id LIKE '%a%b%'",
        "record_id LIKE '%a\\b%'",
        "record_id NOT LIKE '%a%'",
        "record_id ILIKE '%a%'",
        "record_id LIKE ANY ('%a%')",
        "record_id LIKE '%a%' ESCAPE '!'",
        "record_id LIKE NULL",
        &format!("record_id LIKE '%{}%'", "x".repeat(129)),
        &format!("record_id LIKE '%{}%'", "界".repeat(43)),
    ] {
        assert!(
            sql::prepare(
                &format!("SELECT * FROM records WHERE {predicate}"),
                dataset()
            )
            .is_err(),
            "accepted {predicate}"
        );
    }
}

#[tokio::test]
async fn substring_execution_is_case_sensitive_unicode_literal_and_null_safe() {
    use arrow::{
        array::{BooleanArray, Int64Array, StringArray},
        datatypes::{DataType, Field, Schema},
        record_batch::RecordBatch,
    };
    let schema = Arc::new(Schema::new(vec![
        Field::new("record_id", DataType::Utf8, true),
        Field::new("rank", DataType::Int64, false),
        Field::new("active", DataType::Boolean, false),
    ]));
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![
                Some("厨房x"),
                Some("O'Brien"),
                Some("Kitchen"),
                None,
            ])),
            Arc::new(Int64Array::from(vec![0, 1, 2, 3])),
            Arc::new(BooleanArray::from(vec![true; 4])),
        ],
    )
    .unwrap();
    for (keyword, expected) in [
        ("厨房", vec![vec!["厨房x"]]),
        ("O''Brien", vec![vec!["O'Brien"]]),
        ("kitchen", vec![]),
        ("Kitchen", vec![vec!["Kitchen"]]),
    ] {
        let plan = sql::prepare(
            &format!("SELECT record_id FROM records WHERE record_id LIKE '%{keyword}%'"),
            dataset(),
        )
        .unwrap();
        let output = execution::execute(plan, schema.clone(), vec![batch.clone()], "test-snapshot")
            .await
            .unwrap();
        let value: serde_json::Value = serde_json::from_str(&output).unwrap();
        assert_eq!(value["rows"], serde_json::json!(expected));
    }
}

#[test]
fn distinct_orders_only_projected_outputs_and_rejects_modifiers() {
    for sql in [
        "SELECT DISTINCT record_id FROM records ORDER BY record_id",
        "SELECT DISTINCT rank AS n FROM records ORDER BY n DESC LIMIT 2",
        "SELECT DISTINCT * FROM records ORDER BY active",
    ] {
        assert!(sql::prepare(sql, dataset()).unwrap().distinct);
    }
    for sql in [
        "SELECT DISTINCT rank FROM records ORDER BY active",
        "SELECT DISTINCT rank AS n FROM records ORDER BY rank",
        "SELECT DISTINCT rank FROM records ORDER BY 1",
        "SELECT DISTINCT rank + 1 FROM records",
        "SELECT DISTINCT rank AS n, active AS n FROM records",
        "SELECT DISTINCT ON (rank) rank FROM records ORDER BY rank",
    ] {
        assert!(sql::prepare(sql, dataset()).is_err(), "accepted {sql}");
    }
    assert!(
        !sql::prepare(
            "SELECT rank FROM records ORDER BY active LIMIT 2",
            dataset()
        )
        .unwrap()
        .distinct
    );
}

#[tokio::test]
async fn distinct_tuple_null_types_sort_and_limit_are_real_engine_operations() {
    use arrow::{
        array::{BooleanArray, Int64Array, StringArray},
        datatypes::{DataType, Field, Schema},
        record_batch::RecordBatch,
    };
    let schema = Arc::new(Schema::new(vec![
        Field::new("record_id", DataType::Utf8, true),
        Field::new("rank", DataType::Int64, true),
        Field::new("active", DataType::Boolean, true),
    ]));
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![
                Some("same"),
                Some("same"),
                None,
                None,
                Some(""),
                Some("X"),
                Some("X"),
            ])),
            Arc::new(Int64Array::from(vec![
                Some(1),
                Some(1),
                None,
                None,
                Some(0),
                Some(2),
                Some(2),
            ])),
            Arc::new(BooleanArray::from(vec![
                Some(true),
                Some(true),
                None,
                None,
                Some(false),
                Some(false),
                Some(true),
            ])),
        ],
    )
    .unwrap();
    for (sql, expected) in [
        ("SELECT DISTINCT record_id, rank, active FROM records ORDER BY rank ASC NULLS FIRST, active ASC", serde_json::json!([[null,null,null],["","0",false],["same","1",true],["X","2",false],["X","2",true]])),
        ("SELECT DISTINCT record_id, rank, active FROM records ORDER BY rank ASC NULLS FIRST, active ASC LIMIT 4", serde_json::json!([[null,null,null],["","0",false],["same","1",true],["X","2",false]])),
        ("SELECT DISTINCT active FROM records ORDER BY active DESC NULLS LAST", serde_json::json!([[true],[false],[null]])),
        ("SELECT DISTINCT rank AS n FROM records ORDER BY n DESC NULLS LAST LIMIT 2", serde_json::json!([["2"],["1"]])),
        ("SELECT DISTINCT record_id FROM records LIMIT 0", serde_json::json!([])),
    ] {
        let plan = sql::prepare(sql, dataset()).unwrap();
        let output = execution::execute(plan, schema.clone(), vec![batch.clone()], "distinct-test").await.unwrap();
        let value: serde_json::Value = serde_json::from_str(&output).unwrap();
        assert_eq!(value["rows"], expected, "{sql}");
    }
}
