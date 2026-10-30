//! Strict bounded aggregate SQL compilation; execution remains DataFusion.
use crate::compile::{ident, unsupported, Compiler};
use crate::{Column, Result};
use datafusion::{
    functions_aggregate::expr_fn::{count, max, min},
    logical_expr::{col, lit, Expr, SortExpr},
    sql::sqlparser::ast::{self, *},
};
use std::collections::{HashMap, HashSet};

pub const INPUT_LIMIT: usize = 200;
const GROUP: &str = "__guradb_group";

pub struct Plan {
    pub group: Vec<Expr>,
    pub expressions: Vec<Expr>,
}
pub struct Compiled {
    pub plan: Plan,
    pub columns: Vec<Column>,
    pub projection: Vec<Expr>,
    pub order: Vec<SortExpr>,
}

pub(super) fn prepare(
    select: &Select,
    order_by: Option<&OrderBy>,
    compiler: &Compiler<'_>,
) -> Result<Option<Compiled>> {
    let group = match &select.group_by {
        GroupByExpr::Expressions(items, modifiers) if modifiers.is_empty() => {
            match items.as_slice() {
                [] => None,
                [ast::Expr::Identifier(id)] => {
                    let name = ident(id)?;
                    compiler.column(&name)?;
                    Some(name)
                }
                _ => return Err(unsupported()),
            }
        }
        _ => return Err(unsupported()),
    };
    let has_function = select.projection.iter().any(|item| {
        matches!(
            item,
            SelectItem::UnnamedExpr(ast::Expr::Function(_))
                | SelectItem::ExprWithAlias {
                    expr: ast::Expr::Function(_),
                    ..
                }
        )
    });
    if group.is_none() && !has_function {
        return Ok(None);
    }
    if select.distinct.is_some() {
        return Err(unsupported());
    }
    let mut columns = Vec::new();
    let mut projection = Vec::new();
    let mut expressions = Vec::new();
    let mut outputs = HashMap::new();
    let mut names = HashSet::new();
    for item in &select.projection {
        let (expr, alias) = match item {
            SelectItem::UnnamedExpr(expr) => (expr, None),
            SelectItem::ExprWithAlias { expr, alias } => (expr, Some(ident(alias)?)),
            _ => return Err(unsupported()),
        };
        let (internal, default, kind) = match expr {
            ast::Expr::Identifier(id) => {
                let name = ident(id)?;
                if group.as_ref() != Some(&name) {
                    return Err(unsupported());
                }
                (GROUP.to_string(), name.clone(), compiler.column(&name)?)
            }
            ast::Expr::Function(function) => {
                let (expression, default, kind) = function_expr(function, compiler)?;
                let internal = format!("__guradb_aggregate_{}", expressions.len());
                expressions.push(expression.alias(&internal));
                (internal, default, kind)
            }
            _ => return Err(unsupported()),
        };
        let output = alias.unwrap_or(default);
        if !names.insert(output.clone()) {
            return Err(unsupported());
        }
        outputs.insert(output.clone(), internal.clone());
        projection.push(col(internal).alias(&output));
        columns.push(Column {
            name: output,
            r#type: kind,
        });
    }
    if projection.is_empty() {
        return Err(unsupported());
    }
    let mut order = Vec::new();
    if let Some(order_by) = order_by {
        if order_by.interpolate.is_some() {
            return Err(unsupported());
        }
        let OrderByKind::Expressions(items) = &order_by.kind else {
            return Err(unsupported());
        };
        if items.len() > 64 {
            return Err(unsupported());
        }
        for item in items {
            let ast::Expr::Identifier(id) = &item.expr else {
                return Err(unsupported());
            };
            if item.with_fill.is_some() {
                return Err(unsupported());
            }
            let name = ident(id)?;
            let internal = outputs.get(&name).ok_or_else(unsupported)?;
            let asc = item.options.asc.unwrap_or(true);
            order.push(col(internal).sort(asc, item.options.nulls_first.unwrap_or(!asc)));
        }
    }
    // This hidden key also breaks ties when it was not projected or was aliased.
    let group = if let Some(name) = group {
        order.push(col(GROUP).sort(true, false));
        vec![col(name).alias(GROUP)]
    } else {
        Vec::new()
    };
    Ok(Some(Compiled {
        plan: Plan { group, expressions },
        columns,
        projection,
        order,
    }))
}

fn function_expr(function: &Function, compiler: &Compiler<'_>) -> Result<(Expr, String, String)> {
    if function.name.0.len() != 1
        || function.uses_odbc_syntax
        || function.parameters != FunctionArguments::None
        || function.filter.is_some()
        || function.null_treatment.is_some()
        || function.over.is_some()
        || !function.within_group.is_empty()
    {
        return Err(unsupported());
    }
    let ObjectNamePart::Identifier(id) = &function.name.0[0] else {
        return Err(unsupported());
    };
    let name = ident(id)?;
    if !matches!(name.as_str(), "count" | "min" | "max") {
        return Err(unsupported());
    }
    let FunctionArguments::List(args) = &function.args else {
        return Err(unsupported());
    };
    if args.duplicate_treatment.is_some() || !args.clauses.is_empty() || args.args.len() != 1 {
        return Err(unsupported());
    }
    let FunctionArg::Unnamed(arg) = &args.args[0] else {
        return Err(unsupported());
    };
    let (expr, kind) = match arg {
        FunctionArgExpr::Wildcard if name == "count" => (lit(1i64), "int8".to_string()),
        FunctionArgExpr::Expr(ast::Expr::Identifier(id)) => {
            let column = ident(id)?;
            let kind = compiler.column(&column)?;
            (col(column), kind)
        }
        _ => return Err(unsupported()),
    };
    let (expr, kind) = match name.as_str() {
        "count" => (count(expr), "int8".into()),
        "min" if kind == "int8" || kind == "text" => (min(expr), kind),
        "max" if kind == "int8" || kind == "text" => (max(expr), kind),
        _ => return Err(unsupported()),
    };
    Ok((expr, name, kind))
}
