//! Fixed explicit membership and asset-group split over the one source snapshot.
use crate::{media, search, source, Config, Error, Result, RESULT_LIMIT};
use serde::Deserialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, path::PathBuf};

const SELECTION_LIMIT: usize = 64 << 10;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Selection {
    format_version: u32,
    source_sha256: String,
    seed: u32,
    doc_ids: Vec<String>,
}
fn invalid(message: &str) -> Error {
    Error::new("invalid_sample_selection", message)
}

pub(crate) async fn run(config: Config, request: PathBuf, root: PathBuf) -> Result<String> {
    let raw = source::read_bounded(&request, SELECTION_LIMIT).await?;
    let pin = hex::encode(Sha256::digest(&raw));
    let selection: Selection = serde_json::from_slice(&raw)
        .map_err(|_| invalid("invalid or unsupported selection JSON"))?;
    if selection.format_version != 1 {
        return Err(invalid("unsupported sample format version"));
    }
    if selection.source_sha256 != config.sha256 {
        return Err(Error::new(
            "source_mismatch",
            "sample source differs from config",
        ));
    }
    if selection.doc_ids.is_empty() || selection.doc_ids.len() > 200 {
        return Err(invalid("selection requires 1..200 unique document IDs"));
    }
    let mut selected = BTreeSet::new();
    for id in &selection.doc_ids {
        if id.is_empty()
            || id.len() > 64
            || !id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
            || !selected.insert(id.as_str())
        {
            return Err(invalid("invalid or duplicate document ID"));
        }
    }
    let bytes = source::snapshot(&config.source, &config.sha256).await?;
    let (schema, batches) = source::decode(bytes)?;
    let (docs, has_media) = search::documents(&schema, &batches, &[])?;
    if !has_media {
        return Err(invalid("sampling requires the version-1 media corpus"));
    }
    let descriptions = media::assets(&schema, &batches)?;
    let mut docs: Vec<_> = docs
        .into_iter()
        .filter(|d| selected.contains(d.id.as_str()))
        .collect();
    if docs.len() != selected.len() {
        return Err(invalid("selected document is absent from this source"));
    }
    docs.sort_by(|a, b| a.id.cmp(&b.id));
    let groups: BTreeSet<_> = docs.iter().filter_map(|d| d.image_id).collect();
    if groups.len() < 2 {
        return Err(invalid(
            "at least two independent asset groups are required",
        ));
    }
    let mut ranked = Vec::new();
    for id in groups {
        let asset = descriptions
            .get(&id)
            .ok_or_else(|| invalid("missing asset binding"))?;
        let bytes = crate::media_path::read(&root, &format!("{id:012}.jpg"), asset.size)?;
        if hex::encode(Sha256::digest(&bytes)) != asset.sha256 {
            return Err(Error::new(
                "media_changed",
                "sample media differs from bound source",
            ));
        }
        let input = format!("guradb-sample-group-v1\n{}\n{id}\n", selection.seed);
        ranked.push((hex::encode(Sha256::digest(input.as_bytes())), id));
    }
    ranked.sort();
    let validation_id = ranked[0].1;
    let mut train = Vec::new();
    let mut validation = Vec::new();
    for doc in &docs {
        let id = doc.image_id.ok_or_else(|| invalid("missing asset ID"))?;
        let asset = descriptions
            .get(&id)
            .ok_or_else(|| invalid("missing asset binding"))?;
        let row = json!({"doc_id":doc.id,"text":doc.text,"text_version":1,
            "media":{"asset_id":id.to_string(),"image_path":asset.path,"media_version":1,
                     "media_bytes":asset.size,"media_sha256":asset.sha256}});
        if id == validation_id {
            validation.push(row);
        } else {
            train.push(row);
        }
    }
    source::snapshot(&config.source, &config.sha256).await?;
    if hex::encode(Sha256::digest(
        source::read_bounded(&request, SELECTION_LIMIT).await?,
    )) != pin
    {
        return Err(invalid("selection changed before publication"));
    }
    let groups: Vec<_> = ranked
        .iter()
        .map(|(hash, id)| {
            json!({"asset_id":id.to_string(),"sha256":hash,
        "split":if *id==validation_id{"validation"}else{"train"}})
        })
        .collect();
    let output = serde_json::to_string(&json!({"format_version":1,"source_sha256":config.sha256,
        "selection_sha256":pin,"selection":"explicit-doc-ids-v1","seed":selection.seed,
        "algorithm":"asset-sha256-first-validation-v1","order":"ascii-doc-id","model":"not_used",
        "selected_doc_ids":docs.iter().map(|d| &d.id).collect::<Vec<_>>(),"groups":groups,
        "train":train,"validation":validation}))
    .map_err(|_| Error::new("output_failed", "cannot encode fixed sample"))?;
    if output.len() > RESULT_LIMIT {
        return Err(Error::new(
            "resource_limit",
            "sample output exceeds JSON budget",
        ));
    }
    Ok(output)
}
