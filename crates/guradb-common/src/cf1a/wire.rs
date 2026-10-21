use super::{publication, read, Envelope, CAPABILITIES, VERSION};
use serde_json::Value;

#[derive(Debug, PartialEq)]
pub struct ContractFailure {
    pub code: &'static str,
    pub message: &'static str,
}
pub type Result<T> = std::result::Result<T, ContractFailure>;

pub(crate) fn require(condition: bool, message: &'static str) -> Result<()> {
    require_code(condition, message, "invalid_contract")
}
pub(crate) fn require_code(
    condition: bool,
    message: &'static str,
    code: &'static str,
) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(ContractFailure { code, message })
    }
}
pub fn canonical(value: &Value) -> Vec<u8> {
    // All object keys are fixed ASCII. serde_json's map sorts those keys.
    serde_json::to_vec(value).expect("JSON Value always serializes")
}
pub fn digest(value: &Value) -> String {
    crate::digest(&canonical(value))
}

#[derive(Clone, Debug)]
pub struct Contract {
    envelope: Envelope,
    document: Value,
    encoded: Vec<u8>,
}
impl Contract {
    pub fn envelope(&self) -> &Envelope {
        &self.envelope
    }
    pub fn document(&self) -> &Value {
        &self.document
    }
    pub fn encoded(&self) -> &[u8] {
        &self.encoded
    }
    pub fn sha256(&self) -> String {
        crate::digest(&self.encoded)
    }
    pub fn kind(&self) -> &str {
        self.document["payload"]
            .as_object()
            .unwrap()
            .keys()
            .next()
            .unwrap()
    }
    pub fn value(&self) -> &Value {
        &self.document["payload"][self.kind()]
    }
}

pub(super) fn shape(value: &Value, spec: &Value, root: &Value) -> Result<()> {
    if let Some(reference) = spec["$ref"].as_str() {
        return shape(value, root.pointer(&reference[1..]).unwrap(), root);
    }
    if let Some(options) = spec["oneOf"].as_array() {
        return require(
            options
                .iter()
                .filter(|item| shape(value, item, root).is_ok())
                .count()
                == 1,
            "invalid union value",
        );
    }
    if let Some(constant) = spec.get("const") {
        require(value == constant, "invalid constant")?;
    }
    if let Some(options) = spec["enum"].as_array() {
        require(options.contains(value), "unsupported enum")?;
    }
    match spec["type"].as_str() {
        Some("object") => {
            let fields = spec["properties"].as_object().unwrap();
            let object = value.as_object().ok_or(ContractFailure {
                code: "invalid_contract",
                message: "expected object",
            })?;
            require(
                object.len() == fields.len() && fields.keys().all(|key| object.contains_key(key)),
                "unknown or missing field",
            )?;
            for (key, field) in fields {
                shape(&object[key], field, root)?;
            }
        }
        Some("array") => {
            let items = value.as_array().ok_or(ContractFailure {
                code: "invalid_contract",
                message: "expected array",
            })?;
            require(
                items.len() >= spec["minItems"].as_u64().unwrap_or(0) as usize
                    && items.len() <= spec["maxItems"].as_u64().unwrap_or(u64::MAX) as usize,
                "invalid array length",
            )?;
            if spec["uniqueItems"] == true {
                require(
                    items
                        .iter()
                        .enumerate()
                        .all(|(n, item)| !items[..n].contains(item)),
                    "duplicate array value",
                )?;
            }
            for item in items {
                shape(item, &spec["items"], root)?;
            }
        }
        Some("string") => {
            let text = value.as_str().ok_or(ContractFailure {
                code: "invalid_contract",
                message: "expected string",
            })?;
            require(
                text.chars().count() >= spec["minLength"].as_u64().unwrap_or(0) as usize,
                "string too short",
            )?;
            require(
                text.chars().count() <= spec["maxLength"].as_u64().unwrap_or(u64::MAX) as usize,
                "string too long",
            )?;
            match spec["pattern"].as_str() {
                Some("^(?!latest$)[A-Za-z0-9_-]{1,128}$") => require(
                    !text.is_empty()
                        && text.len() <= 128
                        && text != "latest"
                        && text
                            .bytes()
                            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-'),
                    "invalid fixed ID",
                )?,
                Some("^[0-9a-f]{64}$") => require(
                    text.len() == 64
                        && text
                            .bytes()
                            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)),
                    "invalid SHA-256",
                )?,
                Some("^[0-9a-f]{16}$") => require(
                    text.len() == 16
                        && text
                            .bytes()
                            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
                        && u64::from_str_radix(text, 16)
                            .is_ok_and(|bits| f64::from_bits(bits).is_finite()),
                    "invalid finite binary64 score",
                )?,
                Some(pattern) if pattern.starts_with("^[^") => require(
                    !text.chars().any(|c| c <= ' ' || c == '\u{7f}'),
                    "invalid opaque reference",
                )?,
                Some(_) => {
                    let parsed = text.parse::<i64>();
                    require(
                        parsed.is_ok_and(|number| number.to_string() == text),
                        "invalid int8",
                    )?;
                }
                None => {}
            }
        }
        Some("integer") => require(
            value.as_u64().is_some_and(|number| {
                number >= spec["minimum"].as_u64().unwrap()
                    && number <= spec["maximum"].as_u64().unwrap()
            }),
            "invalid safe integer",
        )?,
        Some("boolean") => require(value.is_boolean(), "expected bool")?,
        Some("null") => require(value.is_null(), "invalid NULL")?,
        _ => {}
    }
    Ok(())
}

