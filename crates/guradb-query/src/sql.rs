use datafusion::{
    common::ScalarValue,
    logical_expr::{col, lit, Expr, SortExpr},
    sql::sqlparser::{ast::*, dialect::PostgreSqlDialect, parser::Parser},
};
use guradb_catalog::{Catalog, Dataset};
use guradb_common::{manifest::identifier, protocol::QueryRequest, Error, Result};
use serde_json::Value as Json;
use std::{collections::HashSet, ops::Not, sync::Arc};

pub struct Prepared {
    pub dataset: Arc<Dataset>,
    pub projection: Vec<Expr>,
    pub filter: Option<Expr>,
    pub order: Vec<SortExpr>,
    pub sql_limit: Option<usize>,
}

fn unsupported() -> Error {
    Error::new(
        "unsupported",
        "SQL is outside the M0 single-table SELECT whitelist",
    )
}
fn ident(value: &Ident) -> Result<String> {
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

pub fn prepare(request: &QueryRequest, catalog: &Catalog, allowed: &[String]) -> Result<Prepared> {
    if request.sql.is_empty()
        || request.sql.len() > 16 * 1024
        || request.parameters.len() > 64
        || request.mode != "read_only"
        || request.read_consistency != "published"
    {
        return Err(unsupported());
    }
    let statements =
        Parser::parse_sql(&PostgreSqlDialect {}, &request.sql).map_err(|_| unsupported())?;
    if statements.len() != 1 {
        return Err(unsupported());
    }
    let Statement::Query(query) = &statements[0] else {
        return Err(unsupported());
    };
    if query.with.is_some()
        || query.fetch.is_some()
        || !query.locks.is_empty()
        || query.for_clause.is_some()
        || query.settings.is_some()
        || query.format_clause.is_some()
        || !query.pipe_operators.is_empty()
    {
        return Err(unsupported());
    }
    let SetExpr::Select(select) = query.body.as_ref() else {
        return Err(unsupported());
    };
    let empty_group = matches!(&select.group_by, GroupByExpr::Expressions(items, modifiers) if items.is_empty() && modifiers.is_empty());
    if select.distinct.is_some()
        || select.top.is_some()
        || select.exclude.is_some()
        || select.into.is_some()
        || select.from.len() != 1
        || !select.from[0].joins.is_empty()
        || !select.lateral_views.is_empty()
        || select.prewhere.is_some()
        || !empty_group
        || !select.cluster_by.is_empty()
        || !select.distribute_by.is_empty()
        || !select.sort_by.is_empty()
        || select.having.is_some()
        || !select.named_window.is_empty()
        || select.qualify.is_some()
        || select.value_table_mode.is_some()
        || select.connect_by.is_some()
        || select.flavor != SelectFlavor::Standard
    {
        return Err(unsupported());
    }
    let TableFactor::Table {
        name,
        alias,
        args,
        with_hints,
        version,
        with_ordinality,
        partitions,
        json_path,
        sample,
        index_hints,
    } = &select.from[0].relation
    else {
        return Err(unsupported());
    };
    if name.0.len() != 1
        || alias.is_some()
        || args.is_some()
        || !with_hints.is_empty()
        || version.is_some()
        || *with_ordinality
        || !partitions.is_empty()
        || json_path.is_some()
        || sample.is_some()
        || !index_hints.is_empty()
    {
        return Err(unsupported());
    }
    let ObjectNamePart::Identifier(name) = &name.0[0] else {
        return Err(unsupported());
    };
    let table = ident(name)?;
    let dataset = catalog
        .get(&table)
        .filter(|data| allowed.contains(&data.manifest.dataset_id))
        .ok_or_else(|| Error::new("not_found", "dataset is unknown or inaccessible"))?
        .clone();
    if request
        .read_view_id
        .as_ref()
        .is_some_and(|v| v != &dataset.context.read_view_id)
    {
        return Err(Error::new(
            "view_unavailable",
            "requested view does not cover this dataset",
        ));
    }
    let mut compiler = Compiler {
        dataset: &dataset,
        parameters: &request.parameters,
        used: HashSet::new(),
    };
    let mut projection = Vec::new();
    let mut names = HashSet::new();
    for item in &select.projection {
        match item {
            SelectItem::Wildcard(options) if *options == WildcardAdditionalOptions::default() => {
                for field in &dataset.manifest.schema {
                    if !names.insert(field.name.clone()) {
                        return Err(unsupported());
                    }
                    projection.push(col(&field.name));
                }
            }
            _ => {
                let (expression, alias) = match item {
                    SelectItem::UnnamedExpr(expression) => (expression, None),
                    SelectItem::ExprWithAlias { expr, alias } => (expr, Some(ident(alias)?)),
                    _ => return Err(unsupported()),
                };
                let datafusion::sql::sqlparser::ast::Expr::Identifier(column) = expression else {
                    return Err(unsupported());
                };
                let name = ident(column)?;
                compiler.column(&name)?;
                let output = alias.unwrap_or_else(|| name.clone());
                if !names.insert(output.clone()) {
                    return Err(unsupported());
                }
                projection.push(col(name).alias(output));
            }
        }
    }
    if projection.is_empty() {
        return Err(unsupported());
    }
    let filter = if let Some(expression) = &select.selection {
        let (expr, kind) = compiler.expression(expression, 0)?;
        if kind != "bool" && kind != "null" {
            return Err(unsupported());
        }
        Some(expr)
    } else {
        None
    };
    let mut order = Vec::new();
    if let Some(order_by) = &query.order_by {
        if order_by.interpolate.is_some() {
            return Err(unsupported());
        }
        let OrderByKind::Expressions(expressions) = &order_by.kind else {
            return Err(unsupported());
        };
        if expressions.len() > 64 {
            return Err(unsupported());
        }
        for expression in expressions {
            let datafusion::sql::sqlparser::ast::Expr::Identifier(column) = &expression.expr else {
                return Err(unsupported());
            };
            let name = ident(column)?;
            compiler.column(&name)?;
            if expression.with_fill.is_some() {
                return Err(unsupported());
            }
            let asc = expression.options.asc.unwrap_or(true);
            order.push(col(name).sort(asc, expression.options.nulls_first.unwrap_or(!asc)));
        }
    }
    let sql_limit = match &query.limit_clause {
        None => None,
        Some(LimitClause::LimitOffset {
            limit: Some(datafusion::sql::sqlparser::ast::Expr::Value(value)),
            offset: None,
            limit_by,
        }) if limit_by.is_empty() => {
            let Value::Number(value, false) = &value.value else {
                return Err(unsupported());
            };
            Some(value.parse::<usize>().map_err(|_| unsupported())?)
        }
        _ => return Err(unsupported()),
    };
    if compiler.used.len() != request.parameters.len()
        || (1..=request.parameters.len()).any(|n| !compiler.used.contains(&n))
    {
        return Err(Error::new(
            "invalid_parameter",
            "parameter count does not match positional placeholders",
        ));
    }
    Ok(Prepared {
        dataset,
        projection,
        filter,
        order,
        sql_limit,
    })
}

struct Compiler<'a> {
    dataset: &'a Dataset,
    parameters: &'a [Json],
    used: HashSet<usize>,
}
impl Compiler<'_> {
    fn column(&self, name: &str) -> Result<String> {
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
    fn expression(
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
