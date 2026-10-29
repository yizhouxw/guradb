//! Controlled local manifest path; never a catalog/pin authority.
use arrow::{array::StringArray, record_batch::RecordBatch};
use guradb_catalog::Catalog;
use guradb_common::{
    manifest::Backend,
    protocol::{FixedQueryRequest, QueryRequest},
    Error, Result,
};
use std::collections::HashSet;
use tokio_util::sync::CancellationToken;

pub fn prepare(
    request: &FixedQueryRequest,
    catalog: &Catalog,
    allowed: &[String],
) -> Result<crate::sql::Prepared> {
    // Authenticate/authorize the requested dataset before reporting version details.
    let dataset = catalog
        .values()
        .find(|dataset| {
            dataset.manifest.dataset_id == request.dataset_id
                && allowed.contains(&request.dataset_id)
        })
        .ok_or_else(|| Error::new("not_found", "dataset is unknown or inaccessible"))?;
    if request.data_revision_id != dataset.context.data_revision_id
        || request.read_view_id != dataset.context.read_view_id
    {
        return Err(Error::new(
            "view_unavailable",
            "fixed revision/view is unavailable",
        ));
    }
    if !matches!(dataset.manifest.backend, Backend::Local { .. })
        || !dataset
            .manifest
            .schema
            .iter()
            .any(|field| field.name == "record_id" && field.data_type == "text" && !field.nullable)
    {
        return Err(Error::new(
            "unsupported",
            "fixed local source requires a non-null text record_id",
        ));
    }
    let query = QueryRequest {
        sql: request.sql.clone(),
        parameters: request.parameters.clone(),
        mode: "read_only".into(),
        timeout_ms: request.timeout_ms,
        max_rows: request.max_rows,
        read_consistency: "published".into(),
        read_view_id: Some(request.read_view_id.clone()),
    };
    let mut plan = crate::sql::prepare(&query, catalog, allowed)?;
    if plan.dataset.manifest.dataset_id != request.dataset_id
        || plan
            .columns
            .iter()
            .any(|field| field.name == "__gura_record_id")
    {
        return Err(Error::new(
            "unsupported",
            "SQL must read the explicitly selected dataset",
        ));
    }
    plan.fixed_identity = true;
    Ok(plan)
}

pub async fn validate_records(
    batches: &[RecordBatch],
    budget: usize,
    cancel: &CancellationToken,
) -> Result<()> {
    let count = batches
        .iter()
        .try_fold(0usize, |n, batch| n.checked_add(batch.num_rows()))
        .ok_or_else(|| Error::new("resource_limit", "identity count overflow"))?;
    // Borrow source strings; include buckets, small-table minimum and allocation slack.
    // This workspace is dropped before allocating the DataFusion execution pool.
    if count
        .checked_mul(64)
        .and_then(|bytes| bytes.checked_add(256))
        .is_none_or(|bytes| bytes > budget)
    {
        return Err(Error::new(
            "resource_limit",
            "stable identity validation exceeds execution budget",
        ));
    }
    let mut seen = HashSet::with_capacity(count);
    for batch in batches {
        let ids = batch
            .column_by_name("record_id")
            .and_then(|array| array.as_any().downcast_ref::<StringArray>())
            .ok_or_else(|| Error::new("source_invalid", "missing stable record_id"))?;
        for (row, id) in ids.iter().enumerate() {
            if row % 256 == 0 {
                tokio::task::yield_now().await;
                if cancel.is_cancelled() {
                    return Err(Error::new("cancelled", "query cancelled"));
                }
            }
            if id.is_none_or(|id| id.is_empty() || !seen.insert(id)) {
                return Err(Error::new(
                    "source_invalid",
                    "record_id must be nonempty and globally unique",
                ));
            }
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "../tests/unit/fixed.rs"]
mod tests;
