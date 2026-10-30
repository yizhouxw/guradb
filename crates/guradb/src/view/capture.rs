use super::state::{self, Store};
use crate::{media, search, source, Config, Error, Result};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};

pub async fn config(path: &Path) -> Result<Config> {
    let mut c: Config = serde_json::from_slice(&source::read_bounded(path, 16384).await?)
        .map_err(|_| Error::new("invalid_config", "invalid view input config"))?;
    if !state::digest(&c.sha256) || !(1..=10000).contains(&c.timeout_ms) {
        return Err(Error::new("invalid_config", "invalid input SHA or timeout"));
    }
    if c.source.is_relative() {
        c.source = path.parent().unwrap_or(Path::new(".")).join(&c.source);
    }
    Ok(c)
}
pub async fn validate(
    c: &Config,
    root: &Path,
) -> Result<(bytes::Bytes, BTreeMap<i64, media::Asset>, BTreeSet<String>)> {
    let b = source::snapshot(&c.source, &c.sha256).await?;
    let (schema, batches) = source::decode(b.clone())?;
    let (docs, has_media) = search::documents(&schema, &batches, &[])?;
    if !has_media {
        return Err(Error::new(
            "unsupported_view_input",
            "view requires generic text and a supported media binding",
        ));
    }
    let assets = media::assets(&schema, &batches)?;
    for a in assets.values() {
        let p = media::checked_bytes(root, a)?;
        if hex::encode(Sha256::digest(&p)) != a.sha256 {
            return Err(Error::new(
                "media_changed",
                "captured media SHA differs from input",
            ));
        }
    }
    Ok((b, assets, docs.into_iter().map(|d| d.id).collect()))
}
pub async fn capture(
    s: &Store,
    c: &Config,
    origin: &Path,
    record: &state::Record,
    feature_path: Option<&Path>,
) -> Result<()> {
    let (b, assets, ids) = validate(c, origin).await?;
    if feature_path.is_some() && assets.values().any(|a| a.version == 2) {
        return Err(Error::new(
            "unsupported_media_contract",
            "media v2 cannot bind feature views",
        ));
    }
    let dir = s.root.join(".staging");
    fs::create_dir(&dir).map_err(|_| state::invalid())?;
    fs::create_dir(dir.join("images")).map_err(|_| state::invalid())?;
    if assets.values().any(|a| a.kind == "audio/wav") {
        fs::create_dir(dir.join("audio")).map_err(|_| state::invalid())?;
    }
    state::write(&dir.join("records.parquet"), &b)?;
    for a in assets.into_values() {
        let p = media::checked_bytes(origin, &a)?;
        if hex::encode(Sha256::digest(&p)) != a.sha256 {
            return Err(Error::new("media_changed", "media changed during capture"));
        }
        state::write(&dir.join(a.path), &p)?;
    }
    if let (Some(bound), Some(path)) = (&record.features, feature_path) {
        let loaded = crate::features::load(path, &bound.sha256, &c.sha256, &ids).await?;
        if loaded.space != bound.space {
            return Err(Error::new(
                "space_mismatch",
                "captured feature space changed",
            ));
        }
        let bytes = crate::features::snapshot(path, &bound.sha256).await?;
        state::write(&dir.join("features.jsonl"), &bytes)?;
        crate::features::snapshot(path, &bound.sha256).await?;
    }
    let config =
        serde_json::json!({"source":"records.parquet","sha256":c.sha256,"timeout_ms":10000});
    state::write(
        &dir.join("config.json"),
        &serde_json::to_vec(&config).map_err(|_| state::invalid())?,
    )?;
    source::snapshot(&c.source, &c.sha256).await?;
    state::sync_dir(&dir.join("images"))?;
    if dir.join("audio").exists() {
        state::sync_dir(&dir.join("audio"))?;
    }
    state::sync_dir(&dir)?;
    fs::rename(&dir, s.object(&record.id)).map_err(|_| state::invalid())?;
    state::sync_dir(&s.root.join("objects"))?;
    state::sync_dir(&s.root)
}
pub async fn owned(s: &Store, record: &state::Record) -> Result<(Config, PathBuf)> {
    let p = s.object(&record.id);
    state::directory(&p)?;
    state::regular(&p.join("config.json"))?;
    state::regular(&p.join("records.parquet"))?;
    let c = config(&p.join("config.json")).await?;
    if c.sha256 != record.source() || c.source != p.join("records.parquet") || c.timeout_ms != 10000
    {
        return Err(state::invalid());
    }
    let (_, assets, ids) = validate(&c, &p).await?;
    if record.features.is_some() && assets.values().any(|a| a.version == 2) {
        return Err(Error::new(
            "unsupported_media_contract",
            "media v2 cannot bind feature views",
        ));
    }
    if let Some(bound) = &record.features {
        state::regular(&p.join("features.jsonl"))?;
        let loaded =
            crate::features::load(&p.join("features.jsonl"), &bound.sha256, &c.sha256, &ids)
                .await?;
        if loaded.space != bound.space {
            return Err(Error::new(
                "space_mismatch",
                "owned space differs from view",
            ));
        }
    }
    Ok((c, p))
}
