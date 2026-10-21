//! CF1-A typed wire values; closed schema and validation live in sibling modules.
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Field {
    pub field_id: u64,
    pub name: String,
    #[serde(rename = "type")]
    pub r#type: String,
    pub nullable: bool,
    pub role: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceDescriptor {
    pub tenant_id: String,
    pub namespace_id: String,
    pub dataset_id: String,
    pub display_name: String,
    pub schema_id: String,
    pub schema_version: u64,
    pub schema_sha256: String,
    pub fields: Vec<Field>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Integrity {
    pub mode: String,
    pub block_size: u64,
    pub block_sha256: Vec<String>,
    pub proof_ref: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectRef {
    pub backend_id: String,
    pub bucket: String,
    pub key: String,
    pub version: String,
    pub size_bytes: u64,
    pub sha256: String,
    pub integrity: Integrity,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FieldMapping {
    pub source_field_id: u64,
    pub resource_field_id: u64,
    #[serde(rename = "type")]
    pub r#type: String,
    pub source_type: String,
    pub transform: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SourceVersion {
    pub source_id: String,
    pub source_version_id: String,
    pub format: String,
    pub format_version: String,
    pub snapshot_id: String,
    pub source_schema_sha256: String,
    pub resource_schema_sha256: String,
    pub metadata: ObjectRef,
    pub field_mapping: Vec<FieldMapping>,
    pub protected_until_unix_ms: u64,
    pub protection_ref: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DataRevision {
    pub data_revision_id: String,
    pub dataset_id: String,
    pub schema_id: String,
    pub schema_version: u64,
    pub parent_revision_ids: Vec<String>,
    pub sources: Vec<SourceVersion>,
    pub objects: Vec<ObjectRef>,
    pub content_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Usage {
    pub object_requests: u64,
    pub object_bytes: u64,
    pub memory_bytes: u64,
    pub output_bytes: u64,
    pub elapsed_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Budget {
    pub memory_bytes: u64,
    pub object_requests: u64,
    pub object_bytes: u64,
    pub candidates: u64,
    pub top_k: u64,
    pub graph_edges: u64,
    pub output_bytes: u64,
    pub concurrency: u64,
    pub temp_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IndexArtifact {
    pub artifact_id: String,
    pub build_id: String,
    pub data_revision_id: String,
    pub schema_sha256: String,
    pub kind: String,
    pub model_id: String,
    pub model_version: String,
    pub dimension: u64,
    pub format_id: String,
    pub format_version: u64,
    pub configuration_sha256: String,
    pub processing_version: String,
    pub metric: String,
    pub analyzer: String,
    pub source_version_ids: Vec<String>,
    pub logical_mapping_sha256: String,
    pub deletion_mode: String,
    pub deletion_watermark: u64,
    pub shard_count: u64,
    pub shards: Vec<ObjectRef>,
    pub build_usage: Usage,
    pub reader_capabilities: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IndexRequirement {
    pub artifact_id: String,
    pub model_id: String,
    pub model_version: String,
    pub dimension: u64,
    pub metric: String,
    pub analyzer: String,
    pub format_id: String,
    pub format_version: u64,
    pub configuration_sha256: String,
    pub processing_version: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReadView {
    pub read_view_id: String,
    pub data_revision_id: String,
    pub publication_generation: u64,
    pub publication_sequence: u64,
    pub required_artifact_ids: Vec<String>,
    pub index_requirements: Vec<IndexRequirement>,
    pub descriptor_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthContext {
    pub tenant_id: String,
    pub subject_id: String,
    pub dataset_id: String,
    pub actions: Vec<String>,
    pub policy_epoch: u64,
    pub expires_unix_ms: u64,
    pub delegation_ref: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Pin {
    pub pin_id: String,
    pub lease_id: String,
    pub data_revision_id: String,
    pub read_view_id: String,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QueryContext {
    pub request_id: String,
    pub query_id: String,
    pub tenant_id: String,
    pub dataset_id: String,
    pub schema_id: String,
    pub schema_version: u64,
    pub data_revision_id: String,
    pub read_view_id: String,
    pub source_version_ids: Vec<String>,
    pub artifact_ids: Vec<String>,
    pub auth: AuthContext,
    pub pin: Pin,
    pub bound_at_unix_ms: u64,
    pub deadline_unix_ms: u64,
    pub remaining_ttl_ms: u64,
    pub budget: Budget,
    pub cancellation_id: String,
    pub trace_id: String,
    pub span_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReadDescriptors {
    pub resource: ResourceDescriptor,
    pub revision: DataRevision,
    pub view: ReadView,
    pub indexes: Vec<IndexArtifact>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReadBinding {
    pub resource: ResourceDescriptor,
    pub revision: DataRevision,
    pub view: ReadView,
    pub indexes: Vec<IndexArtifact>,
    pub context: QueryContext,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BindRequest {
    pub tenant_id: String,
    pub subject_id: String,
    pub dataset_id: String,
    pub delegation_ref: String,
    pub request_id: String,
    pub query_id: String,
    pub view_mode: String,
    pub read_view_id: String,
    pub timeout_ms: u64,
    pub budget: Budget,
    pub cancellation_id: String,
    pub trace_id: String,
    pub span_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RowLocator {
    pub source_version_id: String,
    pub object: ObjectRef,
    pub row_group: u64,
    pub row_offset: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Candidate {
    pub record_id: String,
    pub record_version: String,
    pub score_f64_hex: String,
    pub locator: RowLocator,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IndexQuery {
    pub context_sha256: String,
    pub artifact_id: String,
    pub kind: String,
    pub model_id: String,
    pub model_version: String,
    pub dimension: u64,
    pub metric: String,
    pub analyzer: String,
    pub configuration_sha256: String,
    pub processing_version: String,
    pub top_k: u64,
    pub candidate_limit: u64,
    pub query_text: String,
    pub query_vector_f64_hex: Vec<String>,
    pub filter_mode: String,
    pub allowed_record_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateBatch {
    pub context_sha256: String,
    pub index_query_sha256: String,
    pub artifact_id: String,
    pub metric: String,
    pub score_order: String,
    pub complete: bool,
    pub rows: Vec<Candidate>,
    pub usage: Usage,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub record_id: String,
    pub record_version: String,
    pub cells: Vec<Cell>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReadBatch {
    pub context_sha256: String,
    pub schema_id: String,
    pub schema_version: u64,
    pub fields: Vec<Field>,
    pub batch_ordinal: u64,
    pub last: bool,
    pub truncated: bool,
    pub ordering: String,
    pub rows: Vec<Record>,
    pub usage: Usage,
    pub content_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MutationAuth {
    pub tenant_id: String,
    pub subject_id: String,
    pub dataset_id: String,
    pub actions: Vec<String>,
    pub policy_epoch: u64,
    pub expires_unix_ms: u64,
    pub delegation_ref: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegisterIntent {
    pub operation_id: String,
    pub tenant_id: String,
    pub dataset_id: String,
    pub expected_generation: u64,
    pub owner_epoch: u64,
    pub revision_sha256: String,
    pub target_revision_id: String,
    pub target_descriptors_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublishIntent {
    pub operation_id: String,
    pub tenant_id: String,
    pub dataset_id: String,
    pub expected_generation: u64,
    pub owner_epoch: u64,
    pub expected_view_id: String,
    pub target_view_id: String,
    pub target_revision_id: String,
    pub target_descriptors_sha256: String,
    pub target_revision_sha256: String,
    pub target_view_sha256: String,
    pub publication_sequence: u64,
    pub artifact_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MutationReceipt {
    pub operation_id: String,
    pub request_sha256: String,
    pub state: String,
    pub generation: u64,
    pub result_id: String,
    pub reconcile_ref: String,
    pub error_code: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReaderConfig {
    pub max_envelope_bytes: u64,
    pub max_batch_rows: u64,
    pub max_ttl_ms: u64,
    pub capabilities: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ContractError {
    pub code: String,
    pub diagnostic_id: String,
    pub retryable: bool,
    pub reconcile_ref: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(
    tag = "type",
    content = "value",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum Cell {
    Null(()),
    Text(String),
    Bool(bool),
    Int8(String),
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum Payload {
    ReadBinding(Box<ReadBinding>),
    ReadBatch(ReadBatch),
    RegisterIntent(RegisterIntent),
    PublishIntent(PublishIntent),
    MutationReceipt(MutationReceipt),
    ReaderConfig(ReaderConfig),
    ContractError(ContractError),
    BindRequest(BindRequest),
    CandidateBatch(CandidateBatch),
    MutationAuth(MutationAuth),
    IndexQuery(IndexQuery),
    ReadDescriptors(Box<ReadDescriptors>),
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Envelope {
    pub contract_version: String,
    pub required_capabilities: Vec<String>,
    pub payload: Payload,
}

impl ObjectRef {
    /// Immutable physical object identity, without backend or cache policy.
    pub fn immutable_locator(&self) -> (&str, &str, &str, &str) {
        (&self.backend_id, &self.bucket, &self.key, &self.version)
    }
}
