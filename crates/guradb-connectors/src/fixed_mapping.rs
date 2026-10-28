//! One pure record mapping for future ordinary and located source outputs.
use crate::fixed_manifest::{ensure, FixedManifestPlan, PhysicalField, Result};
use guradb_common::{
    cf1a::{Cell, ContractFailure, Record},
    encode_key,
};
use std::collections::{BTreeMap, BTreeSet};

/// Cells already decoded by the caller, keyed by physical field ID, not rowid.
pub type PhysicalRow = BTreeMap<u64, Cell>;

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "latest"
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
}

fn check_cell(value: &Cell, field: &PhysicalField) -> Result<()> {
    if let Cell::Text(text) = value {
        ensure(
            text.chars().count() <= 4096,
            "resource_limit",
            "physical text exceeds fixed bound",
        )?;
    }
    let valid = match value {
        Cell::Null(()) => field.nullable,
        Cell::Text(_) => field.kind == "text",
        Cell::Bool(_) => field.kind == "bool",
        Cell::Int8(text) => {
            field.kind == "int8"
                && text
                    .parse::<i64>()
                    .is_ok_and(|number| number.to_string() == *text)
        }
    };
    ensure(
        valid,
        "corrupt_object",
        "physical cell type or nullability mismatch",
    )
}

fn key(value: &Cell) -> Result<Cell> {
    let bytes = match value {
        Cell::Text(text) => {
            ensure(
                text.len() <= 54,
                "resource_limit",
                "encoded text key exceeds fixed ID bound",
            )?;
            encode_key(&[("text", text.as_bytes())])
        }
        Cell::Int8(text) => {
            let number = text.parse::<i64>().map_err(|_| ContractFailure {
                code: "corrupt_object",
                message: "invalid typed int8 key",
            })?;
            encode_key(&[("int8", &number.to_be_bytes())])
        }
        _ => {
            return Err(ContractFailure {
                code: "corrupt_object",
                message: "NULL or invalid logical source key",
            })
        }
    }
    .map_err(|_| ContractFailure {
        code: "corrupt_object",
        message: "invalid source key encoding",
    })?;
    let mut encoded = String::with_capacity(bytes.len() * 2);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for byte in bytes {
        encoded.push(HEX[(byte >> 4) as usize] as char);
        encoded.push(HEX[(byte & 15) as usize] as char);
    }
    Ok(Cell::Text(encoded))
}

/// Map the supplied complete source sets in plan order. Row counts and physical
/// field sets must match the metadata. This does not attest to Parquet decoding,
/// fixed object integrity, authorization or the actual origin of supplied rows.
pub fn map_records(plan: &FixedManifestPlan, rows: &[Vec<PhysicalRow>]) -> Result<Vec<Record>> {
    ensure(
        rows.len() == plan.sources.len(),
        "invalid_contract",
        "physical source count mismatch",
    )?;
    let binding = plan.read_binding();
    let mut output = Vec::new();
    let mut seen = BTreeSet::new();
    for (source, input) in plan.sources.iter().zip(rows) {
        ensure(
            input.len() == source.rows,
            "corrupt_object",
            "incomplete supplied source rows",
        )?;
        for row in input {
            ensure(
                row.len() == source.schema.len(),
                "corrupt_object",
                "physical row width mismatch",
            )?;
            for field in &source.schema {
                let value = row.get(&field.id).ok_or(ContractFailure {
                    code: "corrupt_object",
                    message: "physical row field ID mismatch",
                })?;
                check_cell(value, field)?;
            }
            let (mut cells, mut record_id, mut record_version) =
                (Vec::new(), String::new(), String::new());
            for field in &binding.resource.fields {
                let mapping = source
                    .source
                    .field_mapping
                    .iter()
                    .find(|mapping| mapping.resource_field_id == field.field_id)
                    .ok_or(ContractFailure {
                        code: "invalid_contract",
                        message: "missing common field mapping",
                    })?;
                let value = if mapping.transform == "revision_version" {
                    Cell::Text(binding.revision.data_revision_id.clone())
                } else {
                    let raw = row.get(&mapping.source_field_id).ok_or(ContractFailure {
                        code: "corrupt_object",
                        message: "mapped physical field missing",
                    })?;
                    if mapping.transform == "key_v1" {
                        key(raw)?
                    } else {
                        raw.clone()
                    }
                };
                ensure(
                    !matches!(value, Cell::Null(())) || field.nullable,
                    "corrupt_object",
                    "NULL in nonnullable mapped field",
                )?;
                if field.role != "value" {
                    let id = match &value {
                        Cell::Text(id) if valid_id(id) => id.clone(),
                        _ => {
                            return Err(ContractFailure {
                                code: "invalid_contract",
                                message: "invalid stable source ID or version",
                            })
                        }
                    };
                    if field.role == "logical_id" {
                        record_id = id;
                    } else {
                        record_version = id;
                    }
                }
                cells.push(value);
            }
            ensure(
                seen.insert(record_id.clone()),
                "corrupt_object",
                "duplicate logical source identity",
            )?;
            output.push(Record {
                record_id,
                record_version,
                cells,
            });
        }
    }
    output.sort_by(|left, right| left.record_id.cmp(&right.record_id));
    Ok(output)
}
