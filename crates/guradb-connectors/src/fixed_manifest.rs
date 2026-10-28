//! Pure p04-fixed/1 metadata validation, not an object provider or read authority.
use guradb_common::cf1a::{
    canonical, digest, read::validate_range, Contract, ContractFailure, ObjectRef, Payload,
    ReadBinding, SourceVersion,
};
use serde_json::Value;
use std::collections::BTreeSet;

pub(crate) type Result<T> = std::result::Result<T, ContractFailure>;

pub(crate) fn ensure(ok: bool, code: &'static str, message: &'static str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(ContractFailure { code, message })
    }
}

/// Derived internal plan. Private fields prevent bypassing manifest validation.
#[derive(Debug)]
pub struct FixedManifestPlan {
    binding: ReadBinding,
    binding_sha256: String,
    pub(crate) sources: Vec<FixedSourcePlan>,
    rows: usize,
}

#[derive(Debug)]
pub(crate) struct FixedSourcePlan {
    pub(crate) source: SourceVersion,
    pub(crate) schema: Vec<PhysicalField>,
    pub(crate) rows: usize,
}

#[derive(Debug)]
pub(crate) struct PhysicalField {
    pub(crate) id: u64,
    pub(crate) kind: String,
    pub(crate) nullable: bool,
}

impl FixedManifestPlan {
    pub fn row_count(&self) -> usize {
        self.rows
    }

    pub fn source_count(&self) -> usize {
        self.sources.len()
    }

    pub fn binding_sha256(&self) -> String {
        self.binding_sha256.clone()
    }

    pub(crate) fn read_binding(&self) -> &ReadBinding {
        &self.binding
    }
}

fn closed(value: &Value, names: &[&str]) -> Result<()> {
    ensure(
        value.as_object().is_some_and(|map| {
            map.len() == names.len() && names.iter().all(|name| map.contains_key(*name))
        }),
        "invalid_contract",
        "unknown or missing fixed metadata field",
    )
}

fn array(value: &Value) -> Result<&[Value]> {
    value.as_array().map(Vec::as_slice).ok_or(ContractFailure {
        code: "invalid_contract",
        message: "expected fixed metadata array",
    })
}

fn natural(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .filter(|n| *n < (1 << 53))
        .ok_or(ContractFailure {
            code: "invalid_contract",
            message: "invalid fixed metadata integer",
        })
}

