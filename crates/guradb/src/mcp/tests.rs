use super::*;
fn server() -> Server {
    Server {
        store: "/explicit/store".into(),
        phase: 0,
        ids: HashSet::new(),
        messages: 0,
        total: 0,
        pending: None,
        worker: None,
    }
}
fn message(s: &mut Server, value: Value) -> Value {
    s.message(&serde_json::to_vec(&value).unwrap()).unwrap();
    serde_json::from_slice(&s.pending.take().unwrap().bytes).unwrap()
}
#[test]
fn lifecycle_negotiates_known_server_version_and_requires_initialized() {
    let mut s = server();
    let r = message(
        &mut s,
        json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"1"},"capabilities":{}}}),
    );
    assert_eq!(r["result"]["protocolVersion"], "2025-06-18");
    assert_eq!(
        message(
            &mut s,
            json!({"jsonrpc":"2.0","id":2,"method":"tools/list"})
        )["error"]["code"],
        -32600
    );
    s.message(br#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#)
        .unwrap();
    assert!(s.pending.is_none());
    assert_eq!(
        message(
            &mut s,
            json!({"jsonrpc":"2.0","id":3,"method":"tools/list"})
        )["result"]["tools"]
            .as_array()
            .unwrap()
            .len(),
        3
    );
    assert_eq!(
        message(
            &mut s,
            json!({"jsonrpc":"2.0","id":4,"method":"resources/list"})
        )["error"]["code"],
        -32601
    );
}
#[test]
fn malformed_initialize_ids_and_exact_tool_arguments_refuse() {
    let mut s = server();
    assert_eq!(
        message(
            &mut s,
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":true,"clientInfo":{},"capabilities":{}}})
        )["error"]["code"],
        -32602
    );
    assert_eq!(
        message(&mut s, json!({"jsonrpc":"2.0","id":true,"method":"ping"}))["error"]["code"],
        -32600
    );
    for v in [
        json!({"name":"guradb_media","arguments":{"view":"current","asset_id":1}}),
        json!({"name":"guradb_query","arguments":{"view":"current","sql":"SELECT x FROM records","path":"/etc/passwd"}}),
        json!({"name":"guradb_vector","arguments":{}}),
    ] {
        assert!(tools::command(&v, "/explicit/store").is_err());
    }
    let cmd = tools::command(
        &json!({"name":"guradb_search","arguments":{"view":"current","query":"kitchen"}}),
        "/explicit/store",
    )
    .unwrap();
    assert_eq!(
        cmd,
        vec![
            "view",
            "search",
            "--store",
            "/explicit/store",
            "--view",
            "current",
            "--query",
            "kitchen"
        ]
    );
}

#[test]
fn empty_string_is_a_valid_bounded_unique_request_id() {
    let mut s = server();
    s.phase = 2;
    let r = message(&mut s, json!({"jsonrpc":"2.0","id":"","method":"ping"}));
    assert_eq!(r["id"], "");
    assert!(r.get("result").is_some());
    assert_eq!(
        message(&mut s, json!({"jsonrpc":"2.0","id":"","method":"ping"}))["error"]["code"],
        -32600
    );
}

#[test]
fn query_parameter_json_is_optional_bounded_and_forwarded_without_sql_rewrite() {
    let raw = r#"{"version":1,"values":[{"type":"text","value":"a'; -- $1"}]}"#;
    let command = super::tools::command(&json!({"name":"guradb_query","arguments":{"view":"current","sql":"SELECT t FROM records WHERE t=$1","params_json":raw}}),"/store").unwrap();
    assert_eq!(
        &command[command.len() - 2..],
        &["--params-json".to_string(), raw.to_string()]
    );
    assert_eq!(command[7], "SELECT t FROM records WHERE t=$1");
    for value in [json!(null), json!(1), json!("x".repeat(16385))] {
        assert!(super::tools::command(&json!({"name":"guradb_query","arguments":{"view":"current","sql":"SELECT t FROM records","params_json":value}}),"/store").is_err());
    }
    assert!(super::tools::command(&json!({"name":"guradb_search","arguments":{"view":"current","query":"kitchen","params_json":raw}}),"/store").is_err());
    assert_eq!(super::tools::list()["tools"].as_array().unwrap().len(), 3);
}