pub(super) fn decode_document(raw: &[u8]) -> Result<Contract> {
    require(raw.len() <= 1 << 20, "envelope too large")?;
    let original = super::json::strict_value(raw)?;
    check_depth(&original, 0)?;
    require(
        original.as_object().is_some_and(|object| {
            object.len() == 3
                && ["contract_version", "required_capabilities", "payload"]
                    .iter()
                    .all(|key| object.contains_key(*key))
        }),
        "invalid envelope fields",
    )?;
    require_code(
        original["contract_version"] == VERSION,
        "unsupported contract version",
        "unsupported_version",
    )?;
    let caps = original["required_capabilities"]
        .as_array()
        .ok_or(ContractFailure {
            code: "invalid_contract",
            message: "invalid capability set",
        })?;
    require(
        caps.iter().all(Value::is_string)
            && caps
                .iter()
                .enumerate()
                .all(|(n, item)| !caps[..n].contains(item)),
        "invalid capability set",
    )?;
    require_code(
        caps.iter()
            .all(|cap| CAPABILITIES.contains(&cap.as_str().unwrap())),
        "unknown required capability",
        "unsupported_capability",
    )?;
    let payload = original["payload"].as_object().ok_or(ContractFailure {
        code: "invalid_contract",
        message: "expected one payload",
    })?;
    require(payload.len() == 1, "expected one payload")?;
    let kind = payload.keys().next().unwrap();
    require(
        [
            "read_binding",
            "read_batch",
            "register_intent",
            "publish_intent",
            "mutation_receipt",
            "reader_config",
            "contract_error",
            "bind_request",
            "candidate_batch",
            "mutation_auth",
            "index_query",
            "read_descriptors",
        ]
        .contains(&kind.as_str()),
        "unsupported payload",
    )?;
    let mut baseline = vec!["fixed_read", "typed_json_v1", "strong_integrity"];
    if [
        "register_intent",
        "publish_intent",
        "mutation_receipt",
        "mutation_auth",
    ]
    .contains(&kind.as_str())
    {
        baseline.push("catalog_cas");
    }
    require_code(
        baseline
            .iter()
            .all(|cap| caps.iter().any(|item| item.as_str() == Some(*cap))),
        "missing required capability",
        "unsupported_capability",
    )?;
    // Typed structs reject unknown fields; comparison forbids serde supplying a
    // missing typed-null value or any other normalization of the original value.
    let envelope: Envelope =
        serde_json::from_value(original.clone()).map_err(|_| ContractFailure {
            code: "invalid_contract",
            message: "invalid JSON or fields",
        })?;
    let document = serde_json::to_value(&envelope).unwrap();
    require(document == original, "missing or normalized wire field")?;
    let schema: Value =
        serde_json::from_str(include_str!("../../../../api/cf1a/schema.json")).unwrap();
    shape(&document, &schema, &schema)?;
    let payload = &document["payload"][kind];
    read::validate_read(kind, payload)?;
    publication::validate_publication(kind, payload)?;
    let encoded = canonical(&document);
    Ok(Contract {
        envelope,
        document,
        encoded,
    })
}

pub(crate) fn validate_named(value: &Value, name: &str) -> Result<()> {
    let schema: Value =
        serde_json::from_str(include_str!("../../../../api/cf1a/schema.json")).unwrap();
    shape(value, &schema["$defs"][name], &schema)
}

pub(crate) fn safe_integer(number: u64, positive: bool) -> Result<()> {
    require(
        number < (1_u64 << 53) && (!positive || number > 0),
        "invalid safe integer",
    )
}

fn check_depth(value: &Value, depth: usize) -> Result<()> {
    require(depth <= 64, "JSON nesting limit exceeded")?;
    match value {
        Value::Object(fields) => {
            for item in fields.values() {
                check_depth(item, depth + 1)?;
            }
        }
        Value::Array(items) => {
            for item in items {
                check_depth(item, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}
