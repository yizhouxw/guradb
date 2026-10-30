//! One managed dataset, complete snapshots, and atomic durable operation results.
use super::{
    capture, managed_input,
    state::{self, Catalog, Record, Store},
};
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Revision {
    pub id: String,
    pub generation: usize,
    pub view_id: String,
    pub operation_id: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Operation {
    pub id: String,
    pub input_sha256: String,
    pub phase: String,
    pub parent: Option<String>,
    pub generation: usize,
    pub revision_id: String,
    pub record: Record,
    pub rows: usize,
    pub assets: usize,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Managed {
    pub name: String,
    pub dataset_id: String,
    pub schema_id: String,
    pub columns: Vec<managed_input::Column>,
    pub mode: u32,
    pub revisions: Vec<Revision>,
    pub operations: Vec<Operation>,
}
fn bad(code: &str, message: &str) -> Error {
    Error::new(code, message)
}
fn hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
fn same_record(a: &Record, b: &Record) -> bool {
    let mut a = a.clone();
    a.published = b.published;
    serde_json::to_value(a).ok() == serde_json::to_value(b).ok()
}
impl Managed {
    pub fn valid(&self, c: &Catalog) -> bool {
        let Ok(schema) = serde_json::to_vec(&self.columns) else {
            return false;
        };
        let mut bytes = b"guradb-schema-v1\n".to_vec();
        bytes.extend(schema);
        if !state::request(&self.name)
            || !state::digest(&self.dataset_id)
            || self.schema_id != hash(&bytes)
            || ![1, 2].contains(&self.mode)
            || self.columns.is_empty()
            || self.columns.len() > 32
            || self.columns.iter().enumerate().any(|(i, col)| {
                !["Int64", "Boolean", "Utf8"].contains(&col.kind.as_str())
                    || col.name.is_empty()
                    || col.name.len() > 256
                    || self.columns[..i].iter().any(|v| v.name == col.name)
            })
            || self.revisions.len() > 2
            || self.operations.is_empty()
            || self.operations.len() > 8
        {
            return false;
        }
        let mut active = 0;
        let mut ready = 0;
        for (i, op) in self.operations.iter().enumerate() {
            let feature = op
                .record
                .features
                .as_ref()
                .map_or("none", |f| f.sha256.as_str());
            let fingerprint = hash(
                format!(
                    "guradb-import-v1\n{}\n{}\n{}\n",
                    self.name,
                    op.record.source(),
                    feature
                )
                .as_bytes(),
            );
            let revision = hash(
                format!(
                    "guradb-revision-v1\n{}\n{}\n{}\n{}\n",
                    self.dataset_id, self.schema_id, op.generation, op.record.id
                )
                .as_bytes(),
            );
            let parent = op
                .generation
                .checked_sub(2)
                .and_then(|i| self.revisions.get(i))
                .map(|r| r.view_id.clone());
            if !state::request(&op.id)
                || op.input_sha256 != fingerprint
                || op.revision_id != revision
                || op.parent != parent
                || op.generation == 0
                || op.generation > 2
                || !op.record.valid()
                || op.record.request_id != op.id
                || op.record.version() != self.mode
                || op.record.published
                || op.rows == 0
                || op.rows > 200
                || op.assets == 0
                || op.assets > 3
                || self.operations[..i].iter().any(|x| x.id == op.id)
            {
                return false;
            }
            match op.phase.as_str() {
                "capturing" | "ready" => {
                    active += 1;
                    if op.generation != self.revisions.len() + 1 || op.parent != c.current {
                        return false;
                    }
                    if op.phase == "ready" {
                        ready += 1;
                        if !c
                            .views
                            .iter()
                            .any(|v| same_record(v, &op.record) && !v.published)
                        {
                            return false;
                        }
                    }
                }
                "committed" => {
                    if !self.revisions.iter().any(|r| {
                        r.operation_id == op.id
                            && r.id == op.revision_id
                            && r.generation == op.generation
                    }) || !c
                        .views
                        .iter()
                        .any(|v| v.published && same_record(v, &op.record))
                    {
                        return false;
                    }
                }
                "failed" => (),
                _ => return false,
            }
        }
        if active > 1 || c.views.len() != self.revisions.len() + ready {
            return false;
        }
        for (i, r) in self.revisions.iter().enumerate() {
            if r.generation != i + 1
                || !state::digest(&r.id)
                || !self.operations.iter().any(|op| {
                    op.id == r.operation_id
                        && op.phase == "committed"
                        && op.revision_id == r.id
                        && op.record.id == r.view_id
                })
                || !c
                    .views
                    .iter()
                    .any(|v| v.id == r.view_id && v.published && v.request_id == r.operation_id)
            {
                return false;
            }
        }
        c.current == self.revisions.last().map(|r| r.view_id.clone())
    }
}

fn reserve(c: &Catalog) -> Result<()> {
    let op = c
        .managed
        .as_ref()
        .and_then(|d| d.operations.last())
        .ok_or_else(state::invalid)?
        .clone();
    let mut ready = c.clone();
    ready.views.push(op.record.clone());
    set_phase(&mut ready, &op.id, "ready");
    let mut committed = ready.clone();
    committed
        .views
        .last_mut()
        .ok_or_else(state::invalid)?
        .published = true;
    committed.current = Some(op.record.id.clone());
    committed
        .managed
        .as_mut()
        .ok_or_else(state::invalid)?
        .revisions
        .push(Revision {
            id: op.revision_id,
            generation: op.generation,
            view_id: op.record.id,
            operation_id: op.id.clone(),
        });
    set_phase(&mut committed, &op.id, "committed");
    for value in [c, &ready, &committed] {
        if serde_json::to_vec(value)
            .map_err(|_| state::invalid())?
            .len()
            > 16384
        {
            return Err(bad(
                "resource_limit",
                "reserve complete ready/committed catalog before admission",
            ));
        }
    }
    Ok(())
}

fn usage() -> Error {
    bad(
        "unsupported_dataset_operation",
        "dataset import|status|reconcile|retry with exact documented arguments",
    )
}
pub async fn entry(a: Vec<String>) {
    crate::operation(Duration::from_secs(10), move || {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .map_err(|_| bad("execution_failed", "cannot start dataset runtime"))?;
        rt.block_on(run(a))
    })
    .await;
}
fn random_id() -> Result<String> {
    let mut bytes = [0u8; 32];
    fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .map_err(|_| state::invalid())?;
    Ok(hash(&bytes))
}
async fn output(s: &Store, c: &Catalog, id: Option<&str>, replayed: bool) -> Result<String> {
    let d = c
        .managed
        .as_ref()
        .ok_or_else(|| bad("dataset_missing", "no managed dataset"))?;
    for record in &c.views {
        let (config, root) = capture::owned(s, record).await?;
        let (_, assets, ids) = capture::validate(&config, &root).await?;
        if d.operations.iter().any(|op| {
            op.record.id == record.id && (op.rows != ids.len() || op.assets != assets.len())
        }) {
            return Err(bad(
                "dataset_integrity",
                "persisted operation counts differ from owned snapshot",
            ));
        }
    }
    let operation = match id {
        Some(id) => Some(
            d.operations
                .iter()
                .find(|o| o.id == id)
                .ok_or_else(|| bad("operation_missing", "unknown operation"))?,
        ),
        None => None,
    };
    serde_json::to_string(&json!({"dataset_id":d.dataset_id,"name":d.name,"schema_id":d.schema_id,
        "schema":d.columns,"current_revision":d.revisions.last(),"current_view":c.current,
        "revisions":d.revisions,"operations":d.operations,"operation":operation,"replayed":replayed,
        "recovery_required":d.operations.iter().any(|o|matches!(o.phase.as_str(),"capturing"|"ready")) || ["catalog.tmp","pending.json",".staging"].iter().any(|p|s.root.join(p).exists())}))
        .map_err(|_|state::invalid())
}
fn clear_temp(s: &Store) -> Result<()> {
    let path = s.root.join("catalog.tmp");
    if path.exists() {
        state::regular(&path)?;
        fs::remove_file(path).map_err(|_| state::invalid())?;
        state::sync_dir(&s.root)?;
    }
    Ok(())
}
fn set_phase(c: &mut Catalog, id: &str, phase: &str) {
    c.managed
        .as_mut()
        .expect("managed checked")
        .operations
        .iter_mut()
        .find(|o| o.id == id)
        .expect("operation checked")
        .phase = phase.into();
}
async fn reconcile(s: &Store, c: &mut Catalog, requested: Option<&str>) -> Result<()> {
    let d = c
        .managed
        .as_ref()
        .ok_or_else(|| bad("dataset_missing", "no managed dataset"))?;
    if let Some(id) = requested {
        let op = d
            .operations
            .iter()
            .find(|o| o.id == id)
            .ok_or_else(|| bad("operation_missing", "unknown operation"))?;
        if matches!(op.phase.as_str(), "committed" | "failed") {
            return Ok(());
        }
    }
    let active = d
        .operations
        .iter()
        .find(|o| matches!(o.phase.as_str(), "capturing" | "ready"))
        .cloned();
    clear_temp(s)?;
    let Some(op) = active else {
        s.recover(c).await?;
        return Ok(());
    };
    if let Some(pending) = s.pending().await? {
        if pending.id != op.record.id || pending.request_id != op.id {
            return Err(state::invalid());
        }
    }
    if s.object(&op.record.id).exists() {
        let (config, root) = capture::owned(s, &op.record).await?;
        let (_, assets, ids) = capture::validate(&config, &root).await?;
        if assets.len() != op.assets || ids.len() != op.rows {
            return Err(state::invalid());
        }
        if !c.views.iter().any(|v| v.id == op.record.id) {
            c.views.push(op.record.clone());
        }
        set_phase(c, &op.id, "ready");
        s.save(c)?;
        s.recover(c).await?;
        let d = c.managed.as_ref().expect("managed checked");
        if c.current != op.parent || op.generation != d.revisions.len() + 1 {
            return Err(bad(
                "operation_stale",
                "operation parent/generation no longer current",
            ));
        }
        let record = c
            .views
            .iter_mut()
            .find(|v| v.id == op.record.id)
            .ok_or_else(state::invalid)?;
        record.published = true;
        c.current = Some(record.id.clone());
        let d = c.managed.as_mut().expect("managed checked");
        d.revisions.push(Revision {
            id: op.revision_id.clone(),
            generation: op.generation,
            view_id: op.record.id.clone(),
            operation_id: op.id.clone(),
        });
        set_phase(c, &op.id, "committed");
        s.save(c)?;
    } else {
        s.recover(c).await?;
        set_phase(c, &op.id, "failed");
        s.save(c)?;
    }
    Ok(())
}
async fn run(a: Vec<String>) -> Result<String> {
    if a.len() < 5 || a[3] != "--store" {
        return Err(usage());
    }
    let action = a[2].as_str();
    let import = action == "import";
    let valid = if import {
        (a.len() == 11
            || (a.len() == 15
                && a[11] == "--features"
                && a[13] == "--features-sha256"
                && state::digest(&a[14])))
            && a[5] == "--name"
            && state::request(&a[6])
            && a[7] == "--operation-id"
            && state::request(&a[8])
            && a[9] == "--config"
    } else {
        matches!(action, "status" | "reconcile" | "retry")
            && (a.len() == 5 || (a.len() == 7 && a[5] == "--operation-id" && state::request(&a[6])))
            && (action != "retry" || a.len() == 7)
    };
    if !valid {
        return Err(usage());
    }
    let s = Store::open(PathBuf::from(&a[4]), import, action == "reconcile")?;
    let mut c = s.catalog().await?;
    if !import {
        if c.managed.is_none() {
            if action == "reconcile" && c.views.is_empty() && c.current.is_none() {
                s.recover(&c).await?;
                return Ok(
                    json!({"dataset":null,"state":"not_admitted","recovery":"clean"}).to_string(),
                );
            }
            return Err(bad("dataset_missing", "store is not a managed dataset"));
        }
        let id = if a.len() == 7 {
            Some(a[6].as_str())
        } else {
            None
        };
        if action != "status" {
            reconcile(&s, &mut c, id).await?;
        }
        return output(&s, &c, id, action == "retry").await;
    }
    if c.managed.is_none() && (!c.views.is_empty() || c.current.is_some()) {
        return Err(bad(
            "unsupported_dataset_store",
            "use a new empty managed root; old view roots are not migrated",
        ));
    }
    let path = Path::new(&a[10]);
    let cfg = capture::config(path).await?;
    let pin = if a.len() == 15 {
        a[14].as_str()
    } else {
        "none"
    };
    let fingerprint =
        hash(format!("guradb-import-v1\n{}\n{}\n{}\n", a[6], cfg.sha256, pin).as_bytes());
    if let Some(d) = &c.managed {
        if d.name != a[6] {
            return Err(bad(
                "dataset_identity_conflict",
                "this root owns a different dataset",
            ));
        }
        if let Some(op) = d.operations.iter().find(|op| op.id == a[8]) {
            if op.input_sha256 != fingerprint {
                return Err(bad(
                    "operation_identity_conflict",
                    "operation ID already binds different input",
                ));
            }
            return output(&s, &c, Some(&a[8]), true).await;
        }
        if d.operations
            .iter()
            .any(|o| matches!(o.phase.as_str(), "capturing" | "ready"))
        {
            return Err(bad(
                "operation_recovery_required",
                "resolve the existing operation before a new import",
            ));
        }
        if d.operations.len() >= 8 || d.revisions.len() >= 2 {
            return Err(bad(
                "resource_limit",
                "managed operation/revision budget exhausted",
            ));
        }
    }
    s.no_pending()?;
    let features = if a.len() == 15 {
        Some((Path::new(&a[12]), a[14].as_str()))
    } else {
        None
    };
    let input = managed_input::inspect(path, features, &a[8]).await?;
    if input.config.sha256 != cfg.sha256 {
        return Err(bad(
            "source_changed",
            "input config identity changed during validation",
        ));
    }
    if input.columns.len() > 32 {
        return Err(bad("resource_limit", "managed schema exceeds 32 columns"));
    }
    if let Some(d) = &c.managed {
        if d.schema_id != input.schema_id
            || d.columns != input.columns
            || d.mode != input.record.version()
            || d.operations.first().is_some_and(|v| {
                v.record.features.as_ref().map(|f| &f.space)
                    != input.record.features.as_ref().map(|f| &f.space)
            })
        {
            return Err(bad(
                "schema_mismatch",
                "replacement requires the same schema, feature mode and space",
            ));
        }
    } else {
        c.format_version = 3;
        c.managed = Some(Managed {
            name: a[6].clone(),
            dataset_id: random_id()?,
            schema_id: input.schema_id.clone(),
            columns: input.columns.clone(),
            mode: input.record.version(),
            revisions: vec![],
            operations: vec![],
        });
    }
    if c.views.iter().any(|v| v.id == input.record.id) {
        return Err(bad(
            "revision_identity_conflict",
            "same content requires replay of its existing operation",
        ));
    }
    let d = c.managed.as_mut().expect("managed initialized");
    let generation = d.revisions.len() + 1;
    let revision_id = hash(
        format!(
            "guradb-revision-v1\n{}\n{}\n{}\n{}\n",
            d.dataset_id, d.schema_id, generation, input.record.id
        )
        .as_bytes(),
    );
    d.operations.push(Operation {
        id: a[8].clone(),
        input_sha256: fingerprint,
        phase: "capturing".into(),
        parent: c.current.clone(),
        generation,
        revision_id,
        record: input.record.clone(),
        rows: input.rows,
        assets: input.assets,
    });
    reserve(&c)?;
    s.save(&c)?;
    state::write(
        &s.root.join("catalog.tmp"),
        &serde_json::to_vec(&input.record).map_err(|_| state::invalid())?,
    )?;
    fs::rename(s.root.join("catalog.tmp"), s.root.join("pending.json"))
        .map_err(|_| state::invalid())?;
    state::sync_dir(&s.root)?;
    let origin = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let captured = capture::capture(
        &s,
        &input.config,
        origin,
        &input.record,
        features.map(|(path, _)| path),
    )
    .await;
    if let Err(error) = captured {
        reconcile(&s, &mut c, None).await?;
        return Err(error);
    }
    reconcile(&s, &mut c, Some(&a[8])).await?;
    output(&s, &c, Some(&a[8]), false).await
}

#[cfg(test)]
#[path = "managed_tests.rs"]
mod tests;
