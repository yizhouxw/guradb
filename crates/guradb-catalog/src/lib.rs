use guradb_common::{
    digest,
    manifest::{Manifest, ManifestRef},
    protocol::{ReadContext, SourceVersion},
    Error, Result,
};
use guradb_storage::Source;
use std::{collections::HashMap, io::Read, sync::Arc};

pub struct Dataset {
    pub manifest: Manifest,
    pub source: Source,
    pub context: ReadContext,
}
pub type Catalog = HashMap<String, Arc<Dataset>>;

pub fn load(references: &[ManifestRef]) -> Result<Catalog> {
    if references.is_empty() || references.len() > 16 {
        return Err(Error::new("invalid_config", "expected 1..16 manifests"));
    }
    let mut catalog = HashMap::new();
    let mut identities = std::collections::HashSet::new();
    for reference in references {
        let mut bytes = Vec::new();
        std::fs::File::open(&reference.path)
            .map_err(|_| Error::new("invalid_manifest", "manifest is unavailable"))?
            .take(256 * 1024 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| Error::new("invalid_manifest", "cannot read manifest"))?;
        if bytes.len() > 256 * 1024 || digest(&bytes) != reference.sha256 {
            return Err(Error::new(
                "invalid_manifest",
                "manifest exceeds limit or differs from pinned SHA-256",
            ));
        }
        let manifest: Manifest = serde_json::from_slice(&bytes)
            .map_err(|_| Error::new("invalid_manifest", "invalid manifest JSON"))?;
        manifest.validate()?;
        if catalog.contains_key(&manifest.table_name)
            || !identities.insert(manifest.dataset_id.clone())
        {
            return Err(Error::new(
                "invalid_manifest",
                "duplicate table or dataset identity",
            ));
        }
        let context = ReadContext {
            read_consistency: "published".into(),
            data_revision_id: format!("rev_{}", reference.sha256),
            read_view_id: format!("view_{}", reference.sha256),
            source_versions: vec![SourceVersion {
                source_id: manifest.dataset_id.clone(),
                format: "parquet-manifest-v1".into(),
                version: reference.sha256.clone(),
            }],
            index_versions: vec![],
        };
        let source = Source::new(&manifest.backend)?;
        catalog.insert(
            manifest.table_name.clone(),
            Arc::new(Dataset {
                manifest,
                source,
                context,
            }),
        );
    }
    Ok(catalog)
}
