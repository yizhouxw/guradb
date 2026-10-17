pub mod manifest;
pub mod protocol;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub type Result<T> = std::result::Result<T, Error>;

/// Optional fields may be omitted; explicit JSON null is not a value in v1.
pub fn non_null<'de, D, T>(deserializer: D) -> std::result::Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    T::deserialize(deserializer).map(Some)
}

#[derive(Clone, Debug, Serialize)]
pub struct Error {
    pub code: String,
    pub message: String,
    pub retryable: bool,
    pub request_id: String,
}

impl Error {
    pub fn new(code: &str, message: &str) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            retryable: false,
            request_id: Uuid::new_v4().to_string(),
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for Error {}

pub fn digest(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    hex::encode(Sha256::digest(bytes))
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Limits {
    pub scan_bytes: usize,
    pub decoded_bytes: usize,
    pub pool_bytes: usize,
    pub result_bytes: usize,
    pub max_rows: usize,
    pub concurrent_queries: usize,
    pub handles: usize,
    pub timeout_ms: u64,
    pub retention_seconds: u64,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            scan_bytes: 32 << 20,
            decoded_bytes: 64 << 20,
            pool_bytes: 32 << 20,
            result_bytes: 2 << 20,
            max_rows: 1000,
            concurrent_queries: 2,
            handles: 32,
            timeout_ms: 10_000,
            retention_seconds: 60,
        }
    }
}
impl Limits {
    pub fn validate(&self) -> Result<()> {
        let hard = Self::default();
        if self.scan_bytes == 0
            || self.scan_bytes > hard.scan_bytes
            || self.decoded_bytes == 0
            || self.decoded_bytes > hard.decoded_bytes
            || self.pool_bytes == 0
            || self.pool_bytes > hard.pool_bytes
            || self.result_bytes == 0
            || self.result_bytes > hard.result_bytes
            || self.max_rows == 0
            || self.max_rows > hard.max_rows
            || self.concurrent_queries == 0
            || self.concurrent_queries > hard.concurrent_queries
            || self.handles == 0
            || self.handles > hard.handles
            || self.timeout_ms == 0
            || self.timeout_ms > hard.timeout_ms
            || self.retention_seconds == 0
            || self.retention_seconds > hard.retention_seconds
        {
            return Err(Error::new(
                "invalid_config",
                "limits must be positive and within M0 hard caps",
            ));
        }
        Ok(())
    }
}

/// Versioned, typed, length-prefixed identity encoding; never delimiter joins.
pub fn encode_key(parts: &[(&str, &[u8])]) -> Result<Vec<u8>> {
    let mut out = vec![1];
    out.extend_from_slice(
        &(u32::try_from(parts.len())
            .map_err(|_| Error::new("invalid_key", "too many key parts"))?)
        .to_be_bytes(),
    );
    for (kind, bytes) in parts {
        let tag = match *kind {
            "text" => 1,
            "int8" if bytes.len() == 8 => 2,
            "uuid" if bytes.len() == 16 => 3,
            _ => return Err(Error::new("invalid_key", "invalid key type/width")),
        };
        if tag == 1 && std::str::from_utf8(bytes).is_err() {
            return Err(Error::new("invalid_key", "text key must be UTF-8"));
        }
        out.push(tag);
        out.extend_from_slice(
            &(u32::try_from(bytes.len())
                .map_err(|_| Error::new("invalid_key", "key part too long"))?)
            .to_be_bytes(),
        );
        out.extend_from_slice(bytes);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn key_vectors_are_typed_and_unambiguous() {
        assert_eq!(
            hex::encode(encode_key(&[("text", b"ab")]).unwrap()),
            "010000000101000000026162"
        );
        assert_ne!(
            encode_key(&[("text", b"a|b"), ("text", b"c")]).unwrap(),
            encode_key(&[("text", b"a"), ("text", b"b|c")]).unwrap()
        );
        assert_ne!(
            encode_key(&[("text", b"1")]).unwrap(),
            encode_key(&[("int8", &1_i64.to_be_bytes())]).unwrap()
        );
        assert!(encode_key(&[("int8", b"1")]).is_err());
    }
}