fn numbers(value: &Value) -> Result<()> {
    match value {
        Value::Number(_) => {
            natural(value)?;
        }
        Value::Array(items) => {
            for item in items {
                numbers(item)?;
            }
        }
        Value::Object(fields) => {
            for item in fields.values() {
                numbers(item)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn metadata(raw: &[u8]) -> Result<Value> {
    ensure(
        !raw.is_empty() && raw.len() <= 65536,
        "resource_limit",
        "fixed metadata exceeds byte bound",
    )?;
    // Bound the p04 JSON tree before parsing. Quoted punctuation is data.
    let (mut quoted, mut escaped, mut depth, mut nodes) = (false, false, 0_i32, 0);
    for (index, byte) in raw.iter().enumerate() {
        if quoted {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                quoted = false;
            }
        } else {
            ensure(
                !raw[index..].starts_with(b"NaN") && !raw[index..].starts_with(b"Infinity"),
                "invalid_contract",
                "nonfinite fixed metadata number",
            )?;
            match byte {
                b'"' => {
                    quoted = true;
                    nodes += 1;
                }
                b'[' | b'{' => {
                    depth += 1;
                    nodes += 1;
                }
                b']' | b'}' => depth -= 1,
                b',' | b':' => nodes += 1,
                _ => {}
            }
        }
        ensure(
            (0..=12).contains(&depth) && nodes <= 4096,
            "resource_limit",
            "fixed metadata exceeds structural bound",
        )?;
    }
    ensure(
        !quoted && depth == 0,
        "corrupt_object",
        "truncated fixed metadata",
    )?;
    let value: Value = serde_json::from_slice(raw).map_err(|_| ContractFailure {
        code: "corrupt_object",
        message: "invalid fixed metadata JSON",
    })?;
    numbers(&value)?;
    // Duplicates necessarily lose bytes during Value parsing, so this rejects
    // them too. Do not use Value parsing alone as a strict JSON validator.
    ensure(
        canonical(&value) == raw,
        "invalid_contract",
        "fixed metadata must be canonical JSON without duplicate fields",
    )?;
    Ok(value)
}

fn reference(value: &Value) -> Result<Vec<u8>> {
    let object: ObjectRef = serde_json::from_value(value.clone()).map_err(|_| ContractFailure {
        code: "invalid_contract",
        message: "invalid fixed object reference",
    })?;
    validate_range(&object, 0, object.size_bytes)?;
    Ok(canonical(value))
}

fn physical_schema(value: &Value) -> Result<Vec<PhysicalField>> {
    let fields = array(value)?;
    ensure(
        !fields.is_empty() && fields.len() <= 32,
        "invalid_contract",
        "invalid complete fixed schema",
    )?;
    let (mut previous, mut names, mut output) = (0, BTreeSet::new(), Vec::new());
    for field in fields {
        closed(field, &["source_field_id", "name", "type", "nullable"])?;
        let id = natural(&field["source_field_id"])?;
        ensure(
            id > previous && id < (1 << 31),
            "invalid_contract",
            "physical field IDs must be positive unique ascending int31",
        )?;
        let name = field["name"].as_str().ok_or(ContractFailure {
            code: "invalid_contract",
            message: "invalid physical field name",
        })?;
        ensure(
            !name.is_empty()
                && name.chars().count() <= 128
                && !name.contains('\0')
                && names.insert(name),
            "invalid_contract",
            "invalid or duplicate physical field name",
        )?;
        let kind = field["type"].as_str().unwrap_or("");
        ensure(
            ["text", "int8", "bool"].contains(&kind) && field["nullable"].is_boolean(),
            "unsupported_capability",
            "unsupported fixed physical field",
        )?;
        output.push(PhysicalField {
            id,
            kind: kind.into(),
            nullable: field["nullable"] == true,
        });
        previous = id;
    }
    Ok(output)
}

#[derive(Default)]
struct Totals {
    files: usize,
    groups: usize,
    rows: usize,
    bytes: u64,
    width: usize,
}

fn source_manifest(
    raw: &[u8],
    source: &SourceVersion,
    members: &mut BTreeSet<Vec<u8>>,
    totals: &mut Totals,
) -> Result<FixedSourcePlan> {
    let value = metadata(raw)?;
    closed(
        &value,
        &[
            "manifest_version",
            "source_id",
            "source_version_id",
            "snapshot_id",
            "source_schema",
            "files",
            "delete_files",
            "schema_evolution",
        ],
    )?;
    ensure(
        value["manifest_version"] == "p04-fixed/1",
        "unsupported_version",
        "unsupported fixed metadata version",
    )?;
    ensure(
        value["delete_files"].as_array().is_some_and(Vec::is_empty)
            && value["schema_evolution"] == "none",
        "unsupported_capability",
        "source delete or schema evolution is unsupported",
    )?;
    ensure(
        value["source_id"] == source.source_id
            && value["source_version_id"] == source.source_version_id
            && value["snapshot_id"] == source.snapshot_id,
        "corrupt_object",
        "fixed source identity mismatch",
    )?;
    let schema = physical_schema(&value["source_schema"])?;
    ensure(
        digest(&value["source_schema"]) == source.source_schema_sha256,
        "corrupt_object",
        "complete physical schema digest mismatch",
    )?;
    for mapping in &source.field_mapping {
        if mapping.source_field_id != 0 {
            ensure(
                schema.iter().any(|field| {
                    field.id == mapping.source_field_id && field.kind == mapping.source_type
                }),
                "corrupt_object",
                "source mapping references a missing or wrong physical field",
            )?;
        }
    }
    let files = array(&value["files"])?;
    ensure(
        files.len() <= 4,
        "resource_limit",
        "fixed file count exceeded",
    )?;
    let mut rows = 0;
    for file in files {
        closed(file, &["object", "row_group_rows"])?;
        let encoded = reference(&file["object"])?;
        ensure(
            members.insert(encoded),
            "invalid_contract",
            "shared fixed data or metadata object",
        )?;
        let size = natural(&file["object"]["size_bytes"])?;
        ensure(
            size <= 1 << 20,
            "resource_limit",
            "fixed data file exceeds byte bound",
        )?;
        let groups = array(&file["row_group_rows"])?;
        ensure(
            !groups.is_empty() && groups.len() <= 16,
            "invalid_contract",
            "invalid fixed row groups",
        )?;
        for group in groups {
            let count = natural(group)?;
            ensure(
                (1..=1000).contains(&count),
                "invalid_contract",
                "invalid fixed group rows",
            )?;
            rows += count as usize;
        }
        totals.files += 1;
        totals.groups += groups.len();
        totals.bytes += size;
    }
    totals.rows += rows;
    totals.width += schema.len();
    ensure(
        totals.files <= 4
            && totals.groups <= 16
            && totals.rows <= 1000
            && totals.bytes <= 4 << 20
            && totals.width <= 32,
        "resource_limit",
        "combined fixed source bounds exceeded",
    )?;
    Ok(FixedSourcePlan {
        source: source.clone(),
        schema,
        rows,
    })
}

/// Validate supplied bytes only. The caller still owns reads, byte integrity,
/// current authorization, parent accounting and cancellation/stop guarantees.
pub fn validate_manifests(binding: &Contract, raw: &[&[u8]]) -> Result<FixedManifestPlan> {
    let input = match &binding.envelope().payload {
        Payload::ReadBinding(value) => value,
        _ => {
            return Err(ContractFailure {
                code: "invalid_contract",
                message: "expected fixed read binding",
            })
        }
    };
    let sources = &input.revision.sources;
    ensure(
        (1..=2).contains(&sources.len())
            && sources
                .iter()
                .all(|source| source.format == "manifest" && source.format_version == "1"),
        "unsupported_capability",
        "only one or two fixed manifest/1 sources are supported",
    )?;
    ensure(
        raw.len() == sources.len(),
        "invalid_contract",
        "metadata source count mismatch",
    )?;
    ensure(
        input.resource.fields.len() <= 32,
        "resource_limit",
        "fixed resource schema too wide",
    )?;
    let mut members = BTreeSet::new();
    let mut metadata_bytes = 0_u64;
    for (source, bytes) in sources.iter().zip(raw) {
        let encoded = serde_json::to_value(&source.metadata).map_err(|_| ContractFailure {
            code: "invalid_contract",
            message: "invalid metadata object reference",
        })?;
        ensure(
            members.insert(reference(&encoded)?),
            "invalid_contract",
            "shared fixed metadata object",
        )?;
        metadata_bytes += source.metadata.size_bytes;
        ensure(
            bytes.len() as u64 == source.metadata.size_bytes
                && guradb_common::digest(bytes) == source.metadata.sha256,
            "corrupt_object",
            "fixed metadata byte identity mismatch",
        )?;
    }
    ensure(
        metadata_bytes <= 65536,
        "resource_limit",
        "combined metadata exceeds byte bound",
    )?;
    let mut totals = Totals::default();
    let mut planned = Vec::new();
    for (source, bytes) in sources.iter().zip(raw) {
        planned.push(source_manifest(bytes, source, &mut members, &mut totals)?);
    }
    let expected: BTreeSet<_> = input
        .revision
        .objects
        .iter()
        .map(|object| {
            canonical(&serde_json::to_value(object).expect("common ObjectRef is serializable"))
        })
        .collect();
    ensure(
        members == expected,
        "unsupported_capability",
        "fixed revision object closure mismatch",
    )?;
    Ok(FixedManifestPlan {
        binding: (**input).clone(),
        binding_sha256: binding.sha256(),
        sources: planned,
        rows: totals.rows,
    })
}

#[cfg(test)]
mod parser_boundary_tests {
    use super::metadata;
    use serde_json::Value;

    fn nested_arrays(depth: usize) -> Vec<u8> {
        // Both peers are complete JSON, not an unterminated bracket probe.
        let mut raw = vec![b'['; depth];
        raw.push(b'0');
        raw.extend(std::iter::repeat_n(b']', depth));
        raw
    }

    fn scalar_array(elements: usize) -> Vec<u8> {
        let items = vec!["0"; elements];
        format!("[{}]", items.join(",")).into_bytes()
    }

    fn ascii_string(bytes: usize) -> Vec<u8> {
        let mut raw = vec![b'a'; bytes];
        raw[0] = b'"';
        raw[bytes - 1] = b'"';
        raw
    }

    #[test]
    fn complete_canonical_depth_twelve_succeeds_thirteen_is_resource_limit() {
        let allowed = nested_arrays(12);
        let over = nested_arrays(13);
        // Independent syntax acceptance isolates the preflight depth refusal.
        assert!(serde_json::from_slice::<Value>(&allowed).is_ok());
        assert!(serde_json::from_slice::<Value>(&over).is_ok());
        let mut parsed = metadata(&allowed).unwrap();
        for _ in 0..12 {
            let array = parsed.as_array().unwrap();
            assert_eq!(array.len(), 1);
            parsed = array[0].clone();
        }
        assert_eq!(parsed.as_u64(), Some(0));
        assert_eq!(metadata(&over).unwrap_err().code, "resource_limit");
    }

    #[test]
    fn complete_canonical_structure_counter_4096_succeeds_4097_is_resource_limit() {
        // n literal zeros: 1 array opener + (n - 1) commas = n, depth 1.
        let allowed = scalar_array(4096);
        let over = scalar_array(4097);
        assert_eq!(allowed.len(), 8193);
        assert_eq!(over.len(), 8195);
        let syntax: Value = serde_json::from_slice(&over).unwrap();
        assert_eq!(syntax.as_array().unwrap().len(), 4097);
        let parsed = metadata(&allowed).unwrap();
        let array = parsed.as_array().unwrap();
        assert_eq!(array.len(), 4096);
        assert!(array.iter().all(|value| value.as_u64() == Some(0)));
        assert_eq!(metadata(&over).unwrap_err().code, "resource_limit");
    }

    #[test]
    fn complete_canonical_65536_bytes_succeeds_65537_is_resource_limit() {
        // Quotation marks are part of the byte budget; no whitespace padding.
        let allowed = ascii_string(65536);
        let over = ascii_string(65537);
        assert_eq!(allowed.len(), 65536);
        assert_eq!(over.len(), 65537);
        let syntax: Value = serde_json::from_slice(&over).unwrap();
        assert_eq!(syntax.as_str().unwrap().len(), 65535);
        let parsed = metadata(&allowed).unwrap();
        assert_eq!(parsed.as_str().unwrap(), "a".repeat(65534));
        assert_eq!(metadata(&over).unwrap_err().code, "resource_limit");
    }

    #[test]
    fn canonical_integer_limit_and_rejected_numeric_tokens_have_exact_codes() {
        let parsed = metadata(b"9007199254740991").unwrap();
        assert_eq!(parsed.as_u64(), Some(9_007_199_254_740_991));
        for token in [
            "-0",
            "-1",
            "1.0",
            "1e0",
            "9007199254740992",
            "18446744073709551615",
        ] {
            assert!(serde_json::from_slice::<Value>(token.as_bytes()).is_ok());
            assert_eq!(
                metadata(token.as_bytes()).unwrap_err().code,
                "invalid_contract",
                "numeric token {token}",
            );
        }
    }
}
