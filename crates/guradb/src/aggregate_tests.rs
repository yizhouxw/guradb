use super::*;
use arrow::{
    array::{ArrayRef, BooleanArray, Int64Array, StringArray},
    datatypes::{DataType, Field, Schema, SchemaRef},
    record_batch::RecordBatch,
};
use serde_json::{json, Value};

fn fixture() -> (Arc<Dataset>, SchemaRef, RecordBatch) {
    let fields = [
        ("g", DataType::Utf8, "text"),
        ("n", DataType::Int64, "int8"),
        ("b", DataType::Boolean, "bool"),
        ("t", DataType::Utf8, "text"),
    ];
    let schema = Arc::new(Schema::new(
        fields
            .iter()
            .map(|(name, kind, _)| Field::new(*name, kind.clone(), true))
            .collect::<Vec<_>>(),
    ));
    let dataset = Arc::new(Dataset {
        manifest: Manifest {
            schema: fields
                .iter()
                .map(|(name, _, kind)| Column {
                    name: (*name).into(),
                    r#type: (*kind).into(),
                })
                .collect(),
        },
    });
    let arrays: Vec<ArrayRef> = vec![
        Arc::new(StringArray::from(vec![
            Some("b"),
            Some("a"),
            Some("a"),
            None,
            None,
            Some("b"),
        ])),
        Arc::new(Int64Array::from(vec![
            Some(3),
            Some(2),
            None,
            Some(7),
            None,
            Some(3),
        ])),
        Arc::new(BooleanArray::from(vec![
            Some(true),
            None,
            Some(false),
            Some(true),
            None,
            Some(true),
        ])),
        Arc::new(StringArray::from(vec![
            Some("z"),
            Some("c"),
            None,
            Some("a"),
            None,
            Some("y"),
        ])),
    ];
    let batch = RecordBatch::try_new(schema.clone(), arrays).unwrap();
    (dataset, schema, batch)
}

async fn run(sql: &str, empty: bool) -> Value {
    let (dataset, schema, batch) = fixture();
    let plan = sql::prepare(sql, dataset).unwrap();
    let batches = if empty { Vec::new() } else { vec![batch] };
    let output = execution::execute(plan, schema, batches, "aggregate-test")
        .await
        .unwrap();
    let value: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(value["truncated"], false);
    value
}

#[tokio::test]
async fn global_null_counts_min_max_and_filter_use_all_rows() {
    let value = run("SELECT COUNT(*), COUNT(n) AS present, COUNT(b) AS flags, MIN(n), MAX(n), MIN(t) AS first, MAX(t) AS last FROM records", false).await;
    assert_eq!(value["rows"], json!([["6", "4", "4", "2", "7", "a", "z"]]));
    assert_eq!(
        value["columns"],
        json!([
            {"name":"count","type":"int8"}, {"name":"present","type":"int8"},
            {"name":"flags","type":"int8"}, {"name":"min","type":"int8"},
            {"name":"max","type":"int8"}, {"name":"first","type":"text"},
            {"name":"last","type":"text"}
        ])
    );
    assert_eq!(
        run(
            "SELECT COUNT(*), MIN(n), MAX(t) FROM records WHERE g = 'a' LIMIT 1",
            false
        )
        .await["rows"],
        json!([["2", "2", "c"]])
    );
    assert_eq!(
        run("SELECT COUNT(*) FROM records LIMIT 0", false).await["rows"],
        json!([])
    );
}

#[tokio::test]
async fn empty_global_and_grouped_inputs_have_distinct_semantics() {
    for empty in [true, false] {
        let predicate = if empty { "" } else { " WHERE n < 0" };
        assert_eq!(
            run(
                &format!("SELECT COUNT(*), COUNT(n) AS n, MIN(n), MAX(t) FROM records{predicate}"),
                empty
            )
            .await["rows"],
            json!([["0", "0", null, null]])
        );
        assert_eq!(
            run(
                &format!("SELECT g, COUNT(*) FROM records{predicate} GROUP BY g"),
                empty
            )
            .await["rows"],
            json!([])
        );
    }
    assert_eq!(
        run(
            "SELECT COUNT(n),MIN(n),MAX(t) FROM records WHERE n IS NULL",
            false
        )
        .await["rows"],
        json!([["0", null, null]])
    );
}

#[tokio::test]
async fn grouping_nulls_duplicates_and_unprojected_keys_are_deterministic() {
    assert_eq!(
        run(
            "SELECT g, COUNT(*), COUNT(n) AS present, MIN(n), MAX(t) FROM records GROUP BY g",
            false
        )
        .await["rows"],
        json!([
            ["a", "2", "1", "2", "c"],
            ["b", "2", "2", "3", "z"],
            [null, "2", "1", "7", "a"]
        ])
    );
    assert_eq!(
        run("SELECT COUNT(n) AS c FROM records GROUP BY g", false).await["rows"],
        json!([["1"], ["2"], ["1"]])
    );
    assert_eq!(
        run("SELECT g AS key FROM records GROUP BY g", false).await["rows"],
        json!([["a"], ["b"], [null]])
    );
    assert_eq!(
        run("SELECT b, COUNT(*) FROM records GROUP BY b", false).await["rows"],
        json!([[false, "1"], [true, "3"], [null, "2"]])
    );
    assert_eq!(
        run("SELECT n FROM records GROUP BY n", false).await["rows"],
        json!([["2"], ["3"], ["7"], [null]])
    );
    assert_eq!(
        run(
            "SELECT g AS key, COUNT(n) AS c FROM records GROUP BY g ORDER BY c DESC LIMIT 2",
            false
        )
        .await["rows"],
        json!([["b", "2"], ["a", "1"]])
    );
    assert_eq!(
        run(
            "SELECT g AS key FROM records GROUP BY g ORDER BY key DESC",
            false
        )
        .await["rows"],
        json!([[null], ["b"], ["a"]])
    );
    assert_eq!(
        run(
            "SELECT g AS key FROM records GROUP BY g ORDER BY key DESC NULLS LAST",
            false
        )
        .await["rows"],
        json!([["b"], ["a"], [null]])
    );
}

