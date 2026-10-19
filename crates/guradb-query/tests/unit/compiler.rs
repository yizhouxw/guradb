use super::*;
use crate::fixture::{Fixture, DATASET};
use serde_json::json;

#[test]
fn compiler_depth_nulls_and_unsupported_expressions() {
    let fixture = Fixture::new();
    let dataset = &fixture.catalog["documents"];
    let mut compiler = Compiler {
        dataset,
        parameters: &[],
        used: HashSet::new(),
    };
    use datafusion::sql::sqlparser::ast::Expr as Ast;
    let literal = Ast::Value(Value::Number("1".into(), false).into());
    assert!(compiler.expression(&literal, 33).is_err());
    for ast in [
        Ast::UnaryOp {
            op: UnaryOperator::Minus,
            expr: Box::new(Ast::Identifier(Ident::new("id"))),
        },
        Ast::UnaryOp {
            op: UnaryOperator::Minus,
            expr: Box::new(Ast::Value(Value::Boolean(true).into())),
        },
        Ast::Value(Value::DoubleQuotedString("unsupported".into()).into()),
    ] {
        assert!(compiler.expression(&ast, 0).is_err());
    }
    for sql in [
        "SELECT * FROM (SELECT id FROM documents)",
        "SELECT id AS \"Bad\" FROM documents",
        "SELECT id FROM documents ORDER BY ALL",
        "SELECT id, * FROM documents",
        "SELECT id FROM documents WHERE id < 2",
        "SELECT id FROM documents WHERE active IS NOT NULL",
        "SELECT id FROM documents WHERE NOT (id = 2)",
        "SELECT id FROM documents WHERE id = -1",
    ] {
        let req: QueryRequest = serde_json::from_value(json!({"sql":sql})).unwrap();
        let result = prepare(&req, &fixture.catalog, &[DATASET.into()]);
        if sql.contains("IS NOT NULL")
            || sql.contains("NOT (")
            || sql.contains("= -1")
            || sql.contains("id < 2")
        {
            assert!(result.is_ok(), "{sql}");
        } else {
            assert!(result.is_err(), "{sql}");
        }
    }
    let long_order = (0..65).map(|_| "id").collect::<Vec<_>>().join(",");
    let req: QueryRequest = serde_json::from_value(
        json!({"sql":format!("SELECT id FROM documents ORDER BY {long_order}")}),
    )
    .unwrap();
    assert!(prepare(&req, &fixture.catalog, &[DATASET.into()]).is_err());
}
