//! Two captured local views; the atomic catalog is the sole publication fact.
mod capture;
mod state;
use crate::{Error, Result, RESULT_LIMIT};
use serde_json::{json, Value};
use state::{Record, Store};
use std::{path::PathBuf, time::Duration};

fn usage() -> Error {
    Error::new("unsupported_view_operation","view prepare|publish|status|recover|query|search|media with exact documented arguments; vector/hybrid/sample view not supported")
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
            a.len() == 9 && a[5] == "--config" && a[7] == "--request-id" && state::request(&a[8])
        }
        "publish" => a.len() == 7 && a[5] == "--request-id" && state::request(&a[6]),
        "status" | "recover" => a.len() == 5,
        "query" | "search" | "media" => {
            a.len() == 9
                && a[5] == "--view"
                && (a[6] == "current" || state::digest(&a[6]))
                && a[7]
                    == match op {
                        "query" => "--sql",
                        "search" => "--query",
                        _ => "--asset-id",
                    }
        }
        _ => false,
    };
    if !valid {
        return Err(usage());
    }
    let s = Store::open(PathBuf::from(&a[4]), op == "prepare", op == "recover")?;
    let mut c = s.catalog().await?;
    if matches!(op, "status" | "recover") {
        for v in &c.views {
            capture::owned(&s, &v.id).await?;
        }
    }
    let output: Value = match op {
        "status" => {
            json!({"format_version":1,"current":c.current,"views":c.views,"pending":s.pending().await?,"recovery_required":s.root.join("pending.json").exists()||s.root.join("catalog.tmp").exists()||s.root.join(".staging").exists()})
        }
        "recover" => {
            let action = s.recover(&c).await?;
            json!({"format_version":1,"recovery":action,"current":c.current,"views":c.views})
        }
        "prepare" => {
            s.no_pending()?;
            let input = PathBuf::from(&a[6]);
            let cfg = capture::config(&input).await?;
            if let Some(v) = c
                .views
                .iter()
                .find(|v| v.request_id == a[8] || v.id == cfg.sha256)
            {
                if v.request_id != a[8] || v.id != cfg.sha256 {
                    return Err(Error::new(
                        "view_identity_conflict",
                        "request/source identity already bound differently",
                    ));
                }
                capture::owned(&s, &v.id).await?;
                json!({"view_id":v.id,"source_sha256":v.id,"state":if v.published{"published"}else{"prepared"},"replayed":true,"current":c.current})
            } else {
                if c.views.len() == 2 {
                    return Err(Error::new(
                        "resource_limit",
                        "at most two captured views; deletion/GC unsupported",
                    ));
                }
                let v = Record {
                    id: cfg.sha256.clone(),
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
                )
                .await?;
                c.views.push(v.clone());
                s.save(&c)?;
                std::fs::remove_file(s.root.join("pending.json")).map_err(|_| state::invalid())?;
                state::sync_dir(&s.root)?;
                json!({"view_id":v.id,"source_sha256":v.id,"state":"prepared","replayed":false,"current":c.current})
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
            capture::owned(&s, &v.id).await?;
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
            if !c.views.iter().any(|v| v.id == id && v.published) {
                return Err(Error::new(
                    "view_not_ready",
                    "view is absent or not published",
                ));
            }
            let (cfg, root) = capture::owned(&s, &id).await?;
            let result = match op {
                "query" => crate::query(cfg, a[8].clone()).await?,
                "search" => crate::search::run(cfg, a[8].clone(), 10).await?,
                _ => {
                    let asset = a[8]
                        .parse::<i64>()
                        .ok()
                        .filter(|id| (1..=999_999_999_999).contains(id))
                        .ok_or_else(usage)?;
                    crate::media::read(cfg, root, asset).await?
                }
            };
            json!({"view_id":id,"source_sha256":id,"result":serde_json::from_str::<Value>(&result).map_err(|_|state::invalid())?})
        }
    };
    let out = serde_json::to_string(&output).map_err(|_| state::invalid())?;
    if out.len() > RESULT_LIMIT {
        return Err(Error::new("resource_limit", "view output exceeds 2 MiB"));
    }
    Ok(out)
}
