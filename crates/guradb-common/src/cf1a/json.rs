//! Preserve duplicate-field rejection before capability/version negotiation.
use super::wire::{ContractFailure, Result};
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
use std::fmt;

pub(super) struct Strict(Value);
impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        deserializer.deserialize_any(StrictVisitor)
    }
}
struct StrictVisitor;
impl<'de> Visitor<'de> for StrictVisitor {
    type Value = Strict;
    fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
        formatter.write_str("strict JSON value")
    }
    fn visit_bool<E: de::Error>(self, value: bool) -> std::result::Result<Strict, E> {
        Ok(Strict(Value::Bool(value)))
    }
    fn visit_i64<E: de::Error>(self, value: i64) -> std::result::Result<Strict, E> {
        Ok(Strict(Value::Number(Number::from(value))))
    }
    fn visit_u64<E: de::Error>(self, value: u64) -> std::result::Result<Strict, E> {
        Ok(Strict(Value::Number(Number::from(value))))
    }
    fn visit_f64<E: de::Error>(self, value: f64) -> std::result::Result<Strict, E> {
        if value == 0.0 && value.is_sign_negative() {
            return Err(E::custom("negative zero JSON integer"));
        }
        Number::from_f64(value)
            .map(|number| Strict(Value::Number(number)))
            .ok_or_else(|| E::custom("nonfinite JSON"))
    }
    fn visit_str<E: de::Error>(self, value: &str) -> std::result::Result<Strict, E> {
        Ok(Strict(Value::String(value.into())))
    }
    fn visit_unit<E: de::Error>(self) -> std::result::Result<Strict, E> {
        Ok(Strict(Value::Null))
    }
    fn visit_seq<A: SeqAccess<'de>>(
        self,
        mut sequence: A,
    ) -> std::result::Result<Strict, A::Error> {
        let mut values = Vec::new();
        while let Some(Strict(value)) = sequence.next_element()? {
            values.push(value);
        }
        Ok(Strict(Value::Array(values)))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> std::result::Result<Strict, A::Error> {
        let mut values = Map::new();
        while let Some((key, Strict(value))) = map.next_entry::<String, Strict>()? {
            if values.insert(key, value).is_some() {
                return Err(de::Error::custom("duplicate JSON field"));
            }
        }
        Ok(Strict(Value::Object(values)))
    }
}
pub(super) fn strict_value(raw: &[u8]) -> Result<Value> {
    serde_json::from_slice::<Strict>(raw)
        .map(|value| value.0)
        .map_err(|_| ContractFailure {
            code: "invalid_contract",
            message: "invalid or duplicate JSON",
        })
}
