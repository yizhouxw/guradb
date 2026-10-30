use super::*;
use datafusion::common::ScalarValue;
use serde_json::json;

fn dataset() -> Arc<Dataset> {
    Arc::new(Dataset {
        manifest: Manifest {
            schema: [("n", "int8"), ("t", "text"), ("b", "bool")]
                .into_iter()
                .map(|(name, kind)| Column {
                    name: name.into(),
                    r#type: kind.into(),
                })
                .collect(),
        },
    })
}
fn bind(sql: &str, values: serde_json::Value) -> Result<sql::Prepared> {
    let raw = json!({"version":1,"values":values}).to_string();
    sql::prepare_bound(sql, dataset(), parameters::Bindings::parse(&raw)?)
}
#[test]
fn typed_values_are_canonical_and_null_retains_its_type() {
    let mut bindings = parameters::Bindings::parse(r#"{"version":1,"values":[{"type":"int8","value":"-9223372036854775808"},{"type":"int8","value":"9223372036854775807"},{"type":"text","value":null},{"type":"bool","value":null}]}"#).unwrap();
    assert_eq!(
        bindings.resolve("$1").unwrap().0,
        ScalarValue::Int64(Some(i64::MIN))
    );
    assert_eq!(
        bindings.resolve("$2").unwrap().0,
        ScalarValue::Int64(Some(i64::MAX))
    );
    assert_eq!(
        bindings.resolve("$3").unwrap(),
        (ScalarValue::Utf8(None), "text".into())
    );
    assert_eq!(
        bindings.resolve("$4").unwrap(),
        (ScalarValue::Boolean(None), "bool".into())
    );
    bindings.finish().unwrap();
    for value in [
        "+1",
        "01",
        "-0",
        " 1",
        "9223372036854775808",
        "-9223372036854775809",
    ] {
        let raw = json!({"version":1,"values":[{"type":"int8","value":value}]}).to_string();
        assert!(parameters::Bindings::parse(&raw).is_err());
    }
}
#[test]
fn malformed_duplicate_missing_fields_and_size_reject_without_echo() {
    for raw in [
        "{}",
        r#"{"version":1}"#,
        r#"{"version":true,"values":[]}"#,
        r#"{"version":1.0,"values":[]}"#,
        r#"{"version":2,"values":[]}"#,
        r#"{"version":1,"version":1,"values":[]}"#,
        r#"{"version":1,"values":[],"unknown":0}"#,
        r#"{"version":1,"values":[{"type":"text"}]}"#,
        r#"{"version":1,"values":[{"value":null}]}"#,
        r#"{"version":1,"values":[{"type":"text","value":"SECRET","value":null}]}"#,
        r#"{"version":1,"values":[{"type":"text","value":"SECRET","extra":0}]}"#,
        r#"{"version":1,"values":[{"type":"int8","value":1}]}"#,
        r#"{"version":1,"values":[{"type":"bool","value":"true"}]}"#,
        r#"{"version":1,"values":[{"type":"text","value":false}]}"#,
        r#"{"version":1,"values":[{"type":"float8","value":null}]}"#,
    ] {
        let error = parameters::Bindings::parse(raw)
            .err()
            .expect("accepted malformed parameters");
        assert!(!error.to_string().contains("SECRET"));
    }
    let oversized =
        json!({"version":1,"values":[{"type":"text","value":"雪".repeat(5500)}]}).to_string();
    assert!(oversized.len() > 16384);
    assert!(parameters::Bindings::parse(&oversized).is_err());
    assert!(parameters::Bindings::parse(
        &json!({"version":1,"values":vec![json!({"type":"bool","value":true});17]}).to_string()
    )
    .is_err());
}
#[test]
fn placeholders_are_dense_exact_reusable_and_where_values_only() {
    let one = json!([{"type":"int8","value":"1"}]);
    assert!(bind("SELECT n FROM records WHERE n=$1 OR $1=n", one.clone()).is_ok());
    for query in [
        "SELECT n FROM records WHERE n=$0",
        "SELECT n FROM records WHERE n=$01",
        "SELECT n FROM records WHERE n=$17",
        "SELECT n FROM records WHERE n=$2",
        "SELECT n FROM records",
        "SELECT $1 FROM records",
        "SELECT n FROM records ORDER BY $1",
        "SELECT n FROM records LIMIT $1",
        "SELECT COUNT($1) FROM records",
        "SELECT COUNT(*) FROM records GROUP BY $1",
        "SELECT n FROM records WHERE n=-$1",
        "SELECT n FROM records WHERE n=$1+1",
        "SELECT n FROM records WHERE t=$1",
        "SELECT n FROM records WHERE $1",
    ] {
        assert!(bind(query, one.clone()).is_err(), "accepted {query}");
    }
    assert!(bind(
        "SELECT n FROM records WHERE n=$2",
        json!([{"type":"int8","value":"1"},{"type":"int8","value":"2"}])
    )
    .is_err());
    assert!(bind("SELECT n FROM records WHERE n=$1", json!([])).is_err());
    assert!(bind("SELECT n FROM records WHERE n=1", json!([])).is_ok());
    assert!(bind("SELECT t FROM records WHERE t='$1' -- $2\n", json!([])).is_ok());
    assert!(bind("SELECT n FROM records WHERE n=$1 /* $2 */", one).is_ok());
    let values = vec![json!({"type":"int8","value":"1"}); 16];
    let predicate = (1..=16)
        .map(|n| format!("n=${n}"))
        .collect::<Vec<_>>()
        .join(" OR ");
    assert!(bind(
        &format!("SELECT n FROM records WHERE {predicate}"),
        json!(values)
    )
    .is_ok());
}
#[test]
fn typed_null_boolean_and_like_preserve_original_type_and_pattern_guards() {
    assert!(bind(
        "SELECT n FROM records WHERE n=$1",
        json!([{"type":"int8","value":null}])
    )
    .is_ok());
    assert!(bind(
        "SELECT n FROM records WHERE n=$1",
        json!([{"type":"text","value":null}])
    )
    .is_err());
    assert!(bind(
        "SELECT n FROM records WHERE NOT $1 OR b=$1",
        json!([{"type":"bool","value":null}])
    )
    .is_ok());
    for value in [
        json!("%kitchen%"),
        json!("%雪%"),
        json!("%O'Reilly%"),
        json!(format!("%{}%", "x".repeat(128))),
    ] {
        assert!(bind(
            "SELECT t FROM records WHERE t LIKE $1",
            json!([{"type":"text","value":value}])
        )
        .is_ok());
    }
    for value in [
        json!(null),
        json!("%%"),
        json!("kitchen"),
        json!("%a_b%"),
        json!("%a%b%"),
        json!("%a\\b%"),
        json!(format!("%{}%", "x".repeat(129))),
    ] {
        assert!(bind(
            "SELECT t FROM records WHERE t LIKE $1",
            json!([{"type":"text","value":value}])
        )
        .is_err());
    }
    assert!(bind(
        "SELECT n FROM records WHERE n LIKE $1",
        json!([{"type":"text","value":"%1%"}])
    )
    .is_err());
}
