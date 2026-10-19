use super::*;
use crate::fixture::{Fixture, DATASET};
use guradb_common::protocol::QueryRequest;
use serde_json::json;
fn request(sql: &str, parameters: Vec<Value>) -> QueryRequest {
    serde_json::from_value(json!({"sql":sql,"parameters":parameters})).unwrap()
}

#[tokio::test]
async fn fixed_parquet_query_truth_and_resource_failures() {
    let fixture = Fixture::new();
    let allowed = [DATASET.into()];
    for (query, expected) in [
        (
            "SELECT * FROM documents ORDER BY id",
            json!([
                ["1", "alpha", true],
                ["2", "数据库", false],
                ["9223372036854775807", null, null]
            ]),
        ),
        (
            "SELECT id AS document_id FROM documents WHERE id <= 2 ORDER BY id DESC LIMIT 1",
            json!([["2"]]),
        ),
        (
            "SELECT id FROM documents WHERE active IS NULL",
            json!([["9223372036854775807"]]),
        ),
    ] {
        let plan = sql::prepare(&request(query, vec![]), &fixture.catalog, &allowed).unwrap();
        let output = execute(plan, &Limits::default(), 100, &CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(serde_json::to_value(&output.rows).unwrap(), expected);
        assert_eq!(output.stats.source_reads, 1);
    }
    let plan = sql::prepare(
        &request("SELECT * FROM documents", vec![]),
        &fixture.catalog,
        &allowed,
    )
    .unwrap();
    let output = execute(plan, &Limits::default(), 1, &CancellationToken::new())
        .await
        .unwrap();
    assert!(output.truncated);
    assert_eq!(output.rows.len(), 1);
    for limits in [
        Limits {
            scan_bytes: 1,
            ..Limits::default()
        },
        Limits {
            decoded_bytes: 1,
            ..Limits::default()
        },
        Limits {
            result_bytes: 1,
            ..Limits::default()
        },
        Limits {
            pool_bytes: 1,
            ..Limits::default()
        },
    ] {
        let plan = sql::prepare(
            &request("SELECT * FROM documents ORDER BY id", vec![]),
            &fixture.catalog,
            &allowed,
        )
        .unwrap();
        let error = execute(plan, &limits, 100, &CancellationToken::new())
            .await
            .err()
            .unwrap();
        assert_eq!(error.code, "resource_limit");
    }
    let cancel = CancellationToken::new();
    cancel.cancel();
    let plan = sql::prepare(
        &request("SELECT * FROM documents", vec![]),
        &fixture.catalog,
        &allowed,
    )
    .unwrap();
    assert_eq!(
        execute(plan, &Limits::default(), 100, &cancel)
            .await
            .err()
            .unwrap()
            .code,
        "cancelled"
    );
    assert_eq!(
        engine_error(datafusion::error::DataFusionError::Plan("invalid".into())).code,
        "execution_failed"
    );
}

#[test]
fn sql_positive_parameters_and_negative_whitelist() {
    let fixture = Fixture::new();
    let allowed = [DATASET.into()];
    for (sql, parameters) in [
        ("SELECT id FROM documents WHERE id = $1", vec![json!({"type":"int8","value":"9223372036854775807"})]),
        ("SELECT title FROM documents WHERE title = $1", vec![json!("a")]),
        ("SELECT active FROM documents WHERE active = $1", vec![json!(true)]),
        ("SELECT id FROM documents WHERE id = $1", vec![Value::Null]),
        ("SELECT id FROM documents WHERE id = $1", vec![json!(1)]),
        ("SELECT id FROM documents WHERE (id != -2 OR id <= 1) AND id >= 0 AND title IS NOT NULL AND NOT active", vec![])] {
        assert!(sql::prepare(&request(sql, parameters), &fixture.catalog, &allowed).is_ok(),"{sql}");
    }
    for sql in [
        "",
        "SELECT",
        "SELECT 1",
        "BEGIN",
        "SELECT * FROM documents; SELECT * FROM documents",
        "SELECT * FROM documents FOR UPDATE",
        "WITH x AS (SELECT * FROM documents) SELECT * FROM x",
        "SELECT id FROM documents UNION SELECT id FROM documents",
        "SELECT * FROM documents d",
        "SELECT * FROM read_parquet('x')",
        "SELECT * FROM public.documents",
        "SELECT * FROM missing",
        "SELECT DISTINCT id FROM documents",
        "SELECT *, id FROM documents",
        "SELECT id, id FROM documents",
        "SELECT documents.* FROM documents",
        "SELECT id + 1 FROM documents",
        "SELECT id FROM documents WHERE id",
        "SELECT id FROM documents ORDER BY random()",
        "SELECT id FROM documents LIMIT 'x'",
        "SELECT id FROM documents OFFSET 1",
        "SELECT id FROM documents WHERE NOT id",
        "SELECT id FROM documents WHERE -id > 1",
        "SELECT id FROM documents WHERE id = '1'",
        "SELECT id FROM documents WHERE id AND active",
        "SELECT id FROM documents WHERE id + 1 = 2",
        "SELECT id FROM documents WHERE id IN (1,2)",
        "SELECT id FROM documents WHERE id = $0",
        "SELECT id FROM documents WHERE id = $1",
        "SELECT id FROM documents WHERE id = 9223372036854775808",
        "SELECT id FROM documents WHERE id = -9223372036854775809",
        "SELECT id FROM documents WHERE id = 1.5",
        "SELECT \"Bad\" FROM documents",
    ] {
        assert!(
            sql::prepare(&request(sql, vec![]), &fixture.catalog, &allowed).is_err(),
            "{sql}"
        );
    }
    for value in [
        json!(1.5),
        json!(9007199254740992_u64),
        json!([]),
        json!({}),
        json!({"type":"int8","value":"01"}),
        json!({"type":"int8","value":"9223372036854775808"}),
        json!({"type":"int8","value":1}),
    ] {
        assert!(sql::prepare(
            &request("SELECT id FROM documents WHERE id = $1", vec![value]),
            &fixture.catalog,
            &allowed
        )
        .is_err());
    }
    let mut req = request("SELECT id FROM documents", vec![]);
    req.read_view_id = Some("wrong".into());
    assert_eq!(
        sql::prepare(&req, &fixture.catalog, &allowed)
            .err()
            .unwrap()
            .code,
        "view_unavailable"
    );
    req.read_view_id = None;
    req.parameters = vec![json!(1)];
    assert_eq!(
        sql::prepare(&req, &fixture.catalog, &allowed)
            .err()
            .unwrap()
            .code,
        "invalid_parameter"
    );
}

#[tokio::test]
async fn empty_fact_manifest_and_result_growth_budget() {
    let mut fixture = Fixture::new();
    let ds = Arc::get_mut(fixture.catalog.get_mut("documents").unwrap()).unwrap();
    ds.manifest.files.clear();
    let plan = sql::prepare(
        &request("SELECT * FROM documents", vec![]),
        &fixture.catalog,
        &[DATASET.into()],
    )
    .unwrap();
    assert!(
        execute(plan, &Limits::default(), 100, &CancellationToken::new())
            .await
            .unwrap()
            .rows
            .is_empty()
    );
    let fixture = Fixture::new();
    let plan = sql::prepare(
        &request("SELECT * FROM documents", vec![]),
        &fixture.catalog,
        &[DATASET.into()],
    )
    .unwrap();
    // First-page metadata fits; a later row crosses the result budget.
    let limits = Limits {
        result_bytes: 4220,
        ..Limits::default()
    };
    assert_eq!(
        execute(plan, &limits, 100, &CancellationToken::new())
            .await
            .err()
            .unwrap()
            .code,
        "resource_limit"
    );
}
