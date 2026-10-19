use super::*;
use guradb_catalog::Dataset;
use guradb_common::{manifest::Manifest, protocol::ReadContext};
use guradb_storage::Source;
use std::sync::Arc;

fn catalog() -> Catalog {
    // A deliberately nonexistent source proves Describe never scans data.
    let manifest: Manifest = serde_json::from_value(json!({
        "schema_version": 1, "dataset_id": "89b349e2-cc73-4c22-871d-c80a159d7789",
        "table_name": "documents", "retention_mode": "best-effort",
        "backend": {"kind": "local", "root": "/nonexistent"},
        "files": [], "schema": [
            {"name": "id", "data_type": "int8", "nullable": false},
            {"name": "title", "data_type": "text", "nullable": true},
            {"name": "active", "data_type": "bool", "nullable": true}
        ]
    }))
    .unwrap();
    Catalog::from([(
        "documents".into(),
        Arc::new(Dataset {
            manifest,
            source: Source::Local("/nonexistent".into()),
            context: ReadContext {
                read_consistency: "published".into(),
                data_revision_id: "rev".into(),
                read_view_id: "view".into(),
                source_versions: vec![],
                index_versions: vec![],
            },
        }),
    )])
}

fn inspect(sql: &str, types: &[Option<String>]) -> Result<Description> {
    describe(
        sql,
        &catalog(),
        &["89b349e2-cc73-4c22-871d-c80a159d7789".into()],
        types,
    )
}

#[test]
fn describes_aliases_and_infers_types_without_io() {
    let description = inspect("SELECT title AS label, id, active FROM documents WHERE id = $1 AND title <> $2 AND active = $3", &[]).unwrap();
    assert_eq!(description.parameter_types, ["int8", "text", "bool"]);
    assert_eq!(
        description
            .columns
            .iter()
            .map(|c| (c.name.as_str(), c.r#type.as_str()))
            .collect::<Vec<_>>(),
        [("label", "text"), ("id", "int8"), ("active", "bool")]
    );
    assert_eq!(
        inspect("SELECT * FROM documents LIMIT 0", &[])
            .unwrap()
            .columns
            .len(),
        3
    );
}

#[test]
fn propagates_repeated_parameter_constraints() {
    let description = inspect(
        "SELECT id FROM documents WHERE $1 = $2 AND $2 = id AND NOT $3",
        &[],
    )
    .unwrap();
    assert_eq!(description.parameter_types, ["int8", "int8", "bool"]);
    assert_eq!(
        inspect(
            "SELECT id FROM documents WHERE $1 IS NULL",
            &[Some("text".into())]
        )
        .unwrap()
        .parameter_types,
        ["text"]
    );
    assert_eq!(
        inspect("SELECT id FROM documents WHERE $1 = NULL OR id = $1", &[])
            .unwrap()
            .parameter_types,
        ["int8"]
    );
}

#[test]
fn rejects_ambiguous_conflicting_or_incorrect_parameters() {
    for sql in [
        "SELECT id FROM documents WHERE $1 IS NULL",
        "SELECT id FROM documents WHERE $1 = $2",
    ] {
        assert_eq!(
            inspect(sql, &[]).err().unwrap().code,
            "indeterminate_datatype"
        );
    }
    for sql in [
        "SELECT id FROM documents WHERE id = $1 OR title = $1",
        "SELECT id FROM documents WHERE id = $2",
        "SELECT id FROM documents WHERE id = $65",
    ] {
        assert!(inspect(sql, &[]).is_err(), "{sql}");
    }
    assert!(inspect(
        "SELECT id FROM documents WHERE id = $1",
        &[Some("text".into())]
    )
    .is_err());
    assert!(inspect("SELECT id FROM documents", &[Some("int8".into())]).is_err());
}

#[test]
fn retains_execution_whitelist_and_authorization() {
    for sql in [
        "BEGIN",
        "DELETE FROM documents",
        "SELECT id FROM documents; SELECT id FROM documents",
        "SELECT pg_sleep(1) FROM documents",
        "SELECT $1 FROM documents",
        "SELECT id FROM documents FOR UPDATE",
    ] {
        assert!(inspect(sql, &[]).is_err(), "{sql}");
    }
    assert_eq!(
        describe("SELECT id FROM documents", &catalog(), &[], &[])
            .err()
            .unwrap()
            .code,
        "not_found"
    );
}

#[test]
fn literal_nested_quoted_and_boundary_descriptions() {
    for sql in [
        "SELECT id FROM documents WHERE (id = $1) AND title IS NOT NULL",
        "SELECT id FROM documents WHERE \"id\" = $1",
        "SELECT id FROM documents WHERE title = 'alpha' OR active = true",
        "SELECT id FROM documents WHERE id > -1",
    ] {
        assert!(inspect(sql, &[]).is_ok(), "{sql}");
    }
    for sql in [
        "",
        "SELECT",
        "SELECT id FROM documents UNION SELECT id FROM documents",
    ] {
        assert!(inspect(sql, &[]).is_err());
    }
    assert!(inspect(&"x".repeat(16385), &[]).is_err());
    assert!(inspect(
        "SELECT id FROM documents WHERE id=$1",
        &[Some("float8".into())]
    )
    .is_err());
    assert!(inspect("SELECT id FROM documents", &vec![None; 65]).is_err());
    // Private inference helper rejects unknown AST kinds before execution's whitelist.
    let ast = Expr::Tuple(vec![]);
    assert_eq!(infer(&ast, None, &[], &mut []).unwrap(), None);
}
