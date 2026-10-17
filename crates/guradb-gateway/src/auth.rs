use axum::http::HeaderMap;
use guradb_common::{digest, manifest::valid_digest, Error, Result};
use serde::Deserialize;
use std::path::Path;
use tokio::io::AsyncReadExt;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Principal {
    pub token_sha256: String,
    pub tenant_id: String,
    pub principal_id: String,
    pub datasets: Vec<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Auth {
    principals: Vec<Principal>,
}
pub async fn load(path: &Path) -> Result<Vec<Principal>> {
    let file = tokio::fs::File::open(path).await.map_err(|_| invalid())?;
    let mut bytes = Vec::new();
    file.take(65537)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| invalid())?;
    if bytes.len() > 65536 {
        return Err(invalid());
    }
    let auth: Auth = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
    if auth.principals.is_empty() || auth.principals.len() > 64 {
        return Err(invalid());
    }
    let mut tokens = std::collections::HashSet::new();
    for principal in &auth.principals {
        if !valid_digest(&principal.token_sha256)
            || principal.tenant_id.is_empty()
            || principal.principal_id.is_empty()
            || principal.tenant_id.len() > 128
            || principal.principal_id.len() > 128
            || principal.datasets.len() > 16
            || principal
                .datasets
                .iter()
                .any(|id| uuid::Uuid::parse_str(id).is_err())
            || !tokens.insert(principal.token_sha256.clone())
        {
            return Err(invalid());
        }
    }
    Ok(auth.principals)
}
fn invalid() -> Error {
    Error::new(
        "auth_unavailable",
        "authorization configuration unavailable",
    )
}
pub async fn authenticate(path: &Path, headers: &HeaderMap) -> Result<Principal> {
    let token = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .filter(|v| !v.is_empty() && v.len() <= 512)
        .ok_or_else(|| Error::new("unauthorized", "Bearer authentication required"))?;
    let hash = digest(token.as_bytes());
    load(path)
        .await?
        .into_iter()
        .find(|principal| {
            principal
                .token_sha256
                .bytes()
                .zip(hash.bytes())
                .fold(0_u8, |diff, (a, b)| diff | (a ^ b))
                == 0
        })
        .ok_or_else(|| Error::new("unauthorized", "invalid authentication"))
}
