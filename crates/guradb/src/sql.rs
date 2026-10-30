use crate::compile::{ident, unsupported, Compiler};
use crate::{Column, Dataset, Result};
use datafusion::{
    logical_expr::{col, Expr, SortExpr},
    sql::sqlparser::{ast::*, dialect::PostgreSqlDialect, parser::Parser},
};

use std::{collections::HashSet, sync::Arc};

pub struct Prepared {
    pub columns: Vec<Column>,
    pub projection: Vec<Expr>,
    pub filter: Option<Expr>,
    pub order: Vec<SortExpr>,
    pub sql_limit: Option<usize>,
    pub distinct: bool,
}

pub fn prepare(sql: &str, dataset: Arc<Dataset>) -> Result<Prepared> {
    if sql.is_empty() || sql.len() > 16 * 1024 {
        return Err(unsupported());
    }
    let statements = Parser::parse_sql(&PostgreSqlDialect {}, sql).map_err(|_| unsupported())?;
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
    let distinct = match &select.distinct {
        None => false,
        Some(Distinct::Distinct) => true,
        Some(_) => return Err(unsupported()),
    };
    if select.top.is_some()
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
    if table != "records" {
        return Err(unsupported());
    }
    let mut compiler = Compiler { dataset: &dataset };
    let mut projection = Vec::new();
    let mut columns = Vec::new();
    let mut names = HashSet::new();
    for item in &select.projection {
        match item {
            SelectItem::Wildcard(options) if *options == WildcardAdditionalOptions::default() => {
                for field in &dataset.manifest.schema {
                    if !names.insert(field.name.clone()) {
                        return Err(unsupported());
                    }
                    projection.push(col(&field.name));
                    columns.push(Column {
                        name: field.name.clone(),
                        r#type: field.r#type.clone(),
                    });
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
                let kind = compiler.column(&name)?;
                let output = alias.unwrap_or_else(|| name.clone());
                if !names.insert(output.clone()) {
                    return Err(unsupported());
                }
                projection.push(col(name).alias(output.clone()));
                columns.push(Column {
                    name: output,
                    r#type: kind,
                });
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
            if distinct {
                if !names.contains(&name) {
                    return Err(unsupported());
                }
            } else {
                compiler.column(&name)?;
            }
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
    Ok(Prepared {
        columns,
        projection,
        filter,
        order,
        sql_limit,
        distinct,
    })
}
