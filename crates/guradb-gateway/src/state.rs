use crate::auth::Principal;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use guradb_catalog::Catalog;
use guradb_common::{protocol::QueryHandle, Error, Limits, Result};
use guradb_query::{sql::Prepared, Output};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::{
    collections::{HashMap, VecDeque},
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::{Mutex, Semaphore};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

pub struct Entry {
    pub owner: (String, String),
    pub dataset_id: String,
    pub handle: QueryHandle,
    pub cancel: CancellationToken,
    pub output: Option<Output>,
    pub finished: Option<Instant>,
}
#[derive(Default)]
pub struct Registry {
    pub entries: HashMap<String, Entry>,
    expired: VecDeque<(String, (String, String))>,
}
pub struct State {
    pub catalog: Catalog,
    pub auth_file: PathBuf,
    pub limits: Limits,
    pub registry: Mutex<Registry>,
    pub slots: Semaphore,
    pub key: Vec<u8>,
}
impl Registry {
    pub fn prune(&mut self, limits: &Limits) {
        let expired: Vec<_> = self
            .entries
            .iter()
            .filter(|(_, e)| {
                e.finished.is_some_and(|time| {
                    time.elapsed() >= Duration::from_secs(limits.retention_seconds)
                })
            })
            .map(|(id, e)| (id.clone(), e.owner.clone()))
            .collect();
        for (id, owner) in expired {
            self.entries.remove(&id);
            self.expired.push_back((id, owner));
        }
        while self.expired.len() > limits.handles {
            self.expired.pop_front();
        }
    }
    pub fn get_mut(&mut self, id: &str, principal: &Principal) -> Result<&mut Entry> {
        let owner = (principal.tenant_id.clone(), principal.principal_id.clone());
        let missing = if self
            .expired
            .iter()
            .any(|(key, subject)| key == id && subject == &owner)
        {
            "expired"
        } else {
            "not_found"
        };
        self.entries
            .get_mut(id)
            .filter(|e| e.owner == owner && principal.datasets.contains(&e.dataset_id))
            .ok_or_else(|| Error::new(missing, "query is unavailable"))
    }
}
impl State {
    pub async fn submit(
        self: &Arc<Self>,
        plan: Prepared,
        principal: Principal,
        timeout: u64,
        max_rows: usize,
    ) -> Result<QueryHandle> {
        let mut registry = self.registry.lock().await;
        registry.prune(&self.limits);
        if registry.entries.len() >= self.limits.handles {
            return Err(Error::new(
                "resource_limit",
                "query handle capacity reached",
            ));
        }
        let worker_identity = principal.clone();
        let id = Uuid::new_v4().to_string();
        let handle = QueryHandle {
            query_id: id.clone(),
            status: "queued".into(),
            result_kind: "data".into(),
            read_context: plan.dataset.context.clone(),
            error: None,
            stats: None,
        };
        let cancel = CancellationToken::new();
        registry.entries.insert(
            id.clone(),
            Entry {
                owner: (principal.tenant_id, principal.principal_id),
                dataset_id: plan.dataset.manifest.dataset_id.clone(),
                handle: handle.clone(),
                cancel: cancel.clone(),
                output: None,
                finished: None,
            },
        );
        let state = self.clone();
        tokio::spawn(async move {
            let work = async {
                let _permit = state
                    .slots
                    .acquire()
                    .await
                    .map_err(|_| Error::new("execution_failed", "executor closed"))?;
                {
                    let mut registry = state.registry.lock().await;
                    if let Some(entry) = registry.entries.get_mut(&id) {
                        if !cancel.is_cancelled() {
                            entry.handle.status = "running".into();
                        }
                    }
                }
                let authorized =
                    crate::auth::load(&state.auth_file)
                        .await?
                        .into_iter()
                        .any(|subject| {
                            subject.token_sha256 == worker_identity.token_sha256
                                && subject.tenant_id == worker_identity.tenant_id
                                && subject.principal_id == worker_identity.principal_id
                                && subject.datasets.contains(&plan.dataset.manifest.dataset_id)
                        });
                if !authorized {
                    return Err(Error::new(
                        "forbidden",
                        "authorization revoked before execution",
                    ));
                }
                guradb_query::execute(plan, &state.limits, max_rows, &cancel).await
            };
            let result = tokio::select! {
                biased;
                _ = cancel.cancelled() => Err(Error::new("cancelled", "query cancelled")),
                result = tokio::time::timeout(Duration::from_millis(timeout), work) => result.unwrap_or_else(|_| Err(Error::new("timeout", "query deadline exceeded"))),
            };
            let mut registry = state.registry.lock().await;
            if let Some(entry) = registry.entries.get_mut(&id) {
                if cancel.is_cancelled() {
                    entry.handle.status = "cancelled".into();
                } else {
                    match result {
                        Ok(output) => {
                            entry.handle.status = "succeeded".into();
                            entry.handle.stats = Some(output.stats.clone());
                            entry.output = Some(output);
                        }
                        Err(error) => {
                            entry.handle.status = "failed".into();
                            entry.handle.error = Some(error);
                        }
                    }
                }
                entry.finished = Some(Instant::now());
            }
        });
        Ok(handle)
    }
    pub fn cursor(&self, id: &str, principal: &Principal, view: &str, offset: usize) -> String {
        let message = serde_json::to_vec(&(
            id,
            &principal.tenant_id,
            &principal.principal_id,
            view,
            offset,
        ))
        .expect("serializable cursor");
        let mut mac = Hmac::<Sha256>::new_from_slice(&self.key).expect("HMAC key");
        mac.update(&message);
        format!(
            "{}.{}",
            URL_SAFE_NO_PAD.encode(&message),
            URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes())
        )
    }
    pub fn offset(
        &self,
        cursor: &str,
        id: &str,
        principal: &Principal,
        view: &str,
    ) -> Result<usize> {
        let invalid = || {
            Error::new(
                "invalid_cursor",
                "cursor is invalid for this query and subject",
            )
        };
        if cursor.len() > 2048 {
            return Err(invalid());
        }
        let (payload, signature) = cursor.split_once('.').ok_or_else(invalid)?;
        let message = URL_SAFE_NO_PAD.decode(payload).map_err(|_| invalid())?;
        let signature = URL_SAFE_NO_PAD.decode(signature).map_err(|_| invalid())?;
        let mut mac = Hmac::<Sha256>::new_from_slice(&self.key).map_err(|_| invalid())?;
        mac.update(&message);
        mac.verify_slice(&signature).map_err(|_| invalid())?;
        let (query, tenant, subject, version, offset): (String, String, String, String, usize) =
            serde_json::from_slice(&message).map_err(|_| invalid())?;
        if query != id
            || tenant != principal.tenant_id
            || subject != principal.principal_id
            || version != view
        {
            return Err(invalid());
        }
        Ok(offset)
    }
}
