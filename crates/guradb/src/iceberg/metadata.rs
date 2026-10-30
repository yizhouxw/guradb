use super::{invalid, path};
use crate::Result;
use serde_json::Value;
use std::collections::HashSet;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Field {
    pub id: i32,
    pub name: String,
    pub kind: String,
    pub required: bool,
}
pub struct Metadata {
    pub uuid: String,
    pub schema_id: i64,
    pub fields: Vec<Field>,
    pub logical_root: String,
    pub manifest_list: String,
    pub snapshot: i64,
}
pub fn integer(value: &Value, key: &str) -> Result<i64> {
    value.get(key).and_then(Value::as_i64).ok_or_else(invalid)
}
pub fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value.get(key).and_then(Value::as_str).ok_or_else(invalid)
}
fn array<'a>(value: &'a Value, key: &str) -> Result<&'a Vec<Value>> {
    value.get(key).and_then(Value::as_array).ok_or_else(invalid)
}
pub fn schema(value: &Value) -> Result<(i64, Vec<Field>)> {
    if text(value, "type")? != "struct" {
        return Err(invalid());
    }
    let id = integer(value, "schema-id")?;
    if id < 0 {
        return Err(invalid());
    }
    let raw = array(value, "fields")?;
    if raw.is_empty() || raw.len() > 64 {
        return Err(invalid());
    }
    let mut ids = HashSet::new();
    let mut names = HashSet::new();
    let mut fields = Vec::new();
    for field in raw {
        let id = i32::try_from(integer(field, "id")?).map_err(|_| invalid())?;
        let name = text(field, "name")?;
        let kind = text(field, "type")?;
        if id <= 0
            || !ids.insert(id)
            || !names.insert(name.to_string())
            || name.is_empty()
            || name.len() > 128
            || !name.is_ascii()
            || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
            || name.as_bytes()[0].is_ascii_digit()
            || !matches!(kind, "long" | "string" | "boolean")
        {
            return Err(invalid());
        }
        fields.push(Field {
            id,
            name: name.into(),
            kind: kind.into(),
            required: field
                .get("required")
                .and_then(Value::as_bool)
                .ok_or_else(invalid)?,
        });
    }
    Ok((id, fields))
}
pub fn parse(bytes: &[u8], selected: i64) -> Result<Metadata> {
    let value: Value = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if integer(&value, "format-version")? != 2 {
        return Err(invalid());
    }
    let uuid = text(&value, "table-uuid")?;
    if uuid.len() != 36
        || !uuid.bytes().enumerate().all(|(i, b)| {
            if [8, 13, 18, 23].contains(&i) {
                b == b'-'
            } else {
                b.is_ascii_hexdigit()
            }
        })
    {
        return Err(invalid());
    }
    let schemas = array(&value, "schemas")?;
    if schemas.len() != 1 {
        return Err(invalid());
    }
    let (schema_id, fields) = schema(&schemas[0])?;
    if integer(&value, "current-schema-id")? != schema_id {
        return Err(invalid());
    }
    let specs = array(&value, "partition-specs")?;
    if specs.len() != 1
        || integer(&specs[0], "spec-id")? != 0
        || !array(&specs[0], "fields")?.is_empty()
        || integer(&value, "default-spec-id")? != 0
    {
        return Err(invalid());
    }
    let orders = array(&value, "sort-orders")?;
    if orders.len() != 1
        || integer(&orders[0], "order-id")? != 0
        || !array(&orders[0], "fields")?.is_empty()
        || integer(&value, "default-sort-order-id")? != 0
    {
        return Err(invalid());
    }
    let snapshots = array(&value, "snapshots")?;
    if snapshots.is_empty() || snapshots.len() > 8 {
        return Err(invalid());
    }
    let mut ids = HashSet::new();
    let mut manifest_list = None;
    for snapshot in snapshots {
        let id = integer(snapshot, "snapshot-id")?;
        if id <= 0 || !ids.insert(id) || integer(snapshot, "schema-id")? != schema_id {
            return Err(invalid());
        }
        if id == selected {
            manifest_list = Some(text(snapshot, "manifest-list")?.to_string());
        }
    }
    let logical_root = path::logical_root(text(&value, "location")?)?;
    let manifest_list = path::relocate(&logical_root, &manifest_list.ok_or_else(invalid)?)?;
    Ok(Metadata {
        uuid: uuid.into(),
        schema_id,
        fields,
        logical_root,
        manifest_list,
        snapshot: selected,
    })
}
