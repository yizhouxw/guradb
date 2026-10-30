use serde_json::{json, Value};
pub fn list() -> Value {
    json!({"tools":[
        {"name":"guradb_query","description":"Read a fixed local view with the existing restricted Rust SQL","inputSchema":{"type":"object","properties":{"view":{"type":"string"},"sql":{"type":"string","maxLength":4096},"params_json":{"type":"string","maxLength":16384,"description":"Optional typed value v1 JSON; raw UTF8 at most 16384 bytes"}},"required":["view","sql"],"additionalProperties":false},"annotations":{"readOnlyHint":true,"destructiveHint":false,"openWorldHint":false}},
        {"name":"guradb_search","description":"Existing Rust BM25; use returned concrete view_id for evidence","inputSchema":{"type":"object","properties":{"view":{"type":"string"},"query":{"type":"string","maxLength":256}},"required":["view","query"],"additionalProperties":false},"annotations":{"readOnlyHint":true,"destructiveHint":false,"openWorldHint":false}},
        {"name":"guradb_media","description":"Exact JPEG bytes_hex from a concrete fixed view; current is refused","inputSchema":{"type":"object","properties":{"view":{"type":"string"},"asset_id":{"type":"integer","minimum":1,"maximum":999999999999i64}},"required":["view","asset_id"],"additionalProperties":false},"annotations":{"readOnlyHint":true,"destructiveHint":false,"openWorldHint":false}}
    ]})
}
fn digest(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub fn command(params: &Value, store: &str) -> Result<Vec<String>, &'static str> {
    let p = params.as_object().ok_or("tool params must be an object")?;
    if p.keys()
        .any(|k| !matches!(k.as_str(), "name" | "arguments"))
    {
        return Err("unsupported tool parameters");
    }
    let name = p
        .get("name")
        .and_then(Value::as_str)
        .ok_or("tool name required")?;
    let a = p
        .get("arguments")
        .and_then(Value::as_object)
        .ok_or("arguments object required")?;
    let (op, field, flag) = match name {
        "guradb_query" => ("query", "sql", "--sql"),
        "guradb_search" => ("search", "query", "--query"),
        "guradb_media" => ("media", "asset_id", "--asset-id"),
        _ => return Err("unsupported tool; only query/search/media are available"),
    };
    if a.keys()
        .any(|key| key != "view" && key != field && !(op == "query" && key == "params_json"))
        || !a.contains_key("view")
        || !a.contains_key(field)
    {
        return Err("exact tool argument fields required");
    }
    let view = a["view"].as_str().ok_or("view string required")?;
    if !digest(view) && (view != "current" || op == "media") {
        return Err("media requires a concrete fixed view; other tools accept current or ID");
    }
    let value = if op == "media" {
        a[field]
            .as_u64()
            .filter(|n| (1..=999_999_999_999).contains(n))
            .ok_or("positive bounded asset ID required")?
            .to_string()
    } else {
        let s = a[field].as_str().ok_or("query string required")?;
        if s.is_empty() || s.len() > if op == "query" { 4096 } else { 256 } {
            return Err("query string exceeds bound or is empty");
        }
        s.to_owned()
    };
    let mut args: Vec<String> = ["view", op, "--store", store, "--view", view, flag, &value]
        .iter()
        .map(|s| s.to_string())
        .collect();
    if let Some(raw) = a.get("params_json") {
        let raw = raw
            .as_str()
            .filter(|s| s.len() <= 16384)
            .ok_or("params_json must be a bounded UTF8 string")?;
        args.extend(["--params-json".into(), raw.to_string()]);
    }
    Ok(args)
}
