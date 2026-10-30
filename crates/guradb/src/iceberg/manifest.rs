//! Apache Avro reads all OCF records; a bounded header guard narrows codecs.
use super::{invalid, metadata, path};
use crate::{Error, Result};
use apache_avro::{from_avro_datum, types::Value, Reader, Schema};
use std::{collections::BTreeMap, io::Cursor};

type OcfHeader = BTreeMap<String, Vec<u8>>;

pub struct Manifest {
    pub path: String,
    pub length: usize,
    pub counts: [usize; 3],
}
pub struct DataFile {
    pub path: String,
    pub size: usize,
    pub rows: usize,
    pub status: usize,
}
fn value<'a>(record: &'a Value, key: &str) -> Result<&'a Value> {
    let Value::Record(fields) = record else {
        return Err(invalid());
    };
    fields
        .iter()
        .find(|(name, _)| name == key)
        .map(|(_, v)| unbox(v))
        .ok_or_else(invalid)
}
fn optional<'a>(record: &'a Value, key: &str) -> Option<&'a Value> {
    let Value::Record(fields) = record else {
        return None;
    };
    fields
        .iter()
        .find(|(name, _)| name == key)
        .map(|(_, v)| unbox(v))
}
fn unbox(mut value: &Value) -> &Value {
    while let Value::Union(_, inner) = value {
        value = inner;
    }
    value
}
fn number(value: &Value) -> Result<i64> {
    match value {
        Value::Int(n) => Ok(*n as i64),
        Value::Long(n) => Ok(*n),
        _ => Err(invalid()),
    }
}
fn count(record: &Value, key: &str) -> Result<usize> {
    usize::try_from(number(value(record, key)?)?).map_err(|_| invalid())
}
fn string<'a>(record: &'a Value, key: &str) -> Result<&'a str> {
    match value(record, key)? {
        Value::String(s) => Ok(s),
        _ => Err(invalid()),
    }
}
fn header(bytes: &[u8]) -> Result<OcfHeader> {
    if !bytes.starts_with(b"Obj\x01") {
        return Err(invalid());
    }
    // Use the official datum parser solely for the OCF map(bytes) header.
    // Reader below still validates magic, declared writer schema and sync marks.
    let schema = Schema::parse_str(r#"{"type":"map","values":"bytes"}"#).map_err(|_| invalid())?;
    let value =
        from_avro_datum(&schema, &mut Cursor::new(&bytes[4..]), None).map_err(|_| invalid())?;
    let Value::Map(values) = value else {
        return Err(invalid());
    };
    if values.len() > 32 {
        return Err(invalid());
    }
    let fields: BTreeMap<_, _> = values
        .into_iter()
        .map(|(key, value)| match value {
            Value::Bytes(bytes) => Ok((key, bytes)),
            _ => Err(invalid()),
        })
        .collect::<Result<_>>()?;
    let codec = fields
        .get("avro.codec")
        .map(Vec::as_slice)
        .unwrap_or(b"null");
    // Apache Avro 0.20 deflate expands with an unbounded Vec; reject it before
    // constructing Reader. Only null OCF blocks are admitted in this slice.
    if codec != b"null" || !fields.contains_key("avro.schema") {
        return Err(invalid());
    }
    Ok(fields)
}
fn records(bytes: &[u8], maximum: usize) -> Result<(OcfHeader, Vec<Value>)> {
    if apache_avro::max_allocation_bytes(2 << 20) > 2 << 20 {
        return Err(Error::new(
            "resource_limit",
            "Avro allocation limit was not installed",
        ));
    }
    let header = header(bytes)?;
    let reader = Reader::new(Cursor::new(bytes)).map_err(|_| invalid())?;
    let mut records = Vec::new();
    for value in reader {
        if records.len() == maximum {
            return Err(Error::new(
                "resource_limit",
                "Iceberg Avro entry limit exceeded",
            ));
        }
        records.push(value.map_err(|_| invalid())?);
    }
    Ok((header, records))
}
pub fn list(bytes: &[u8], meta: &metadata::Metadata) -> Result<Vec<Manifest>> {
    let (header, records) = records(bytes, 2)?;
    let snapshot = header
        .get("snapshot-id")
        .and_then(|v| std::str::from_utf8(v).ok())
        .and_then(|v| v.parse::<i64>().ok())
        .ok_or_else(invalid)?;
    if snapshot != meta.snapshot {
        return Err(invalid());
    }
    let mut manifests = Vec::new();
    for record in records {
        if number(value(&record, "partition_spec_id")?)? != 0
            || number(value(&record, "content")?)? != 0
        {
            return Err(invalid());
        }
        manifests.push(Manifest {
            path: path::relocate(&meta.logical_root, string(&record, "manifest_path")?)?,
            length: count(&record, "manifest_length")?,
            counts: [
                count(&record, "existing_files_count")?,
                count(&record, "added_files_count")?,
                count(&record, "deleted_files_count")?,
            ],
        });
    }
    Ok(manifests)
}
pub fn entries(
    bytes: &[u8],
    meta: &metadata::Metadata,
    expected: &[usize; 3],
) -> Result<Vec<DataFile>> {
    let (header, records) = records(bytes, 32)?;
    let get = |key: &str| header.get(key).map(Vec::as_slice).ok_or_else(invalid);
    if get("format-version")? != b"2"
        || get("content")? != b"data"
        || get("partition-spec-id")? != b"0"
    {
        return Err(invalid());
    }
    let spec: serde_json::Value =
        serde_json::from_slice(get("partition-spec")?).map_err(|_| invalid())?;
    if spec.as_array().is_none_or(|a| !a.is_empty()) {
        return Err(invalid());
    }
    let schema: serde_json::Value =
        serde_json::from_slice(get("schema")?).map_err(|_| invalid())?;
    let (schema_id, fields) = metadata::schema(&schema)?;
    if schema_id != meta.schema_id || fields != meta.fields {
        return Err(invalid());
    }
    let mut files = Vec::new();
    let mut counts = [0usize; 3];
    for record in records {
        let status = count(&record, "status")?;
        if status > 2 {
            return Err(invalid());
        }
        counts[status] += 1;
        let data = value(&record, "data_file")?;
        if number(value(data, "content")?)? != 0 || string(data, "file_format")? != "PARQUET" {
            return Err(invalid());
        }
        match value(data, "partition")? {
            Value::Record(fields) if fields.is_empty() => (),
            _ => return Err(invalid()),
        }
        for key in [
            "equality_ids",
            "key_metadata",
            "referenced_data_file",
            "content_offset",
            "content_size_in_bytes",
        ] {
            if let Some(value) = optional(data, key) {
                if !matches!(value, Value::Null)
                    && !matches!(value, Value::Array(a) if a.is_empty())
                {
                    return Err(invalid());
                }
            }
        }
        if let Some(value) = optional(data, "sort_order_id") {
            if !matches!(value, Value::Null) && number(value)? != 0 {
                return Err(invalid());
            }
        }
        files.push(DataFile {
            path: path::relocate(&meta.logical_root, string(data, "file_path")?)?,
            size: count(data, "file_size_in_bytes")?,
            rows: count(data, "record_count")?,
            status,
        });
    }
    if &counts != expected {
        return Err(invalid());
    }
    Ok(files)
}

#[cfg(test)]
mod tests {
    use super::*;
    use apache_avro::{Codec, Writer};
    fn ocf(codec: Codec, count: usize) -> Vec<u8> {
        apache_avro::max_allocation_bytes(2 << 20);
        let schema = Schema::parse_str("\"long\"").unwrap();
        let mut writer = Writer::with_codec(&schema, Vec::new(), codec);
        for i in 0..count {
            writer.append(Value::Long(i as i64)).unwrap();
        }
        writer.into_inner().unwrap()
    }
    #[test]
    fn official_ocf_codec_guard_and_entry_limit_are_fail_closed() {
        let null = ocf(Codec::Null, 2);
        assert_eq!(records(&null, 2).unwrap().1.len(), 2);
        assert_eq!(records(&null, 1).err().unwrap().code, "resource_limit");
        let deflate = ocf(Codec::Deflate(Default::default()), 2);
        assert_eq!(records(&deflate, 2).err().unwrap().code, "unsupported");
        assert!(records(b"not avro", 2).is_err());
        assert!(records(&null[..null.len() - 1], 2).is_err());
    }
}
