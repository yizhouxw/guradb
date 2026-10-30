use crate::{source, Error, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    os::{fd::AsRawFd, unix::fs::OpenOptionsExt},
    path::{Path, PathBuf},
};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_sha256: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub features: Option<BoundFeatures>,
    pub id: String,
    pub request_id: String,
    pub published: bool,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BoundFeatures {
    pub sha256: String,
    pub space: crate::features::Space,
}
impl Record {
    pub fn source(&self) -> &str {
        self.source_sha256.as_deref().unwrap_or(&self.id)
    }
    pub fn version(&self) -> u32 {
        if self.features.is_some() {
            2
        } else {
            1
        }
    }
    pub fn valid(&self) -> bool {
        digest(&self.id)
            && request(&self.request_id)
            && match (&self.source_sha256, &self.features) {
                (None, None) => true,
                (Some(source), Some(f)) => {
                    digest(source) && digest(&f.sha256) && self.id == identity(source, &f.sha256)
                }
                _ => false,
            }
    }
}
pub fn identity(source: &str, features: &str) -> String {
    hex::encode(Sha256::digest(
        format!("guradb-view-features-v2\n{source}\n{features}\n").as_bytes(),
    ))
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Catalog {
    pub format_version: u32,
    pub current: Option<String>,
    pub views: Vec<Record>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub managed: Option<super::managed::Managed>,
}
pub struct Store {
    pub root: PathBuf,
    _lock: File,
}
pub fn invalid() -> Error {
    Error::new(
        "invalid_view_store",
        "invalid, linked, unknown or inconsistent view store",
    )
}
pub fn digest(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub fn request(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 64
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
}
pub fn directory(p: &Path) -> Result<()> {
    let m = fs::symlink_metadata(p).map_err(|_| invalid())?;
    if !m.is_dir() || m.file_type().is_symlink() {
        return Err(invalid());
    }
    Ok(())
}
pub fn regular(p: &Path) -> Result<()> {
    let m = fs::symlink_metadata(p).map_err(|_| invalid())?;
    if !m.is_file() || m.file_type().is_symlink() {
        return Err(invalid());
    }
    Ok(())
}
pub fn sync_dir(p: &Path) -> Result<()> {
    File::open(p)
        .and_then(|f| f.sync_all())
        .map_err(|_| invalid())
}
pub fn write(p: &Path, bytes: &[u8]) -> Result<()> {
    let mut f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(p)
        .map_err(|_| invalid())?;
    f.write_all(bytes)
        .and_then(|_| f.sync_all())
        .map_err(|_| invalid())
}
impl Store {
    pub fn open(root: PathBuf, create: bool, recover: bool) -> Result<Self> {
        let fresh = create && !root.exists();
        if fresh {
            fs::create_dir(&root).map_err(|_| invalid())?;
        }
        directory(&root)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .custom_flags(libc::O_NOFOLLOW)
            .open(root.join(".lock"))
            .map_err(|_| invalid())?;
        if !lock.metadata().map_err(|_| invalid())?.is_file() {
            return Err(invalid());
        }
        // SAFETY: this live descriptor is an owned regular lock file. Kernel
        // releases its advisory lock on close/death, including SIGKILL.
        if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(Error::new(
                "view_busy",
                "another view operation holds the store",
            ));
        }
        let store = Self { root, _lock: lock };
        if !store
            .root
            .join("catalog.json")
            .try_exists()
            .map_err(|_| invalid())?
        {
            if !fresh && !recover {
                return Err(Error::new(
                    "view_recovery_required",
                    "incomplete bootstrap; run view recover",
                ));
            }
            store.bootstrap()?;
        }
        directory(&store.root.join("objects"))?;
        Ok(store)
    }
    fn bootstrap(&self) -> Result<()> {
        // Only an empty, known bootstrap can become a new catalog. Never infer
        // an empty database when captured objects or unknown files survived.
        for e in fs::read_dir(&self.root).map_err(|_| invalid())? {
            let e = e.map_err(|_| invalid())?;
            match e.file_name().to_str() {
                Some(".lock") => regular(&e.path())?,
                Some("catalog.tmp") => {
                    regular(&e.path())?;
                    if e.metadata().map_err(|_| invalid())?.len() > 16384 {
                        return Err(invalid());
                    }
                }
                Some("objects") => {
                    directory(&e.path())?;
                    if fs::read_dir(e.path())
                        .map_err(|_| invalid())?
                        .next()
                        .is_some()
                    {
                        return Err(invalid());
                    }
                }
                _ => return Err(invalid()),
            }
        }
        let objects = self.root.join("objects");
        if !objects.exists() {
            fs::create_dir(&objects).map_err(|_| invalid())?;
        }
        let temp = self.root.join("catalog.tmp");
        if temp.exists() {
            fs::remove_file(temp).map_err(|_| invalid())?;
        }
        sync_dir(&objects)?;
        self.save(&Catalog {
            format_version: 1,
            current: None,
            views: vec![],
            managed: None,
        })
    }
    pub async fn catalog(&self) -> Result<Catalog> {
        regular(&self.root.join("catalog.json"))?;
        let b = source::read_bounded(&self.root.join("catalog.json"), 16384).await?;
        let c: Catalog = serde_json::from_slice(&b).map_err(|_| invalid())?;
        if ![1, 2, 3].contains(&c.format_version)
            || c.views.len() > 2
            || (c.format_version == 3) != c.managed.is_some()
            || c.managed.as_ref().is_some_and(|d| !d.valid(&c))
        {
            return Err(invalid());
        }
        for (i, v) in c.views.iter().enumerate() {
            if !v.valid()
                || v.version() != c.managed.as_ref().map_or(c.format_version, |d| d.mode)
                || c.views[..i]
                    .iter()
                    .any(|x| x.id == v.id || x.request_id == v.request_id)
            {
                return Err(invalid());
            }
        }
        if (c.current.is_none() && c.views.iter().any(|v| v.published))
            || c.current
                .as_ref()
                .is_some_and(|id| !c.views.iter().any(|v| &v.id == id && v.published))
        {
            return Err(invalid());
        }
        let pending = self.pending().await?;
        if let (Some(d), Some(p)) = (&c.managed, &pending) {
            if !d.operations.iter().any(|o| {
                o.id == p.request_id
                    && o.record.id == p.id
                    && o.record.source() == p.source()
                    && matches!(o.phase.as_str(), "capturing" | "ready" | "committed")
            }) {
                return Err(invalid());
            }
        }
        self.layout(&c, pending.as_ref())?;
        Ok(c)
    }
    fn layout(&self, c: &Catalog, pending: Option<&Record>) -> Result<()> {
        let mut data = 0u64;
        let mut description = 0u64;
        for entry in fs::read_dir(&self.root).map_err(|_| invalid())? {
            let entry = entry.map_err(|_| invalid())?;
            let name = entry.file_name();
            match name.to_str() {
                Some("objects" | ".staging") => directory(&entry.path())?,
                Some("catalog.json" | "catalog.tmp" | "pending.json" | ".lock") => {
                    regular(&entry.path())?;
                    let size = entry.metadata().map_err(|_| invalid())?.len();
                    if size > 16384 {
                        return Err(Error::new(
                            "resource_limit",
                            "view description exceeds budget",
                        ));
                    }
                    description += size;
                }
                _ => return Err(invalid()),
            }
        }
        let mut count = 0;
        for entry in fs::read_dir(self.root.join("objects")).map_err(|_| invalid())? {
            let entry = entry.map_err(|_| invalid())?;
            let name = entry.file_name();
            let id = name.to_str().ok_or_else(invalid)?;
            if !c.views.iter().any(|v| v.id == id) && pending.is_none_or(|v| v.id != id) {
                return Err(invalid());
            }
            count += 1;
            Self::object_size(
                &entry.path(),
                &mut data,
                &mut description,
                c.views
                    .iter()
                    .find(|v| v.id == id)
                    .or_else(|| pending.filter(|v| v.id == id))
                    .is_some_and(|v| v.features.is_some()),
            )?;
        }
        if count > 2 {
            return Err(Error::new("resource_limit", "at most two owned views"));
        }
        let staging = self.root.join(".staging");
        if staging.exists() {
            if pending.is_none() {
                return Err(invalid());
            }
            Self::object_size(
                &staging,
                &mut data,
                &mut description,
                pending.is_some_and(|v| v.features.is_some()),
            )?;
            if count >= 2 {
                return Err(Error::new(
                    "resource_limit",
                    "prepared and pending views share the two-view budget",
                ));
            }
        }
        if data > 128 << 20 || description > 1 << 20 {
            return Err(Error::new(
                "resource_limit",
                "owned view storage exceeds budget",
            ));
        }
        Ok(())
    }
    fn object_size(
        root: &Path,
        data: &mut u64,
        description: &mut u64,
        full_features: bool,
    ) -> Result<()> {
        directory(root)?;
        for e in fs::read_dir(root).map_err(|_| invalid())? {
            let e = e.map_err(|_| invalid())?;
            match e.file_name().to_str() {
                Some("features.jsonl") if full_features => {
                    regular(&e.path())?;
                    let n = e.metadata().map_err(|_| invalid())?.len();
                    if n > crate::features::FEATURE_LIMIT as u64 {
                        return Err(Error::new("resource_limit", "owned features exceed budget"));
                    }
                    *data += n;
                }
                Some("config.json") => {
                    regular(&e.path())?;
                    let n = e.metadata().map_err(|_| invalid())?.len();
                    if n > 16384 {
                        return Err(invalid());
                    }
                    *description += n;
                }
                Some("records.parquet") => {
                    regular(&e.path())?;
                    let n = e.metadata().map_err(|_| invalid())?.len();
                    if n > crate::SOURCE_LIMIT as u64 {
                        return Err(Error::new("resource_limit", "owned source exceeds budget"));
                    }
                    *data += n;
                }
                Some("images") => {
                    directory(&e.path())?;
                    let mut count = 0;
                    for image in fs::read_dir(e.path()).map_err(|_| invalid())? {
                        let image = image.map_err(|_| invalid())?;
                        let name = image.file_name();
                        let name = name.to_str().ok_or_else(invalid)?;
                        if !name.is_ascii()
                            || name.len() != 16
                            || !name.ends_with(".jpg")
                            || !name[..12].bytes().all(|b| b.is_ascii_digit())
                        {
                            return Err(invalid());
                        }
                        regular(&image.path())?;
                        let n = image.metadata().map_err(|_| invalid())?.len();
                        if n > crate::media::MEDIA_LIMIT as u64 {
                            return Err(Error::new("resource_limit", "owned media exceeds budget"));
                        }
                        *data += n;
                        count += 1;
                    }
                    if count > 3 {
                        return Err(Error::new(
                            "resource_limit",
                            "owned view exceeds three images",
                        ));
                    }
                }
                _ => return Err(invalid()),
            }
        }
        Ok(())
    }
    pub fn save(&self, c: &Catalog) -> Result<()> {
        let bytes = serde_json::to_vec(c).map_err(|_| invalid())?;
        if bytes.len() > 16384 {
            return Err(Error::new(
                "resource_limit",
                "view description exceeds budget",
            ));
        }
        let temp = self.root.join("catalog.tmp");
        write(&temp, &bytes)?;
        fs::rename(&temp, self.root.join("catalog.json")).map_err(|_| invalid())?;
        sync_dir(&self.root)
    }
    pub async fn pending(&self) -> Result<Option<Record>> {
        let p = self.root.join("pending.json");
        if !p.try_exists().map_err(|_| invalid())? {
            return Ok(None);
        }
        regular(&p)?;
        let r: Record = serde_json::from_slice(&source::read_bounded(&p, 16384).await?)
            .map_err(|_| invalid())?;
        if !r.valid() || r.published {
            return Err(invalid());
        }
        Ok(Some(r))
    }
    pub fn object(&self, id: &str) -> PathBuf {
        self.root.join("objects").join(id)
    }
    pub fn no_pending(&self) -> Result<()> {
        if self.root.join("pending.json").exists()
            || self.root.join("catalog.tmp").exists()
            || self.root.join(".staging").exists()
        {
            return Err(Error::new(
                "view_recovery_required",
                "run view recover before another mutation",
            ));
        }
        Ok(())
    }
    pub async fn recover(&self, c: &Catalog) -> Result<String> {
        let pending = self.pending().await?;
        if let Some(r) = &pending {
            if let Some(committed) = c
                .views
                .iter()
                .find(|v| v.id == r.id || v.request_id == r.request_id)
            {
                if committed.id != r.id || committed.request_id != r.request_id {
                    return Err(invalid());
                }
            } else {
                let p = self.object(&r.id);
                if p.exists() {
                    directory(&p)?;
                    fs::remove_dir_all(p).map_err(|_| invalid())?;
                }
            }
            let staging = self.root.join(".staging");
            if staging.exists() {
                directory(&staging)?;
                fs::remove_dir_all(staging).map_err(|_| invalid())?;
            }
            fs::remove_file(self.root.join("pending.json")).map_err(|_| invalid())?;
        } else if self.root.join(".staging").exists() {
            return Err(invalid());
        }
        let temp = self.root.join("catalog.tmp");
        if temp.exists() {
            regular(&temp)?;
            fs::remove_file(temp).map_err(|_| invalid())?;
        }
        sync_dir(&self.root)?;
        Ok(if pending.is_some() {
            "reconciled"
        } else {
            "clean"
        }
        .into())
    }
}
