use crate::Error;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QueryRequest {
    pub sql: String,
    #[serde(default)]
    pub parameters: Vec<Value>,
    #[serde(default = "read_only")]
    pub mode: String,
    #[serde(default, deserialize_with = "crate::non_null")]
    pub timeout_ms: Option<u64>,
    #[serde(default, deserialize_with = "crate::non_null")]
    pub max_rows: Option<usize>,
    #[serde(default = "published")]
    pub read_consistency: String,
    #[serde(default, deserialize_with = "crate::non_null")]
    pub read_view_id: Option<String>,
}
fn read_only() -> String {
    "read_only".into()
}
fn published() -> String {
    "published".into()
}

#[derive(Clone, Debug, Serialize)]
pub struct SourceVersion {
    pub source_id: String,
    pub format: String,
    pub version: String,
}
#[derive(Clone, Debug, Serialize)]
pub struct ReadContext {
    pub read_consistency: String,
    pub data_revision_id: String,
    pub read_view_id: String,
    pub source_versions: Vec<SourceVersion>,
    pub index_versions: Vec<Value>,
}
#[derive(Clone, Debug, Serialize)]
pub struct Column {
    pub name: String,
    pub r#type: String,
}
#[derive(Clone, Debug, Default, Serialize)]
pub struct QueryStats {
    pub source_reads: usize,
    pub source_bytes: usize,
    pub decoded_bytes: usize,
    pub elapsed_ms: u64,
}
#[derive(Clone, Debug, Serialize)]
pub struct QueryHandle {
    pub query_id: String,
    pub status: String,
    pub result_kind: String,
    pub read_context: ReadContext,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<Error>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stats: Option<QueryStats>,
}
#[derive(Clone, Debug, Serialize)]
pub struct ResultPage {
    pub query_id: String,
    pub columns: Vec<Column>,
    pub rows: Vec<Vec<Value>>,
    pub next_cursor: Option<String>,
    pub truncated: bool,
    pub result_kind: String,
    pub read_context: ReadContext,
}