#[test]
fn every_aggregate_modifier_expression_and_illegal_projection_is_rejected() {
    let (dataset, _, _) = fixture();
    for query in [
        "SELECT COUNT(DISTINCT n) FROM records",
        "SELECT COUNT(ALL n) FROM records",
        "SELECT COUNT(n ORDER BY n) FROM records",
        "SELECT COUNT(*) FILTER (WHERE n > 0) FROM records",
        "SELECT COUNT(*) OVER () FROM records",
        "SELECT COUNT(*) WITHIN GROUP (ORDER BY n) FROM records",
        "SELECT COUNT(n IGNORE NULLS) FROM records",
        "SELECT COUNT(n) IGNORE NULLS FROM records",
        "SELECT COUNT(n) RESPECT NULLS FROM records",
        "SELECT COUNT(x => n) FROM records",
        "SELECT COUNT(n := 1) FROM records",
        "SELECT COUNT(n,n) FROM records",
        "SELECT COUNT() FROM records",
        "SELECT COUNT(1) FROM records",
        "SELECT COUNT(n + 1) FROM records",
        "SELECT COUNT((n)) FROM records",
        "SELECT COUNT(MIN(n)) FROM records",
        "SELECT MIN(*) FROM records",
        "SELECT MAX(b) FROM records",
        "SELECT MIN(b) FROM records",
        "SELECT SUM(n) FROM records",
        "SELECT AVG(n) FROM records",
        "SELECT pg_catalog.count(*) FROM records",
        "SELECT COUNT(records.*) FROM records",
        "SELECT COUNT(n)(n) FROM records",
        "SELECT n, COUNT(*) FROM records",
        "SELECT t, COUNT(*) FROM records GROUP BY g",
        "SELECT COUNT(*),COUNT(n) FROM records",
        "SELECT MIN(n),MIN(t) FROM records",
        "SELECT g AS x,COUNT(*) AS x FROM records GROUP BY g",
        "SELECT * FROM records GROUP BY g",
        "SELECT COUNT(*) FROM records GROUP BY g,n",
        "SELECT COUNT(*) FROM records GROUP BY g || t",
        "SELECT COUNT(*) FROM records GROUP BY ROLLUP(g)",
        "SELECT COUNT(*) FROM records GROUP BY CUBE(g)",
        "SELECT COUNT(*) FROM records GROUP BY GROUPING SETS ((g))",
        "SELECT COUNT(*) FROM records GROUP BY ALL",
        "SELECT COUNT(*) FROM records HAVING COUNT(*) > 0",
        "SELECT DISTINCT COUNT(*) FROM records",
        "SELECT DISTINCT g FROM records GROUP BY g",
        "SELECT COUNT(*) FROM records ORDER BY n",
        "SELECT COUNT(*) FROM records ORDER BY COUNT(*)",
        "SELECT COUNT(*) FROM records ORDER BY 1",
        "SELECT g AS key FROM records GROUP BY g ORDER BY g",
        "SELECT COUNT(missing) FROM records",
        "SELECT COUNT(*) FROM records GROUP BY missing",
        "SELECT COUNT(*) FROM records WHERE COUNT(*) > 0",
    ] {
        assert!(
            sql::prepare(query, dataset.clone()).is_err(),
            "accepted {query}"
        );
    }
}

#[tokio::test]
async fn full_input_budget_is_checked_before_filter_and_limit_only_for_aggregates() {
    let (dataset, schema, batch) = fixture();
    let batches = vec![batch; 34]; // 204 complete input rows, not just filtered rows.
    for query in [
        "SELECT COUNT(*) FROM records",
        "SELECT COUNT(*) FROM records WHERE n < 0 LIMIT 0",
        "SELECT g FROM records GROUP BY g LIMIT 1",
    ] {
        let plan = sql::prepare(query, dataset.clone()).unwrap();
        let error = execution::execute(plan, schema.clone(), batches.clone(), "budget-test")
            .await
            .unwrap_err();
        assert_eq!(error.code, "resource_limit");
    }
    let plan = sql::prepare("SELECT n FROM records LIMIT 1", dataset).unwrap();
    assert!(execution::execute(plan, schema, batches, "scalar-test")
        .await
        .is_ok());
}

#[tokio::test]
async fn two_hundred_groups_and_collision_names_keep_exact_results() {
    let schema = Arc::new(Schema::new(vec![Field::new(
        "__guradb_group",
        DataType::Int64,
        false,
    )]));
    let dataset = Arc::new(Dataset {
        manifest: Manifest {
            schema: vec![Column {
                name: "__guradb_group".into(),
                r#type: "int8".into(),
            }],
        },
    });
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![Arc::new(Int64Array::from(
            (0..200).rev().collect::<Vec<_>>(),
        ))],
    )
    .unwrap();
    let plan = sql::prepare("SELECT __guradb_group AS __guradb_aggregate_0, COUNT(*) AS __guradb_group FROM records GROUP BY __guradb_group ORDER BY __guradb_group DESC", dataset).unwrap();
    let output = execution::execute(plan, schema, vec![batch], "limit-test")
        .await
        .unwrap();
    let value: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(value["rows"].as_array().unwrap().len(), 200);
    assert_eq!(value["rows"][0], json!(["0", "1"]));
    assert_eq!(value["rows"][199], json!(["199", "1"]));
    assert_eq!(value["truncated"], false);
}
