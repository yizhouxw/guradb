//! Describe the same bounded SELECT language without reading any source data.
use datafusion::sql::sqlparser::{ast::*, dialect::PostgreSqlDialect, parser::Parser};
use guradb_catalog::Catalog;
use guradb_common::{
    protocol::{Column, QueryRequest},
    Error, Result,
};
use serde_json::{json, Value as Json};

#[derive(Clone)]
pub struct Description {
    pub columns: Vec<Column>,
    pub parameter_types: Vec<String>,
}

fn invalid(message: &str) -> Error {
    Error::new("invalid_parameter", message)
}

fn placeholder(value: &Expr) -> Option<&str> {
    match value {
        Expr::Value(value) => match &value.value {
            Value::Placeholder(name) => Some(name),
            _ => None,
        },
        _ => None,
    }
}

fn position(name: &str) -> Result<usize> {
    name.strip_prefix('$')
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|n| (1..=64).contains(n))
        .map(|n| n - 1)
        .ok_or_else(|| invalid("parameter position must be within 1..64"))
}

fn parameter_count(expression: &Expr) -> Result<usize> {
    if let Some(name) = placeholder(expression) {
        return Ok(position(name)? + 1);
    }
    match expression {
        Expr::Nested(expr)
        | Expr::IsNull(expr)
        | Expr::IsNotNull(expr)
        | Expr::UnaryOp { expr, .. } => parameter_count(expr),
        Expr::BinaryOp { left, right, .. } => {
            Ok(parameter_count(left)?.max(parameter_count(right)?))
        }
        _ => Ok(0),
    }
}

fn unify(actual: Option<String>, expected: Option<&str>) -> Result<Option<String>> {
    match (actual, expected) {
        (Some(actual), Some(expected)) if actual != expected => {
            Err(invalid("parameter has incompatible type constraints"))
        }
        (Some(actual), _) => Ok(Some(actual)),
        (None, Some(expected)) => Ok(Some(expected.into())),
        (None, None) => Ok(None),
    }
}

fn infer(
    expression: &Expr,
    expected: Option<&str>,
    columns: &[guradb_common::manifest::Field],
    types: &mut [Option<String>],
) -> Result<Option<String>> {
    if let Some(name) = placeholder(expression) {
        let index = position(name)?;
        types[index] = unify(types[index].clone(), expected)?;
        return Ok(types[index].clone());
    }
    let actual = match expression {
        Expr::Identifier(id) => {
            let name = if id.quote_style.is_some() {
                id.value.clone()
            } else {
                id.value.to_ascii_lowercase()
            };
            columns
                .iter()
                .find(|field| field.name == name)
                .map(|field| field.data_type.clone())
        }
        Expr::Value(value) => match value.value {
            Value::Number(..) => Some("int8".into()),
            Value::SingleQuotedString(..) => Some("text".into()),
            Value::Boolean(..) => Some("bool".into()),
            _ => None,
        },
        Expr::Nested(expr) => return infer(expr, expected, columns, types),
        Expr::UnaryOp {
            op: UnaryOperator::Not,
            expr,
        } => {
            infer(expr, Some("bool"), columns, types)?;
            Some("bool".into())
        }
        Expr::UnaryOp { .. } => Some("int8".into()),
        Expr::IsNull(expr) | Expr::IsNotNull(expr) => {
            infer(expr, None, columns, types)?;
            Some("bool".into())
        }
        Expr::BinaryOp { left, op, right } => {
            if matches!(op, BinaryOperator::And | BinaryOperator::Or) {
                infer(left, Some("bool"), columns, types)?;
                infer(right, Some("bool"), columns, types)?;
            } else {
                let left_type = infer(left, None, columns, types)?;
                let right_type = infer(right, left_type.as_deref(), columns, types)?;
                infer(left, right_type.as_deref(), columns, types)?;
            }
            Some("bool".into())
        }
        _ => None,
    };
    unify(actual, expected)
}

pub fn describe(
    sql: &str,
    catalog: &Catalog,
    allowed: &[String],
    parameter_types: &[Option<String>],
) -> Result<Description> {
    if sql.is_empty() || sql.len() > 16 * 1024 || parameter_types.len() > 64 {
        return Err(Error::new(
            "unsupported",
            "SQL or parameter count exceeds bounds",
        ));
    }
    let statements = Parser::parse_sql(&PostgreSqlDialect {}, sql)
        .map_err(|_| Error::new("unsupported", "invalid SELECT syntax"))?;
    let selection = match statements.as_slice() {
        [Statement::Query(query)] => match query.body.as_ref() {
            SetExpr::Select(select) => select.selection.as_ref(),
            _ => {
                return Err(Error::new(
                    "unsupported",
                    "only single-table SELECT is supported",
                ))
            }
        },
        _ => return Err(Error::new("unsupported", "exactly one SELECT is required")),
    };
    let count = selection.map(parameter_count).transpose()?.unwrap_or(0);
    if parameter_types.len() > count {
        return Err(invalid("more declared parameters than placeholders"));
    }
    let mut request = QueryRequest {
        sql: sql.into(),
        parameters: vec![Json::Null; count],
        mode: "read_only".into(),
        timeout_ms: None,
        max_rows: None,
        read_consistency: "published".into(),
        read_view_id: None,
    };
    // This is the execution compiler, so describe cannot broaden its whitelist.
    let plan = crate::sql::prepare(&request, catalog, allowed)?;
    let mut types = parameter_types.to_vec();
    types.resize(count, None);
    if types
        .iter()
        .flatten()
        .any(|kind| !matches!(kind.as_str(), "int8" | "text" | "bool"))
    {
        return Err(invalid("unsupported parameter type"));
    }
    if let Some(selection) = selection {
        // At most 64 unknowns can acquire types. Repeated placeholders may carry
        // a constraint from a later comparison back to an earlier expression.
        for _ in 0..=count {
            let before = types.clone();
            infer(
                selection,
                Some("bool"),
                &plan.dataset.manifest.schema,
                &mut types,
            )?;
            if types == before {
                break;
            }
        }
    }
    let types: Vec<String> = types.into_iter().collect::<Option<_>>().ok_or_else(|| {
        Error::new(
            "indeterminate_datatype",
            "cannot infer parameter type; specify its PostgreSQL type",
        )
    })?;
    request.parameters = types
        .iter()
        .map(|kind| match kind.as_str() {
            "int8" => json!({"type": "int8", "value": "0"}),
            "bool" => Json::Bool(false),
            _ => Json::String(String::new()),
        })
        .collect();
    crate::sql::prepare(&request, catalog, allowed)?;
    Ok(Description {
        columns: plan.columns,
        parameter_types: types,
    })
}

#[cfg(test)]
#[path = "../tests/unit/describe_existing.rs"]
mod tests;
