use crate::{sql::Prepared, Error, Result, POOL_LIMIT, RESULT_LIMIT, ROW_LIMIT};
use arrow::{
    array::{Array, BooleanArray, Int64Array, StringArray},
    datatypes::{DataType, SchemaRef},
    record_batch::RecordBatch,
};
use datafusion::{
    datasource::MemTable,
    execution::{
        disk_manager::{DiskManagerBuilder, DiskManagerMode},
        memory_pool::GreedyMemoryPool,
        runtime_env::RuntimeEnvBuilder,
    },
    prelude::{SessionConfig, SessionContext},
};
use futures::TryStreamExt;
use serde_json::{json, Value};
use std::sync::Arc;

fn engine(error: datafusion::error::DataFusionError) -> Error {
    Error::new(
        if matches!(
            error,
            datafusion::error::DataFusionError::ResourcesExhausted(_)
        ) {
            "resource_limit"
        } else {
            "execution_failed"
        },
        "query failed within alpha constraints",
    )
}

pub async fn execute(
    plan: Prepared,
    schema: SchemaRef,
    batches: Vec<RecordBatch>,
    sha: &str,
) -> Result<String> {
    let runtime = RuntimeEnvBuilder::new()
        .with_memory_pool(Arc::new(GreedyMemoryPool::new(POOL_LIMIT)))
        .with_disk_manager_builder(
            DiskManagerBuilder::default().with_mode(DiskManagerMode::Disabled),
        )
        .build_arc()
        .map_err(engine)?;
    let context = SessionContext::new_with_config_rt(
        SessionConfig::new()
            .with_target_partitions(1)
            .with_batch_size(4096),
        runtime,
    );
    let table = MemTable::try_new(schema, vec![batches]).map_err(engine)?;
    let mut frame = context.read_table(Arc::new(table)).map_err(engine)?;
    if let Some(filter) = plan.filter {
        frame = frame.filter(filter).map_err(engine)?;
    }
    if !plan.order.is_empty() {
        frame = frame.sort(plan.order).map_err(engine)?;
    }
    frame = frame.select(plan.projection).map_err(engine)?;
    frame = frame
        .limit(
            0,
            Some(plan.sql_limit.unwrap_or(ROW_LIMIT + 1).min(ROW_LIMIT + 1)),
        )
        .map_err(engine)?;
    let mut stream = frame.execute_stream().await.map_err(engine)?;
    let mut rows = Vec::new();
    let mut size = 4096usize;
    let mut truncated = false;
    while let Some(batch) = stream.try_next().await.map_err(engine)? {
        for row in 0..batch.num_rows() {
            if rows.len() == ROW_LIMIT {
                truncated = true;
                break;
            }
            let values: Vec<_> = batch
                .columns()
                .iter()
                .map(|array| {
                    if array.is_null(row) {
                        return Value::Null;
                    }
                    match array.data_type() {
                        DataType::Int64 => Value::String(
                            array
                                .as_any()
                                .downcast_ref::<Int64Array>()
                                .expect("checked schema")
                                .value(row)
                                .to_string(),
                        ),
                        DataType::Boolean => Value::Bool(
                            array
                                .as_any()
                                .downcast_ref::<BooleanArray>()
                                .expect("checked schema")
                                .value(row),
                        ),
                        _ => Value::String(
                            array
                                .as_any()
                                .downcast_ref::<StringArray>()
                                .expect("checked schema")
                                .value(row)
                                .into(),
                        ),
                    }
                })
                .collect();
            size += serde_json::to_vec(&values)
                .map_err(|_| Error::new("execution_failed", "cannot encode rows"))?
                .len()
                + 1;
            if size > RESULT_LIMIT {
                return Err(Error::new("resource_limit", "result exceeds byte budget"));
            }
            rows.push(values);
        }
        if truncated {
            break;
        }
    }
    let output = serde_json::to_string(&json!({"source_sha256": sha, "columns": plan.columns, "rows": rows, "truncated": truncated}))
        .map_err(|_| Error::new("execution_failed", "cannot encode output"))?;
    if output.len() > RESULT_LIMIT {
        return Err(Error::new("resource_limit", "result exceeds byte budget"));
    }
    Ok(output)
}
