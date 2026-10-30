//! Full-corpus exact vector ranking and rank-based fusion, with no early TopK.
use crate::{features, media, search, source, Config, Error, Result, RESULT_LIMIT};
use serde_json::json;
use std::{collections::BTreeSet, path::PathBuf};
pub(crate) struct Request {
    pub(crate) features: PathBuf,
    pub(crate) pin: String,
    pub(crate) query: PathBuf,
    pub(crate) k: usize,
    pub(crate) text: Option<String>,
}
pub(crate) fn parse(args: &[String]) -> Result<Option<Request>> {
    let hybrid = args.get(1).is_some_and(|s| s == "hybrid");
    if !hybrid && args.get(1).is_none_or(|s| s != "vector") {
        return Ok(None);
    }
    let expected = if hybrid { 14 } else { 12 };
    if args.len() != expected
        || args[2] != "--config"
        || args[4] != "--features"
        || args[6] != "--features-sha256"
        || args[8] != "--query"
        || args[10] != "--top-k"
        || (hybrid && args[12] != "--text-query")
    {
        return Err(Error::new("invalid_config","vector/hybrid requires --config --features --features-sha256 --query --top-k [--text-query]"));
    }
    let k = args[11].parse::<usize>().unwrap_or(0);
    if !(1..=20).contains(&k)
        || args[7].len() != 64
        || !args[7]
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(Error::new(
            "invalid_config",
            "invalid top-k or feature SHA256",
        ));
    }
    Ok(Some(Request {
        features: PathBuf::from(&args[5]),
        pin: args[7].clone(),
        query: PathBuf::from(&args[9]),
        k,
        text: if hybrid { Some(args[13].clone()) } else { None },
    }))
}
pub(crate) async fn run(config: Config, request: Request) -> Result<String> {
    let terms = match &request.text {
        Some(q) => search::terms(q)?,
        None => Vec::new(),
    };
    let (docs, assets) = {
        let bytes = source::snapshot(&config.source, &config.sha256).await?;
        let (schema, batches) = source::decode(bytes)?;
        media::reject_v2(&schema)?;
        let (docs, has_media) = search::documents(&schema, &batches, &terms)?;
        let assets = if has_media {
            Some(media::assets(&schema, &batches)?)
        } else {
            None
        };
        (docs, assets)
    };
    let ids = docs.iter().map(|d| d.id.clone()).collect::<BTreeSet<_>>();
    let features = features::load(&request.features, &request.pin, &config.sha256, &ids).await?;
    let (query, query_sha) =
        features::query(&request.query, &config.sha256, &features.space).await?;
    let mut vectors = Vec::new();
    for (i, d) in docs.iter().enumerate() {
        let value = features
            .rows
            .get(&d.id)
            .ok_or_else(|| Error::new("invalid_features", "missing document vector"))?;
        let score = value
            .iter()
            .zip(&query)
            .map(|(a, b)| a * b)
            .sum::<f64>()
            .clamp(-1.0, 1.0);
        let score = if score == 0.0 { 0.0 } else { score };
        vectors.push((i, score));
    }
    vectors
        .sort_by(|(a, sa), (b, sb)| sb.total_cmp(sa).then_with(|| docs[*a].id.cmp(&docs[*b].id)));
    let bm = if request.text.is_some() {
        Some(search::scores(&docs, &terms)?)
    } else {
        None
    };
    let mut vector_rank = vec![0usize; docs.len()];
    let mut vector_score = vec![0.0; docs.len()];
    for (rank, &(i, score)) in vectors.iter().enumerate() {
        vector_rank[i] = rank + 1;
        vector_score[i] = score;
    }
    let mut bm_rank = vec![None; docs.len()];
    let mut bm_score = vec![None; docs.len()];
    if let Some(bm) = &bm {
        for (rank, &(i, score)) in bm.ranked.iter().enumerate() {
            bm_rank[i] = Some(rank + 1);
            bm_score[i] = Some(score);
        }
    }
    let mut ranked = if bm.is_some() {
        docs.iter()
            .enumerate()
            .map(|(i, _)| {
                (
                    i,
                    bm_rank[i].map_or(0.0, |r| 1.0 / (60.0 + r as f64))
                        + 1.0 / (60.0 + vector_rank[i] as f64),
                )
            })
            .collect::<Vec<_>>()
    } else {
        vectors
    };
    ranked.sort_by(|(a, sa), (b, sb)| sb.total_cmp(sa).then_with(|| docs[*a].id.cmp(&docs[*b].id)));
    let mut hits = Vec::new();
    for &(i, score) in ranked.iter().take(request.k) {
        let d = &docs[i];
        let identity = match (&assets, d.asset_id) {
            (Some(assets), Some(id)) => {
                let a = assets.get(&id).ok_or_else(|| {
                    Error::new("invalid_media_binding", "missing asset description")
                })?;
                json!({"asset_id":id.to_string(),"image_path":a.path,"media_sha256":a.sha256,"media_bytes":a.size,"media_version":1})
            }
            _ => serde_json::Value::Null,
        };
        hits.push(json!({"doc_id":d.id,"text":d.text,"score":score,"vector_score":vector_score[i],"vector_rank":vector_rank[i],"bm25_score":bm_score[i],"bm25_rank":bm_rank[i],"bm25_rrf":bm_rank[i].map_or(0.0,|r|1.0/(60.0+r as f64)),"vector_rrf":1.0/(60.0+vector_rank[i]as f64),"media":identity}));
    }
    source::snapshot(&config.source, &config.sha256).await?;
    features::snapshot(&request.features, &request.pin).await?;
    let output=serde_json::to_string(&json!({"source_sha256":config.sha256,"features_sha256":request.pin,"query_sha256":query_sha,"space":features.space,"model_effectiveness":"NOT_VERIFIED; caller declaration only","algorithm":if bm.is_some(){"rrf-k60-full-corpus-v1"}else{"exact-cosine-scaled-f64-v1"},"rrf_k":60,"documents":docs.len(),"top_k":request.k,"bm25_matches":bm.as_ref().map_or(0,|x|x.ranked.len()),"hits":hits,"truncated":ranked.len()>request.k})).map_err(|_|Error::new("output_failed","cannot encode vector result"))?;
    if output.len() > RESULT_LIMIT {
        return Err(Error::new("resource_limit", "vector output exceeds 2 MiB"));
    }
    Ok(output)
}
