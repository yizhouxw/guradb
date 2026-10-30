//! Exact bounded BM25 over one immutable corpus, without a persistent index.
use crate::{media, source, Config, Error, Result, RESULT_LIMIT};
use arrow::{
    array::{Int64Array, StringArray},
    datatypes::{DataType, SchemaRef},
    record_batch::RecordBatch,
};
use serde_json::json;
use std::collections::BTreeSet;
const K1: f64 = 1.2;
const B: f64 = 0.75;
pub(crate) struct Doc {
    pub(crate) id: String,
    pub(crate) text: String,
    pub(crate) dl: usize,
    pub(crate) tf: [usize; 8],
    pub(crate) image_id: Option<i64>,
}
fn invalid() -> Error {
    Error::new(
        "invalid_search_input",
        "invalid text document, identity or analyzer input",
    )
}
fn printable(text: &str) -> bool {
    text.bytes()
        .all(|b| b.is_ascii_graphic() || matches!(b, b' ' | b'\t' | b'\n' | b'\r'))
}
fn words(text: &str) -> impl Iterator<Item = &str> {
    text.split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|s| !s.is_empty())
}
pub(crate) fn terms(query: &str) -> Result<Vec<String>> {
    if query.len() > 256 || !printable(query) {
        return Err(Error::new(
            "invalid_search_query",
            "query must be bounded printable ASCII",
        ));
    }
    let lower = query.to_ascii_lowercase();
    let tokens: Vec<_> = words(&lower).collect();
    if tokens.is_empty() || tokens.len() > 8 || tokens.iter().any(|t| t.len() > 64) {
        return Err(Error::new(
            "invalid_search_query",
            "query needs 1..8 words of at most 64 bytes",
        ));
    }
    Ok(tokens
        .into_iter()
        .map(str::to_owned)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect())
}
fn column(schema: &SchemaRef, name: &str, kind: DataType) -> Result<usize> {
    let indexes: Vec<_> = schema
        .fields()
        .iter()
        .enumerate()
        .filter(|(_, f)| f.name() == name)
        .collect();
    if indexes.len() != 1 || indexes[0].1.data_type() != &kind {
        return Err(Error::new(
            "unsupported_search_contract",
            "search requires typed text-version-1 columns",
        ));
    }
    Ok(indexes[0].0)
}
pub(crate) fn documents(
    schema: &SchemaRef,
    batches: &[RecordBatch],
    terms: &[String],
) -> Result<(Vec<Doc>, bool)> {
    let has_media = schema.fields().iter().any(|f| {
        [
            "image_id",
            "image_path",
            "media_version",
            "media_bytes",
            "media_sha256",
        ]
        .contains(&f.name().as_str())
    });
    let allowed = [
        "doc_id",
        "text",
        "text_version",
        "image_id",
        "image_path",
        "media_version",
        "media_bytes",
        "media_sha256",
    ];
    if schema.fields().len() != if has_media { 8 } else { 3 }
        || schema
            .fields()
            .iter()
            .any(|f| !allowed.contains(&f.name().as_str()))
    {
        return Err(Error::new(
            "unsupported_search_contract",
            "unsupported text corpus layout",
        ));
    }
    let id = column(schema, "doc_id", DataType::Utf8)?;
    let text = column(schema, "text", DataType::Utf8)?;
    let version = column(schema, "text_version", DataType::Int64)?;
    let image = if has_media {
        Some(column(schema, "image_id", DataType::Int64)?)
    } else {
        None
    };
    let count = batches.iter().map(RecordBatch::num_rows).sum::<usize>();
    if count == 0 || count > 200 {
        return Err(Error::new(
            "resource_limit",
            "search requires 1..200 documents",
        ));
    }
    if has_media {
        media::assets(schema, batches)?;
    }
    let mut docs = Vec::with_capacity(count);
    let mut seen = BTreeSet::new();
    let mut text_bytes = 0usize;
    let mut total_tokens = 0usize;
    for batch in batches {
        let ids = batch
            .column(id)
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or_else(invalid)?;
        let texts = batch
            .column(text)
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or_else(invalid)?;
        let versions = batch
            .column(version)
            .as_any()
            .downcast_ref::<Int64Array>()
            .ok_or_else(invalid)?;
        for row in 0..batch.num_rows() {
            if [id, text, version]
                .iter()
                .any(|&i| batch.column(i).is_null(row))
            {
                return Err(invalid());
            }
            if versions.value(row) != 1 {
                return Err(Error::new(
                    "unsupported_search_contract",
                    "unknown text version",
                ));
            }
            let key = ids.value(row);
            let value = texts.value(row);
            if key.is_empty()
                || key.len() > 64
                || !key
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
                || !seen.insert(key.to_owned())
            {
                return Err(invalid());
            }
            if value.len() > 8192 || !printable(value) {
                return Err(invalid());
            }
            text_bytes += value.len();
            if text_bytes > 256 << 10 {
                return Err(Error::new("resource_limit", "corpus text exceeds 256 KiB"));
            }
            let lower = value.to_ascii_lowercase();
            let mut tf = [0; 8];
            let mut dl = 0;
            for token in words(&lower) {
                if token.len() > 64 {
                    return Err(invalid());
                }
                dl += 1;
                if dl > 2048 {
                    return Err(Error::new("resource_limit", "document exceeds 2048 tokens"));
                }
                for (i, term) in terms.iter().enumerate() {
                    if token == term {
                        tf[i] += 1;
                    }
                }
            }
            if dl == 0 {
                return Err(invalid());
            }
            total_tokens += dl;
            if total_tokens > 65536 {
                return Err(Error::new("resource_limit", "corpus exceeds 65536 tokens"));
            }
            let image_id = match image {
                Some(i) => Some(
                    batch
                        .column(i)
                        .as_any()
                        .downcast_ref::<Int64Array>()
                        .ok_or_else(invalid)?
                        .value(row),
                ),
                None => None,
            };
            docs.push(Doc {
                id: key.into(),
                text: value.into(),
                dl,
                tf,
                image_id,
            });
        }
    }
    Ok((docs, has_media))
}
fn contribution(idf: f64, tf: usize, dl: usize, avgdl: f64) -> f64 {
    if tf == 0 {
        0.0
    } else {
        idf * tf as f64 * (K1 + 1.0) / (tf as f64 + K1 * (1.0 - B + B * dl as f64 / avgdl))
    }
}
pub(crate) struct Scores {
    pub(crate) ranked: Vec<(usize, f64)>,
    pub(crate) total_tokens: usize,
    pub(crate) avgdl: f64,
    pub(crate) df: Vec<usize>,
    pub(crate) idf: Vec<f64>,
}
pub(crate) fn scores(docs: &[Doc], terms: &[String]) -> Result<Scores> {
    let n = docs.len();
    let total_tokens = docs.iter().map(|d| d.dl).sum::<usize>();
    let avgdl = total_tokens as f64 / n as f64;
    let df: Vec<_> = (0..terms.len())
        .map(|i| docs.iter().filter(|d| d.tf[i] > 0).count())
        .collect();
    let idf: Vec<_> = df
        .iter()
        .map(|&f| (1.0 + (n as f64 - f as f64 + 0.5) / (f as f64 + 0.5)).ln())
        .collect();
    let mut scored = Vec::new();
    for (i, doc) in docs.iter().enumerate() {
        let score = (0..terms.len())
            .map(|t| contribution(idf[t], doc.tf[t], doc.dl, avgdl))
            .sum::<f64>();
        if !score.is_finite() {
            return Err(Error::new("execution_failed", "nonfinite BM25 score"));
        }
        if score > 0.0 {
            scored.push((i, score));
        }
    }
    scored.sort_by(|(a, sa), (b, sb)| sb.total_cmp(sa).then_with(|| docs[*a].id.cmp(&docs[*b].id)));
    Ok(Scores {
        ranked: scored,
        total_tokens,
        avgdl,
        df,
        idf,
    })
}

