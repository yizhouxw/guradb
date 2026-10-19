use bytes::{BufMut, BytesMut};
use guradb_common::{protocol::Column, Error, Result};
use pgwire::messages::data::{DataRow, FieldDescription, RowDescription};
use serde_json::{json, Value};

pub fn kind(oid: u32) -> Result<Option<String>> {
    Ok(match oid {
        0 => None,
        20 | 21 | 23 => Some("int8".into()),
        25 | 1043 => Some("text".into()),
        16 => Some("bool".into()),
        _ => {
            return Err(Error::new(
                "unsupported",
                "unsupported PostgreSQL parameter type",
            ))
        }
    })
}
pub fn oid(kind: &str) -> u32 {
    match kind {
        "int8" => 20,
        "bool" => 16,
        _ => 25,
    }
}
pub fn formats(values: &[i16], count: usize) -> Result<Vec<i16>> {
    match values.len() {
        0 => Ok(vec![0; count]),
        1 => Ok(vec![values[0]; count]),
        n if n == count => Ok(values.to_vec()),
        _ => Err(super::wire::protocol()),
    }
}
pub fn parameter(raw: Option<&[u8]>, oid: u32, binary: bool) -> Result<Value> {
    let Some(raw) = raw else {
        return Ok(Value::Null);
    };
    let invalid = || Error::new("invalid_parameter", "invalid PostgreSQL parameter value");
    if matches!(oid, 20 | 21 | 23) {
        let number = if binary {
            match oid {
                20 => i64::from_be_bytes(raw.try_into().map_err(|_| invalid())?),
                21 => i16::from_be_bytes(raw.try_into().map_err(|_| invalid())?) as i64,
                23 => i32::from_be_bytes(raw.try_into().map_err(|_| invalid())?) as i64,
                _ => return Err(invalid()),
            }
        } else {
            let n = std::str::from_utf8(raw)
                .map_err(|_| invalid())?
                .trim()
                .parse::<i64>()
                .map_err(|_| invalid())?;
            if (oid == 21 && i16::try_from(n).is_err()) || (oid == 23 && i32::try_from(n).is_err())
            {
                return Err(invalid());
            }
            n
        };
        return Ok(json!({"type":"int8", "value":number.to_string()}));
    }
    if oid == 16 {
        let value = if binary {
            match raw {
                [0] => false,
                [1] => true,
                _ => return Err(invalid()),
            }
        } else {
            match std::str::from_utf8(raw)
                .map_err(|_| invalid())?
                .to_ascii_lowercase()
                .as_str()
            {
                "true" | "t" | "1" => true,
                "false" | "f" | "0" => false,
                _ => return Err(invalid()),
            }
        };
        return Ok(Value::Bool(value));
    }
    let value = std::str::from_utf8(raw).map_err(|_| invalid())?;
    if value.contains('\0') {
        return Err(invalid());
    }
    Ok(Value::String(value.into()))
}
pub fn description(columns: &[Column], formats: &[i16]) -> RowDescription {
    RowDescription::new(
        columns
            .iter()
            .zip(formats)
            .map(|(column, format)| {
                let size = match column.r#type.as_str() {
                    "int8" => 8,
                    "bool" => 1,
                    _ => -1,
                };
                FieldDescription::new(
                    column.name.clone(),
                    0,
                    0,
                    oid(&column.r#type),
                    size,
                    -1,
                    *format,
                )
            })
            .collect(),
    )
}
pub fn row(columns: &[Column], values: &[Value], formats: &[i16]) -> Result<DataRow> {
    let mut data = BytesMut::new();
    let invalid = || {
        Error::new(
            "execution_failed",
            "invalid result value for PostgreSQL type",
        )
    };
    for ((column, value), format) in columns.iter().zip(values).zip(formats) {
        if value.is_null() {
            data.put_i32(-1);
            continue;
        }
        let encoded: Vec<u8> = match column.r#type.as_str() {
            "int8" if *format == 1 => value
                .as_str()
                .ok_or_else(invalid)?
                .parse::<i64>()
                .map_err(|_| invalid())?
                .to_be_bytes()
                .to_vec(),
            "bool" => {
                let boolean = value.as_bool().ok_or_else(invalid)?;
                vec![if *format == 1 {
                    u8::from(boolean)
                } else if boolean {
                    b't'
                } else {
                    b'f'
                }]
            }
            _ => {
                let text = value.as_str().ok_or_else(invalid)?;
                if text.contains('\0') {
                    return Err(invalid());
                }
                text.as_bytes().to_vec()
            }
        };
        data.put_i32(encoded.len() as i32);
        data.extend_from_slice(&encoded);
    }
    Ok(DataRow::new(data, columns.len() as i16))
}

#[cfg(test)]
#[path = "../../tests/unit/pg_types_existing.rs"]
mod tests;
