//! One bounded typed-value parser and per-query AST binding state.
use crate::{Error, Result};
use datafusion::{
    common::ScalarValue,
    logical_expr::{lit, Expr},
};
use serde::{Deserialize, Deserializer};
use serde_json::Value;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    version: u8,
    values: Vec<Parameter>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Parameter {
    #[serde(rename = "type")]
    kind: String,
    #[serde(deserialize_with = "required_value")]
    value: Value,
}
fn required_value<'de, D: Deserializer<'de>>(d: D) -> std::result::Result<Value, D::Error> {
    Value::deserialize(d)
}
pub fn invalid() -> Error {
    Error::new("unsupported", "invalid SQL value parameters")
}
#[derive(Default)]
pub struct Bindings {
    values: Vec<(ScalarValue, String)>,
    used: u16,
}
impl Bindings {
    pub fn parse(raw: &str) -> Result<Self> {
        if raw.len() > 16384 {
            return Err(invalid());
        }
        let input: Input = serde_json::from_str(raw).map_err(|_| invalid())?;
        if input.version != 1 || input.values.len() > 16 {
            return Err(invalid());
        }
        let mut values = Vec::new();
        for parameter in input.values {
            let scalar = match (parameter.kind.as_str(), parameter.value) {
                ("int8", Value::Null) => ScalarValue::Int64(None),
                ("text", Value::Null) => ScalarValue::Utf8(None),
                ("bool", Value::Null) => ScalarValue::Boolean(None),
                ("int8", Value::String(s)) => {
                    let n = s.parse::<i64>().map_err(|_| invalid())?;
                    if n.to_string() != s {
                        return Err(invalid());
                    }
                    ScalarValue::Int64(Some(n))
                }
                ("text", Value::String(s)) => ScalarValue::Utf8(Some(s)),
                ("bool", Value::Bool(b)) => ScalarValue::Boolean(Some(b)),
                _ => return Err(invalid()),
            };
            values.push((scalar, parameter.kind));
        }
        Ok(Self { values, used: 0 })
    }
    pub fn resolve(&mut self, token: &str) -> Result<(ScalarValue, String)> {
        let digits = token.strip_prefix('$').ok_or_else(invalid)?;
        let n = digits.parse::<usize>().map_err(|_| invalid())?;
        if !(1..=16).contains(&n) || n.to_string() != digits {
            return Err(invalid());
        }
        let value = self.values.get(n - 1).ok_or_else(invalid)?.clone();
        self.used |= 1 << (n - 1);
        Ok(value)
    }
    pub fn expression(&mut self, token: &str) -> Result<(Expr, String)> {
        let (value, kind) = self.resolve(token)?;
        Ok((lit(value), kind))
    }
    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }
    pub fn finish(&self) -> Result<()> {
        let expected = ((1u32 << self.values.len()) - 1) as u16;
        if self.used != expected {
            return Err(invalid());
        }
        Ok(())
    }
}
pub fn suffix(args: &mut Vec<String>) -> Result<Bindings> {
    if args.len() >= 2 && args[args.len() - 2] == "--params-json" {
        let raw = args.pop().ok_or_else(invalid)?;
        args.pop();
        Bindings::parse(&raw)
    } else {
        Ok(Bindings::default())
    }
}
