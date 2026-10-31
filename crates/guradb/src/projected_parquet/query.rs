//! Compile once against the full source, then scan every group's dependencies.
use super::{bounded, invalid, limit, metadata, query_request, reader, sparse, Transfer};
use crate::{Column, Dataset, Manifest, Result};
use arrow::datatypes::{DataType, Schema};
use serde_json::json;
use std::{
    collections::BTreeSet,
    path::Path,
    sync::Arc,
    time::{Duration, Instant},
};

pub(super) fn required_columns(plan: &crate::sql::Prepared, schema: &Schema) -> Result<Vec<usize>> {
    if plan.distinct || plan.aggregate.is_some() {
        return Err(crate::compile::unsupported());
    }
    let mut indices = BTreeSet::new();
    for expression in plan
        .projection
        .iter()
        .chain(plan.filter.iter())
        .chain(plan.order.iter().map(|s| &s.expr))
    {
        for column in expression.column_refs() {
            if column.relation.is_some() {
                return Err(crate::compile::unsupported());
            }
            indices.insert(
                schema
                    .index_of(&column.name)
                    .map_err(|_| crate::compile::unsupported())?,
            );
        }
    }
    if indices.is_empty() {
        return Err(crate::compile::unsupported());
    }
    Ok(indices.into_iter().collect())
}
pub(super) fn run(mut args: Vec<String>) -> Result<String> {
    let deadline = Instant::now() + Duration::from_secs(10);
    let argv_bytes = args
        .iter()
        .try_fold(0usize, |sum, s| sum.checked_add(s.len() + 1))
        .ok_or_else(limit)?;
    if argv_bytes > 65536 {
        return Err(limit());
    }
    let bindings = crate::parameters::suffix(&mut args)?;
    if args.len() != 6
        || args[2] != "--source"
        || args[4] != "--sql"
        || args[5].is_empty()
        || args[5].len() > 16384
    {
        return Err(invalid());
    }
    let (mut request, port) = query_request::read(Path::new(&args[3]), argv_bytes)?;
    let mut transfer = Transfer {
        deadline,
        port,
        payload: 0,
        headers: 0,
        ranges: Vec::new(),
    };
    let head = transfer.get(&request, &request.header, "header", None)?;
    if head.as_ref() != b"PAR1" {
        return Err(invalid());
    }
    let footer = transfer.get(&request, &request.footer, "footer", None)?;
    let mut budget = bounded::Budget::default();
    let metadata = metadata::parse(&request, &footer, &mut budget)?;
    let source_rows = metadata.metadata().file_metadata().num_rows();
    let full_schema = metadata.schema().clone();
    let columns = full_schema
        .fields()
        .iter()
        .map(|f| Column {
            name: f.name().clone(),
            r#type: match f.data_type() {
                DataType::Int64 => "int8",
                DataType::Boolean => "bool",
                _ => "text",
            }
            .into(),
        })
        .collect();
    let dataset = Arc::new(Dataset {
        manifest: Manifest { schema: columns },
    });
    let prepared = crate::sql::prepare_bound(&args[5], dataset, bindings)?;
    request.columns = required_columns(&prepared, &full_schema)?;
    request.row_groups = (0..metadata.metadata().num_row_groups()).collect();
    // The physical read interface's 3-column/2-group selector is never applied
    // to this complete SQL relation. Its operation request/body budgets are.
    request.validate_plan()?;
    let mut sparse = sparse::Sparse {
        length: request.object_bytes,
        segments: Vec::new(),
        read_calls: Default::default(),
    };
    for group in &request.row_groups {
        for column in &request.columns {
            let part = request.chunk(*group, *column)?.range();
            let bytes = transfer.get(&request, &part, "chunk", Some((*group, *column)))?;
            sparse.segments.push((part.offset, bytes));
        }
    }
    let (schema, batches) = reader::decode_batches(&request, metadata, sparse, &mut budget)?;
    let decoded_rows: usize = batches.iter().map(|b| b.num_rows()).sum();
    if decoded_rows != source_rows as usize {
        return Err(invalid());
    }
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|_| invalid())?;
    let output = runtime.block_on(crate::execution::execute(
        prepared,
        schema,
        batches,
        &request.source_sha256_provenance,
    ))?;
    let mut result: serde_json::Value = serde_json::from_str(&output).map_err(|_| invalid())?;
    let object = result.as_object_mut().ok_or_else(invalid)?;
    object.remove("source_sha256");
    object.extend(json!({"backend":"local-http-projected-sql-v1","origin":request.origin,"object_key":request.object_key,"etag":request.etag,
        "declared_object_bytes":request.object_bytes,"source_sha256_provenance":request.source_sha256_provenance,
        "source_rows":source_rows,"decoded_rows":decoded_rows,"required_columns":request.columns,"row_groups":request.row_groups,
        "read_ranges":transfer.ranges,"request_count":transfer.ranges.len(),"payload_bytes":transfer.payload,"header_bytes":transfer.headers,
        "decode_charged_bytes":budget.used(),"verification":"selected_ranges_only","unread_content_verified":false}).as_object().ok_or_else(invalid)?.clone());
    let output = serde_json::to_string(&result).map_err(|_| invalid())?;
    if output.len() > crate::RESULT_LIMIT {
        return Err(limit());
    }
    Ok(output)
}
