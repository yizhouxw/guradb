use bytes::{Bytes, BytesMut};
use futures::StreamExt;
use guradb_common::{
    digest,
    manifest::{Backend, Fragment},
    Error, Result,
};
use object_store::{aws::AmazonS3Builder, path::Path as ObjectPath, GetOptions, ObjectStore};
use std::{
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio_util::sync::CancellationToken;

#[derive(Clone)]
pub enum Source {
    Local(PathBuf),
    S3(Arc<dyn ObjectStore>),
}

impl Source {
    pub fn new(backend: &Backend) -> Result<Self> {
        match backend {
            Backend::Local { root } => {
                Ok(Self::Local(std::fs::canonicalize(root).map_err(|_| {
                    Error::new("invalid_config", "local root is unavailable")
                })?))
            }
            Backend::S3 {
                bucket,
                region,
                endpoint,
                allow_http,
            } => {
                let key = std::env::var("AWS_ACCESS_KEY_ID")
                    .map_err(|_| Error::new("invalid_config", "missing S3 credentials"))?;
                let secret = std::env::var("AWS_SECRET_ACCESS_KEY")
                    .map_err(|_| Error::new("invalid_config", "missing S3 credentials"))?;
                let mut builder = AmazonS3Builder::new()
                    .with_bucket_name(bucket)
                    .with_region(region)
                    .with_endpoint(endpoint)
                    .with_allow_http(*allow_http)
                    .with_access_key_id(key)
                    .with_secret_access_key(secret);
                if let Ok(token) = std::env::var("AWS_SESSION_TOKEN") {
                    builder = builder.with_token(token);
                }
                Ok(Self::S3(Arc::new(builder.build().map_err(|_| {
                    Error::new("invalid_config", "invalid S3 backend")
                })?)))
            }
        }
    }

    pub async fn read(&self, file: &Fragment, cancel: &CancellationToken) -> Result<Bytes> {
        if cancel.is_cancelled() {
            return Err(Error::new("cancelled", "query cancelled"));
        }
        let unavailable = || Error::new("source_unavailable", "fixed source object is unavailable");
        let invalid = || {
            Error::new(
                "source_invalid",
                "fixed object size or SHA-256 differs from manifest",
            )
        };
        let bytes = match self {
            Self::Local(root) => {
                let mut path = root.clone();
                for part in Path::new(&file.key).components() {
                    path.push(part);
                    if tokio::fs::symlink_metadata(&path)
                        .await
                        .map_err(|_| unavailable())?
                        .file_type()
                        .is_symlink()
                    {
                        return Err(Error::new(
                            "source_invalid",
                            "symlink objects are not allowed",
                        ));
                    }
                }
                let real = tokio::fs::canonicalize(&path)
                    .await
                    .map_err(|_| unavailable())?;
                if !real.starts_with(root) {
                    return Err(invalid());
                }
                if !tokio::fs::metadata(&real)
                    .await
                    .map_err(|_| unavailable())?
                    .is_file()
                {
                    return Err(invalid());
                }
                // Bound before allocation and also during reading, including concurrent growth.
                let handle = tokio::fs::File::open(real)
                    .await
                    .map_err(|_| unavailable())?;
                use tokio::io::AsyncReadExt;
                let mut buffer = Vec::new();
                let mut reader = handle.take((file.size_bytes + 1) as u64);
                tokio::select! {
                    _ = cancel.cancelled() => return Err(Error::new("cancelled", "query cancelled")),
                    result = reader.read_to_end(&mut buffer) => { result.map_err(|_| unavailable())?; }
                }
                Bytes::from(buffer)
            }
            Self::S3(store) => {
                let options = GetOptions {
                    version: file.version_id.clone(),
                    ..Default::default()
                };
                let path = ObjectPath::from(file.key.as_str());
                let result = tokio::select! {
                    _ = cancel.cancelled() => return Err(Error::new("cancelled", "query cancelled")),
                    value = store.get_opts(&path, options) => value.map_err(|_| unavailable())?,
                };
                if result.meta.size != file.size_bytes as u64 {
                    return Err(invalid());
                }
                let mut stream = result.into_stream();
                let mut output = BytesMut::new();
                loop {
                    let item = tokio::select! { _ = cancel.cancelled() => return Err(Error::new("cancelled", "query cancelled")), value = stream.next() => value };
                    let Some(item) = item else { break };
                    let chunk = item.map_err(|_| unavailable())?;
                    if output.len().saturating_add(chunk.len()) > file.size_bytes {
                        return Err(invalid());
                    }
                    output.extend_from_slice(&chunk);
                }
                output.freeze()
            }
        };
        if bytes.len() != file.size_bytes || digest(&bytes) != file.sha256 {
            return Err(invalid());
        }
        Ok(bytes)
    }
}

#[cfg(test)]
#[path = "../tests/unit/storage.rs"]
mod tests;

#[cfg(test)]
#[path = "../tests/unit/stream.rs"]
mod stream_tests;

pub mod fixed_request;

#[cfg(test)]
#[path = "../tests/unit/fixed_request.rs"]
mod fixed_request_tests;
