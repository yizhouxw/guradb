//! Explicit pinned external feature bytes; no model execution or latest lookup.
use crate::{source, Error, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};
pub(crate) const FEATURE_LIMIT: usize = 8 << 20;
#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Space {
    pub(crate) id: String,
    pub(crate) dimensions: usize,
    dtype: String,
    metric: String,
    normalization: String,
    origin: String,
    model_id: String,
    model_revision: String,
    preprocessing_id: String,
    license: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Header {
    format_version: u32,
    source_sha256: String,
    documents: usize,
    space: Space,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Row {
    doc_id: String,
    vector: Vec<f64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Query {
    format_version: u32,
    source_sha256: String,
    space: Space,
    vector: Vec<f64>,
}
pub(crate) struct Set {
    pub(crate) space: Space,
    pub(crate) rows: BTreeMap<String, Vec<f64>>,
}
fn invalid() -> Error {
    Error::new(
        "invalid_features",
        "invalid feature format, dimension, identity or version",
    )
}
fn validate_space(s: &Space) -> Result<()> {
    if s.id.is_empty()
        || s.id.len() > 64
        || !s
            .id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
        || !(1..=1024).contains(&s.dimensions)
        || s.dtype != "f64"
        || s.metric != "cosine"
        || s.normalization != "l2-scaled-f64-v1"
        || !["numerical-fixture", "external-declared"].contains(&s.origin.as_str())
        || [
            &s.model_id,
            &s.model_revision,
            &s.preprocessing_id,
            &s.license,
        ]
        .iter()
        .any(|v| v.is_empty() || v.len() > 256 || v.chars().any(char::is_control))
    {
        return Err(invalid());
    }
    Ok(())
}
pub(crate) fn normalize(mut values: Vec<f64>, dimensions: usize) -> Result<Vec<f64>> {
    if values.len() != dimensions || values.iter().any(|v| !v.is_finite()) {
        return Err(Error::new(
            "invalid_vector",
            "vector requires finite numbers and exact dimensions",
        ));
    }
    let maximum = values.iter().map(|v| v.abs()).fold(0.0, f64::max);
    if maximum == 0.0 {
        return Err(Error::new("invalid_vector", "zero vector is unsupported"));
    }
    let norm = values
        .iter()
        .map(|v| {
            let x = v / maximum;
            x * x
        })
        .sum::<f64>()
        .sqrt();
    for value in &mut values {
        *value = (*value / maximum) / norm;
    }
    Ok(values)
}
pub(crate) async fn snapshot(path: &Path, expected: &str) -> Result<Vec<u8>> {
    let bytes = source::read_bounded(path, FEATURE_LIMIT).await?;
    if hex::encode(Sha256::digest(&bytes)) != expected {
        return Err(Error::new(
            "feature_changed",
            "feature SHA differs from pinned request",
        ));
    }
    Ok(bytes)
}
pub(crate) async fn load(
    path: &Path,
    pin: &str,
    source_sha: &str,
    ids: &BTreeSet<String>,
) -> Result<Set> {
    let bytes = snapshot(path, pin).await?;
    let text = std::str::from_utf8(&bytes).map_err(|_| invalid())?;
    let mut lines = text.lines();
    let header = lines.next().ok_or_else(invalid)?;
    if header.len() > 16384 {
        return Err(Error::new(
            "resource_limit",
            "feature header exceeds 16 KiB",
        ));
    }
    let header: Header = serde_json::from_str(header).map_err(|_| invalid())?;
    if header.format_version != 1 || header.documents != ids.len() {
        return Err(invalid());
    }
    if header.source_sha256 != source_sha {
        return Err(Error::new(
            "source_mismatch",
            "features belong to another corpus",
        ));
    }
    validate_space(&header.space)?;
    let mut rows = BTreeMap::new();
    for line in lines {
        if line.len() > 65536 {
            return Err(Error::new("resource_limit", "feature row exceeds bounds"));
        }
        if line.trim().is_empty() {
            continue;
        }
        let row: Row = serde_json::from_str(line).map_err(|_| invalid())?;
        if !ids.contains(&row.doc_id) || rows.contains_key(&row.doc_id) {
            return Err(invalid());
        }
        rows.insert(row.doc_id, normalize(row.vector, header.space.dimensions)?);
    }
    if rows.keys().cloned().collect::<BTreeSet<_>>() != *ids {
        return Err(invalid());
    }
    Ok(Set {
        space: header.space,
        rows,
    })
}
pub(crate) async fn query(
    path: &Path,
    source_sha: &str,
    space: &Space,
) -> Result<(Vec<f64>, String)> {
    let bytes = source::read_bounded(path, 65536).await?;
    let digest = hex::encode(Sha256::digest(&bytes));
    let query: Query = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
    if query.format_version != 1 {
        return Err(invalid());
    }
    if query.source_sha256 != source_sha {
        return Err(Error::new(
            "source_mismatch",
            "query belongs to another corpus",
        ));
    }
    if query.space != *space {
        return Err(Error::new(
            "space_mismatch",
            "query and feature space descriptions differ",
        ));
    }
    Ok((normalize(query.vector, space.dimensions)?, digest))
}

#[cfg(test)]
mod tests {
    use super::normalize;
    #[test]
    fn scaled_normalization_handles_geometry_extreme_and_subnormal() {
        let v = normalize(vec![3.0, 4.0], 2).unwrap();
        assert!((v[0] - 0.6).abs() < 1e-15);
        assert!((v[1] - 0.8).abs() < 1e-15);
        for value in [f64::MAX, f64::from_bits(1)] {
            let v = normalize(vec![value, value], 2).unwrap();
            assert!(v.iter().all(|x| x.is_finite()));
            assert!((v[0] - std::f64::consts::FRAC_1_SQRT_2).abs() < 1e-15);
            assert_eq!(v[0], v[1]);
        }
    }
    #[test]
    fn zero_nonfinite_and_wrong_dimensions_reject() {
        for v in [
            vec![0.0, -0.0],
            vec![f64::NAN, 1.0],
            vec![f64::INFINITY, 1.0],
            vec![1.0],
        ] {
            assert!(normalize(v, 2).is_err());
        }
    }
}
