//! Test-only immutable Parquet fixture, with literal source truth.
use arrow::{
    array::{ArrayRef, BooleanArray, Int64Array, StringArray},
    datatypes::{DataType, Field, Schema},
    record_batch::RecordBatch,
};
use guradb_catalog::Catalog;
use guradb_common::{digest, manifest::ManifestRef};
use parquet::arrow::ArrowWriter;
use serde_json::json;
use std::{path::PathBuf, sync::Arc};

static NEXT_FIXTURE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

pub const DATASET: &str = "89b349e2-cc73-4c22-871d-c80a159d7789";
pub struct Fixture {
    pub root: PathBuf,
    pub catalog: Catalog,
}
impl Fixture {
    pub fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "gura-unit-{}-{}-{}",
            std::process::id(),
            NEXT_FIXTURE.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        let schema = Arc::new(Schema::new(vec![
            Field::new("id", DataType::Int64, false),
            Field::new("title", DataType::Utf8, true),
            Field::new("active", DataType::Boolean, true),
        ]));
        let arrays: Vec<ArrayRef> = vec![
            Arc::new(Int64Array::from(vec![1, 2, i64::MAX])),
            Arc::new(StringArray::from(vec![Some("alpha"), Some("数据库"), None])),
            Arc::new(BooleanArray::from(vec![Some(true), Some(false), None])),
        ];
        let batch = RecordBatch::try_new(schema.clone(), arrays).unwrap();
        let mut raw = Vec::new();
        let mut writer = ArrowWriter::try_new(&mut raw, schema, None).unwrap();
        writer.write(&batch).unwrap();
        writer.close().unwrap();
        std::fs::write(root.join("data.parquet"), &raw).unwrap();
        let manifest = json!({"schema_version":1,"dataset_id":DATASET,"table_name":"documents","schema":[{"name":"id","data_type":"int8","nullable":false},{"name":"title","data_type":"text","nullable":true},{"name":"active","data_type":"bool","nullable":true}],"backend":{"kind":"local","root":root},"files":[{"fragment_id":"f0","key":"data.parquet","size_bytes":raw.len(),"sha256":digest(&raw)}],"retention_mode":"best-effort"});
        let bytes = serde_json::to_vec(&manifest).unwrap();
        let path = root.join("manifest.json");
        std::fs::write(&path, &bytes).unwrap();
        let mut catalog = guradb_catalog::load(&[ManifestRef {
            path: path.to_str().unwrap().into(),
            sha256: digest(&bytes),
        }])
        .unwrap();
        Arc::get_mut(catalog.get_mut("documents").unwrap())
            .unwrap()
            .context
            .read_view_id = "view".into();
        Self { root, catalog }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        if let Err(error) = std::fs::remove_dir_all(&self.root) {
            if !std::thread::panicking() {
                panic!("fixture cleanup failed: {error}");
            }
        }
    }
}
