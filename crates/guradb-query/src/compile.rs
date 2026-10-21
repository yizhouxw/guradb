//! Private legacy SQL identifier, parameter and typed-expression compilation.
use datafusion::{
    common::ScalarValue,
    logical_expr::{col, lit, Expr},
    sql::sqlparser::ast::{BinaryOperator, Ident, UnaryOperator, Value},
};
use guradb_catalog::Dataset;
use guradb_common::{manifest::identifier, Error, Result};
use serde_json::Value as Json;
use std::{collections::HashSet, ops::Not};

pub(super) fn unsupported() -> Error {
    Error::new(
        "unsupported",
        "SQL is outside the M0 single-table SELECT whitelist",
    )
}
pub(super) fn ident(value: &Ident) -> Result<String> {
    let name = if value.quote_style.is_some() {
        value.value.clone()
    } else {
        value.value.to_ascii_lowercase()
    };
    if !identifier(&name) {
        return Err(unsupported());
    }
    Ok(name)
}

pub(super) struct Compiler<'a> {
    pub(super) dataset: &'a Dataset,
    pub(super) parameters: &'a [Json],
    pub(super) used: HashSet<usize>,
}
impl Compiler<'_> {
    pub(super) fn column(&self, name: &str) -> Result<String> {
        self.dataset
            .manifest
            .schema
            .iter()
            .find(|f| f.name == name)
            .map(|f| f.data_type.clone())
            .ok_or_else(unsupported)
    }
    fn parameter(&mut self, name: &str) -> Result<(Expr, String)> {
        let n = name
            .strip_prefix('$')
            .and_then(|n| n.parse::<usize>().ok())
            .filter(|n| *n > 0)
            .ok_or_else(|| Error::new("invalid_parameter", "invalid placeholder"))?;
        let value = self
            .parameters
            .get(n - 1)
            .ok_or_else(|| Error::new("invalid_parameter", "missing positional parameter"))?;
        self.used.insert(n);
        let scalar = match value {
            Json::Null => ScalarValue::Null,
            Json::Bool(v) => ScalarValue::Boolean(Some(*v)),
            Json::String(v) => ScalarValue::Utf8(Some(v.clone())),
            Json::Number(v) => {
                let n = v
                    .as_i64()
                    .filter(|n| n.unsigned_abs() <= 9_007_199_254_740_991)
                    .ok_or_else(|| {
                        Error::new(
                            "invalid_parameter",
                            "numeric parameter must be a safe int8 or typed int8 string",
                        )
                    })?;
                ScalarValue::Int64(Some(n))
            }
            Json::Object(v)
                if v.len() == 2 && v.get("type").and_then(Json::as_str) == Some("int8") =>
            {
                let raw = v
                    .get("value")
                    .and_then(Json::as_str)
                    .ok_or_else(unsupported)?;
                let number = raw
                    .parse::<i64>()
                    .map_err(|_| Error::new("invalid_parameter", "int8 outside range"))?;
                if number.to_string() != raw {
                    return Err(Error::new(
                        "invalid_parameter",
                        "int8 must be canonical decimal",
                    ));
                }
                ScalarValue::Int64(Some(number))
            }
            _ => {
                return Err(Error::new(
                    "invalid_parameter",
                    "unsupported parameter type",
                ))
            }
        };
        let kind = match &scalar {
            ScalarValue::Null => "null",
            ScalarValue::Boolean(_) => "bool",
            ScalarValue::Int64(_) => "int8",
            _ => "text",
        };
        Ok((lit(scalar), kind.into()))
    }
    pub(super) fn expression(
        &mut self,
        value: &datafusion::sql::sqlparser::ast::Expr,
        depth: usize,
    ) -> Result<(Expr, String)> {
        use datafusion::sql::sqlparser::ast::Expr as Ast;
        if depth > 32 {
            return Err(unsupported());
        }
        match value {
            Ast::Identifier(id) => {
                let name = ident(id)?;
                Ok((col(&name), self.column(&name)?))
            }
            Ast::Value(value) => match &value.value {
                Value::Placeholder(name) => self.parameter(name),
                Value::Number(n, false) => Ok((
                    lit(n.parse::<i64>().map_err(|_| unsupported())?),
                    "int8".into(),
                )),
                Value::SingleQuotedString(s) => Ok((lit(s.clone()), "text".into())),
                Value::Boolean(v) => Ok((lit(*v), "bool".into())),
                Value::Null => Ok((lit(ScalarValue::Null), "null".into())),
                _ => Err(unsupported()),
            },
            Ast::Nested(value) => self.expression(value, depth + 1),
            Ast::IsNull(value) => Ok((
                self.expression(value, depth + 1)?.0.is_null(),
                "bool".into(),
            )),
            Ast::IsNotNull(value) => Ok((
                self.expression(value, depth + 1)?.0.is_not_null(),
                "bool".into(),
            )),
            Ast::UnaryOp {
                op: UnaryOperator::Not,
                expr,
            } => {
                let (expr, kind) = self.expression(expr, depth + 1)?;
                if kind != "bool" && kind != "null" {
                    return Err(unsupported());
                }
                Ok((expr.not(), "bool".into()))
            }
            Ast::UnaryOp {
                op: UnaryOperator::Minus,
                expr,
            } => {
                if let Ast::Value(v) = expr.as_ref() {
                    if let Value::Number(n, false) = &v.value {
                        return Ok((
                            lit(format!("-{n}").parse::<i64>().map_err(|_| unsupported())?),
                            "int8".into(),
                        ));
                    }
                }
                Err(unsupported())
            }
            Ast::BinaryOp { left, op, right } => {
                let (left, lk) = self.expression(left, depth + 1)?;
                let (right, rk) = self.expression(right, depth + 1)?;
                if (lk != rk && lk != "null" && rk != "null")
                    || (matches!(op, BinaryOperator::And | BinaryOperator::Or)
                        && (lk != "bool" && lk != "null" || rk != "bool" && rk != "null"))
                {
                    return Err(unsupported());
                }
                let expr = match op {
                    BinaryOperator::Eq => left.eq(right),
                    BinaryOperator::NotEq => left.not_eq(right),
                    BinaryOperator::Lt => left.lt(right),
                    BinaryOperator::LtEq => left.lt_eq(right),
                    BinaryOperator::Gt => left.gt(right),
                    BinaryOperator::GtEq => left.gt_eq(right),
                    BinaryOperator::And => left.and(right),
                    BinaryOperator::Or => left.or(right),
                    _ => return Err(unsupported()),
                };
                Ok((expr, "bool".into()))
            }
            _ => Err(unsupported()),
        }
    }
}