pub async fn run(config: Config, query: String, top_k: usize) -> Result<String> {
    let terms = terms(&query)?;
    let bytes = source::snapshot(&config.source, &config.sha256).await?;
    let (schema, batches) = source::decode(bytes)?;
    let (docs, has_media) = documents(&schema, &batches, &terms)?;
    let media = if has_media {
        Some(media::assets(&schema, &batches)?)
    } else {
        None
    };
    let n = docs.len();
    let Scores {
        ranked: scored,
        total_tokens,
        avgdl,
        df,
        idf,
    } = scores(&docs, &terms)?;
    let truncated = scored.len() > top_k;
    let mut hits = Vec::new();
    for &(index, score) in scored.iter().take(top_k) {
        let d = &docs[index];
        let identity = match (&media, d.image_id) {
            (Some(assets), Some(id)) => {
                let asset = assets.get(&id).ok_or_else(invalid)?;
                json!({"asset_id":id.to_string(),"image_path":asset.path,"media_sha256":asset.sha256,"media_bytes":asset.size,"media_version":1})
            }
            _ => serde_json::Value::Null,
        };
        let detail:Vec<_>=terms.iter().enumerate().map(|(i,t)|json!({"term":t,"tf":d.tf[i],"contribution":contribution(idf[i],d.tf[i],d.dl,avgdl)})).collect();
        hits.push(json!({"doc_id":d.id,"text":d.text,"score":score,"dl":d.dl,"terms":detail,"media":identity}));
    }
    source::snapshot(&config.source, &config.sha256).await?;
    let statistics: Vec<_> = terms
        .iter()
        .enumerate()
        .map(|(i, t)| json!({"term":t,"df":df[i],"idf":idf[i]}))
        .collect();
    let output=serde_json::to_string(&json!({"source_sha256":config.sha256,"algorithm":"bm25-positive-idf-v1","analyzer":"ascii-alnum-lower-v1","k1":K1,"b":B,"documents":n,"total_tokens":total_tokens,"avgdl":avgdl,"terms":statistics,"top_k":top_k,"hits":hits,"truncated":truncated})).map_err(|_|Error::new("output_failed","cannot encode search result"))?;
    if output.len() > RESULT_LIMIT {
        return Err(Error::new("resource_limit", "search output exceeds 2 MiB"));
    }
    Ok(output)
}
