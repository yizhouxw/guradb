//! Private legacy SQL identifier, parameter and typed-expression compilation.
use crate::{Dataset, Error, Result};
use datafusion::{
    common::ScalarValue,
    logical_expr::{col, lit, Expr},
    sql::sqlparser::ast::{BinaryOperator, Ident, UnaryOperator, Value},
};
use std::ops::Not;

pub(super) fn unsupported() -> Error {
    Error::new(
        "unsupported",
        "SQL is outside the alpha single-table SELECT whitelist",
    )
}
pub(super) fn ident(value: &Ident) -> Result<String> {
    let name = if value.quote_style.is_some() {
        value.value.clone()
    } else {
        value.value.to_ascii_lowercase()
    };
    if name.is_empty()
        || name.len() > 128
        || !name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
        || name.as_bytes()[0].is_ascii_digit()
    {
        return Err(unsupported());
    }
    Ok(name)
}

pub(super) struct Compiler<'a> {
    pub(super) dataset: &'a Dataset,
    pub(super) bindings: crate::parameters::Bindings,
}
impl Compiler<'_> {
    pub(super) fn column(&self, name: &str) -> Result<String> {
        self.dataset
            .manifest
            .schema
            .iter()
            .find(|f| f.name == name)
            .map(|f| f.r#type.clone())
            .ok_or_else(unsupported)
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
                Value::Number(n, false) => Ok((
                    lit(n.parse::<i64>().map_err(|_| unsupported())?),
                    "int8".into(),
                )),
                Value::SingleQuotedString(s) => Ok((lit(s.clone()), "text".into())),
                Value::Boolean(v) => Ok((lit(*v), "bool".into())),
                Value::Null => Ok((lit(ScalarValue::Null), "null".into())),
                Value::Placeholder(token) => self.bindings.expression(token),
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
            Ast::Like {
                negated: false,
                any: false,
                expr,
                pattern,
                escape_char: None,
            } => {
                let Ast::Identifier(id) = expr.as_ref() else {
                    return Err(unsupported());
                };
                let name = ident(id)?;
                let pattern = match pattern.as_ref() {
                    Ast::Value(value) => match &value.value {
                        Value::SingleQuotedString(s) => s.clone(),
                        Value::Placeholder(token) => match self.bindings.resolve(token)? {
                            (ScalarValue::Utf8(Some(s)), _) => s,
                            _ => return Err(unsupported()),
                        },
                        _ => return Err(unsupported()),
                    },
                    _ => return Err(unsupported()),
                };
                let keyword = pattern
                    .strip_prefix('%')
                    .and_then(|p| p.strip_suffix('%'))
                    .ok_or_else(unsupported)?;
                if self.column(&name)? != "text"
                    || keyword.is_empty()
                    || keyword.len() > 128
                    || keyword.contains(['%', '_', '\\'])
                {
                    return Err(unsupported());
                }
                Ok((col(name).like(lit(pattern.clone())), "bool".into()))
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
