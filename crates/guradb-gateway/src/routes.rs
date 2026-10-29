use crate::{auth, state::State};
use axum::{
    extract::{rejection::JsonRejection, Path, Query, State as ExtractState},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use guradb_common::{
    protocol::{FixedQueryRequest, QueryRequest, ResultPage},
    Error,
};
use serde::Deserialize;
use std::sync::Arc;

pub struct ApiError(pub Error);
impl From<Error> for ApiError {
    fn from(value: Error) -> Self {
        Self(value)
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let status = match self.0.code.as_str() {
            "unauthorized" => StatusCode::UNAUTHORIZED,
            "auth_unavailable" => StatusCode::SERVICE_UNAVAILABLE,
            "not_found" => StatusCode::NOT_FOUND,
            "expired" => StatusCode::GONE,
            "not_ready" => StatusCode::CONFLICT,
            "resource_limit" => StatusCode::TOO_MANY_REQUESTS,
            _ => StatusCode::BAD_REQUEST,
        };
        (status, Json(serde_json::json!({"error": self.0}))).into_response()
    }
}
pub async fn submit(
    ExtractState(state): ExtractState<Arc<State>>,
    headers: HeaderMap,
    body: std::result::Result<Json<QueryRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    let principal = auth::authenticate(&state.auth_file, &headers).await?;
    let Json(request) =
        body.map_err(|_| Error::new("invalid_request", "invalid JSON query request"))?;
    let timeout = request.timeout_ms.unwrap_or(state.limits.timeout_ms);
    let rows = request.max_rows.unwrap_or(state.limits.max_rows);
    if timeout == 0
        || timeout > state.limits.timeout_ms
        || rows == 0
        || rows > state.limits.max_rows
    {
        return Err(Error::new("resource_limit", "request exceeds server limits").into());
    }
    let plan = guradb_query::sql::prepare(&request, &state.catalog, &principal.datasets)?;
    let handle = state.submit(plan, principal, timeout, rows).await?;
    Ok((StatusCode::ACCEPTED, Json(handle)).into_response())
}
pub async fn submit_fixed(
    ExtractState(state): ExtractState<Arc<State>>,
    headers: HeaderMap,
    body: std::result::Result<Json<FixedQueryRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    let principal = auth::authenticate(&state.auth_file, &headers).await?;
    let Json(request) =
        body.map_err(|_| Error::new("invalid_request", "invalid fixed query request"))?;
    let timeout = request.timeout_ms.unwrap_or(state.limits.timeout_ms);
    let rows = request.max_rows.unwrap_or(state.limits.max_rows);
    if timeout == 0
        || timeout > state.limits.timeout_ms
        || rows == 0
        || rows > state.limits.max_rows
    {
        return Err(Error::new("resource_limit", "request exceeds server limits").into());
    }
    let plan = guradb_query::fixed::prepare(&request, &state.catalog, &principal.datasets)?;
    let handle = state.submit(plan, principal, timeout, rows).await?;
    Ok((StatusCode::ACCEPTED, Json(handle)).into_response())
}
pub async fn status(
    ExtractState(state): ExtractState<Arc<State>>,
    headers: HeaderMap,
    Path(id): Path<String>,
) -> Result<Response, ApiError> {
    let principal = auth::authenticate(&state.auth_file, &headers).await?;
    let mut registry = state.registry.lock().await;
    registry.prune(&state.limits);
    Ok(Json(registry.get_mut(&id, &principal)?.handle.clone()).into_response())
}
pub async fn cancel(
    ExtractState(state): ExtractState<Arc<State>>,
    headers: HeaderMap,
    Path(id): Path<String>,
) -> Result<Response, ApiError> {
    let principal = auth::authenticate(&state.auth_file, &headers).await?;
    let mut registry = state.registry.lock().await;
    registry.prune(&state.limits);
    let entry = registry.get_mut(&id, &principal)?;
    let status = if entry.finished.is_none() {
        entry.handle.status = "cancel_requested".into();
        entry.cancel.cancel();
        StatusCode::ACCEPTED
    } else {
        StatusCode::OK
    };
    Ok((status, Json(entry.handle.clone())).into_response())
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Page {
    cursor: Option<String>,
    page_size: Option<usize>,
}
pub async fn results(
    ExtractState(state): ExtractState<Arc<State>>,
    headers: HeaderMap,
    Path(id): Path<String>,
    page: std::result::Result<Query<Page>, axum::extract::rejection::QueryRejection>,
) -> Result<Response, ApiError> {
    let principal = auth::authenticate(&state.auth_file, &headers).await?;
    let Query(page) =
        page.map_err(|_| Error::new("invalid_request", "invalid pagination parameters"))?;
    let count = page.page_size.unwrap_or(100);
    if count == 0 || count > 1000 {
        return Err(Error::new("invalid_request", "page size outside 1..1000").into());
    }
    let mut registry = state.registry.lock().await;
    registry.prune(&state.limits);
    let entry = registry.get_mut(&id, &principal)?;
    let Some(output) = &entry.output else {
        return Err(Error::new("not_ready", "query has no successful result").into());
    };
    let offset = match page.cursor {
        Some(cursor) => state.offset(
            &cursor,
            &id,
            &principal,
            &entry.handle.read_context.read_view_id,
        )?,
        None => 0,
    };
    if offset > output.rows.len() {
        return Err(Error::new("invalid_cursor", "cursor offset outside result").into());
    }
    let end = (offset + count).min(output.rows.len());
    Ok(Json(ResultPage {
        query_id: id.clone(),
        binding: entry.handle.binding.clone(),
        lineage: output
            .lineage
            .as_ref()
            .map(|rows| rows[offset..end].to_vec()),
        columns: output.columns.clone(),
        rows: output.rows[offset..end].to_vec(),
        next_cursor: (end < output.rows.len()).then(|| {
            state.cursor(
                &id,
                &principal,
                &entry.handle.read_context.read_view_id,
                end,
            )
        }),
        truncated: output.truncated,
        result_kind: "data".into(),
        read_context: entry.handle.read_context.clone(),
    })
    .into_response())
}
