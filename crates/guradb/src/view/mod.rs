//! Two captured local views; the atomic catalog is the sole publication fact.
mod capture;
pub mod managed;
mod managed_input;
mod state;
use crate::{Error, Result, RESULT_LIMIT};
use serde_json::{json, Value};
use state::{Record, Store};
use std::{path::PathBuf, time::Duration};

fn usage() -> Error {
    Error::new("unsupported_view_operation","view prepare|publish|status|recover|query|search|media with exact documented arguments; v2 features required for vector/hybrid/sample")
}
pub async fn entry(args: Vec<String>) {
    crate::operation(Duration::from_secs(10), move || {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .map_err(|_| Error::new("execution_failed", "cannot start view runtime"))?;
        runtime.block_on(run(args))
    })
    .await;
}
async fn run(a: Vec<String>) -> Result<String> {
    if a.len() < 5 || a[3] != "--store" {
        return Err(usage());
    }
    let op = a[2].as_str();
    let valid = match op {
        "prepare" => {
            (a.len() == 9
                || (a.len() == 13
                    && a[9] == "--features"
                    && a[11] == "--features-sha256"
                    && state::digest(&a[12])))
                && a[5] == "--config"
                && a[7] == "--request-id"
                && state::request(&a[8])
        }
        "publish" => a.len() == 7 && a[5] == "--request-id" && state::request(&a[6]),
        "status" | "recover" => a.len() == 5,
        "query" | "search" | "media" | "sample" => {
            a.len() == 9
                && a[5] == "--view"
                && (a[6] == "current" || state::digest(&a[6]))
                && a[7]
                    == match op {
                        "query" => "--sql",
                        "search" => "--query",
                        "sample" => "--selection",
                        _ => "--asset-id",
                    }
        }
        "vector" | "hybrid" => {
            a.len() == if op == "hybrid" { 13 } else { 11 }
                && a[5] == "--view"
                && (a[6] == "current" || state::digest(&a[6]))
                && a[7] == "--query"
                && a[9] == "--top-k"
                && (op != "hybrid" || a[11] == "--text-query")
        }
        _ => false,
    };
    if !valid {
        return Err(usage());
    }
    let s = Store::open(PathBuf::from(&a[4]), op == "prepare", op == "recover")?;
    let mut c = s.catalog().await?;
    if c.managed.is_some() && matches!(op, "prepare" | "publish" | "recover") {
        return Err(Error::new(
            "unsupported_dataset_mutation",
            "use dataset operations for this managed root",
        ));
    }
    if matches!(op, "status" | "recover") {
        for v in &c.views {
            capture::owned(&s, v).await?;
        }
    }
    let output: Value = match op {
        "status" => {
            json!({"format_version":c.format_version,"current":c.current,"views":c.views,"pending":s.pending().await?,"recovery_required":s.root.join("pending.json").exists()||s.root.join("catalog.tmp").exists()||s.root.join(".staging").exists()})
        }
        "recover" => {
            let action = s.recover(&c).await?;
            json!({"format_version":c.format_version,"recovery":action,"current":c.current,"views":c.views})
        }
        "prepare" => {
            s.no_pending()?;
            let input = PathBuf::from(&a[6]);
            let cfg = capture::config(&input).await?;
            let feature_path = if a.len() == 13 {
                Some(PathBuf::from(&a[10]))
            } else {
                None
            };
            let bound = if let Some(path) = &feature_path {
                let (_, _, ids) = capture::validate(
                    &cfg,
                    input
                        .parent()
                        .filter(|p| !p.as_os_str().is_empty())
                        .unwrap_or(std::path::Path::new(".")),
                )
                .await?;
                let loaded = crate::features::load(path, &a[12], &cfg.sha256, &ids).await?;
                Some(state::BoundFeatures {
                    sha256: a[12].clone(),
                    space: loaded.space,
                })
            } else {
                None
            };
            let id = bound.as_ref().map_or_else(
                || cfg.sha256.clone(),
                |f| state::identity(&cfg.sha256, &f.sha256),
            );
            let version = if bound.is_some() { 2 } else { 1 };
            if c.views.is_empty() {
                c.format_version = version;
            } else if c.format_version != version {
                return Err(Error::new(
                    "unsupported_view_version",
                    "use a new empty store; dependencies cannot be added to an existing view",
                ));
            }

            if let Some(v) = c.views.iter().find(|v| v.request_id == a[8] || v.id == id) {
                if v.request_id != a[8] || v.id != id {
                    return Err(Error::new(
                        "view_identity_conflict",
                        "request/source identity already bound differently",
                    ));
                }
                capture::owned(&s, v).await?;
                json!({"view_id":v.id,"source_sha256":v.source(),"state":if v.published{"published"}else{"prepared"},"replayed":true,"current":c.current})
            } else {
                if c.views.len() == 2 {
                    return Err(Error::new(
                        "resource_limit",
                        "at most two captured views; deletion/GC unsupported",
                    ));
                }
                let v = Record {
                    id,
                    source_sha256: bound.as_ref().map(|_| cfg.sha256.clone()),
                    features: bound,
                    request_id: a[8].clone(),
                    published: false,
                };
                state::write(
                    &s.root.join("pending.json"),
                    &serde_json::to_vec(&v).map_err(|_| state::invalid())?,
                )?;
                state::sync_dir(&s.root)?;
                capture::capture(
                    &s,
                    &cfg,
                    input
                        .parent()
                        .filter(|p| !p.as_os_str().is_empty())
                        .unwrap_or(std::path::Path::new(".")),
                    &v,
                    feature_path.as_deref(),
                )
                .await?;
                c.views.push(v.clone());
                s.save(&c)?;
                std::fs::remove_file(s.root.join("pending.json")).map_err(|_| state::invalid())?;
                state::sync_dir(&s.root)?;
                json!({"view_id":v.id,"source_sha256":v.source(),"state":"prepared","replayed":false,"current":c.current})
            }
        }
        "publish" => {
            s.no_pending()?;
            let index = c
                .views
                .iter()
                .position(|v| v.request_id == a[6])
                .ok_or_else(|| Error::new("view_missing", "unknown request"))?;
            let v = c.views[index].clone();
            capture::owned(&s, &v).await?;
            if !v.published {
                c.views[index].published = true;
                c.current = Some(v.id.clone());
                s.save(&c)?;
            }
            json!({"view_id":v.id,"state":"published","replayed":v.published,"current":c.current})
        }
        _ => {
            let id = if a[6] == "current" {
                c.current
                    .clone()
                    .ok_or_else(|| Error::new("view_missing", "no published current"))?
            } else {
                a[6].clone()
            };
            let v = c
                .views
                .iter()
                .find(|v| v.id == id && v.published)
                .ok_or_else(|| Error::new("view_not_ready", "view is absent or not published"))?;
            if matches!(op, "vector" | "hybrid" | "sample") && v.features.is_none() {
                return Err(Error::new(
                    "view_features_required",
                    "v1 view has no fixed features; prepare a new full v2 store",
                ));
            }
            let (cfg, root) = capture::owned(&s, v).await?;
            let source_sha = cfg.sha256.clone();
            let result = match op {
                "query" => crate::query(cfg, a[8].clone()).await?,
                "search" => crate::search::run(cfg, a[8].clone(), 10).await?,
                "vector" | "hybrid" => {
                    let k = a[10].parse::<usize>().unwrap_or(0);
                    if !(1..=20).contains(&k) {
                        return Err(usage());
                    }
                    let f = v.features.as_ref().ok_or_else(usage)?;
                    crate::vector::run(
                        cfg,
                        crate::vector::Request {
                            features: root.join("features.jsonl"),
                            pin: f.sha256.clone(),
                            query: PathBuf::from(&a[8]),
                            k,
                            text: if op == "hybrid" {
                                Some(a[12].clone())
                            } else {
                                None
                            },
                        },
                    )
                    .await?
                }
                "sample" => {
                    let out = crate::sample::run(cfg, PathBuf::from(&a[8]), root).await?;
                    let mut value: Value =
                        serde_json::from_str(&out).map_err(|_| state::invalid())?;
                    value["view_id"] = json!(id);
                    serde_json::to_string(&value).map_err(|_| state::invalid())?
                }
                _ => {
                    let asset = a[8]
                        .parse::<i64>()
                        .ok()
                        .filter(|id| (1..=999_999_999_999).contains(id))
                        .ok_or_else(usage)?;
                    crate::media::read(cfg, root, asset).await?
                }
            };
            json!({"view_id":id,"source_sha256":source_sha,"result":serde_json::from_str::<Value>(&result).map_err(|_|state::invalid())?})
        }
    };
    let out = serde_json::to_string(&output).map_err(|_| state::invalid())?;
    if out.len() > RESULT_LIMIT {
        return Err(Error::new("resource_limit", "view output exceeds 2 MiB"));
    }
    Ok(out)
}
