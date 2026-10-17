use crate::{Error, Result};
use serde::Deserialize;
use std::collections::HashSet;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ManifestRef {
    pub path: String,
    pub sha256: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Field {
    pub name: String,
    pub data_type: String,
    pub nullable: bool,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Backend {
    Local {
        root: String,
    },
    S3 {
        bucket: String,
        region: String,
        endpoint: String,
        #[serde(default)]
        allow_http: bool,
    },
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Fragment {
    pub fragment_id: String,
    pub key: String,
    pub size_bytes: usize,
    pub sha256: String,
    #[serde(default, deserialize_with = "crate::non_null")]
    pub version_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub schema_version: u32,
    pub dataset_id: String,
    pub table_name: String,
    pub schema: Vec<Field>,
    pub backend: Backend,
    pub files: Vec<Fragment>,
    pub retention_mode: String,
}

pub fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 63
        && value
            .bytes()
            .enumerate()
            .all(|(n, b)| b.is_ascii_lowercase() || b == b'_' || (n > 0 && b.is_ascii_digit()))
}
pub fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

impl Manifest {
    pub fn validate(&self) -> Result<()> {
        let bad = || {
            Error::new(
                "invalid_manifest",
                "manifest identity, schema or file constraints are invalid",
            )
        };
        if self.schema_version != 1
            || uuid::Uuid::parse_str(&self.dataset_id).is_err()
            || !identifier(&self.table_name)
            || self.schema.is_empty()
            || self.schema.len() > 64
            || self.files.is_empty()
            || self.files.len() > 32
            || self.retention_mode != "best-effort"
        {
            return Err(bad());
        }
        let mut names = HashSet::new();
        for field in &self.schema {
            if !identifier(&field.name)
                || !names.insert(&field.name)
                || !["int8", "text", "bool"].contains(&field.data_type.as_str())
            {
                return Err(bad());
            }
        }
        let mut ids = HashSet::new();
        let mut keys = HashSet::new();
        for file in &self.files {
            if !identifier(&file.fragment_id)
                || !ids.insert(&file.fragment_id)
                || !keys.insert(&file.key)
                || file.key.is_empty()
                || file.key.starts_with('/')
                || file.key.contains('\\')
                || file
                    .key
                    .split('/')
                    .any(|x| x.is_empty() || x == "." || x == "..")
                || file.size_bytes == 0
                || file.size_bytes > 32 << 20
                || !valid_digest(&file.sha256)
                || file.version_id.as_ref().is_some_and(String::is_empty)
            {
                return Err(bad());
            }
            if matches!(self.backend, Backend::Local { .. }) && file.version_id.is_some() {
                return Err(bad());
            }
        }
        Ok(())
    }
}
