//! SQL tests reuse only the private real TCP fixture, never a prepared result.
use super::*;
fn source(bytes: &[u8], port: u16) -> Value {
    let mut value = request(bytes, port, vec![0], vec![0]);
    value.as_object_mut().unwrap().remove("columns");
    value.as_object_mut().unwrap().remove("row_groups");
    value
}
fn command(input: &Input, sql: &str, parameters: Option<&str>) -> Command {
    let mut c = Command::new(env!("CARGO_BIN_EXE_guradb"));
    c.args([
        "parquet-query",
        "--source",
        input.root.join("request.json").to_str().unwrap(),
        "--sql",
        sql,
    ]);
    if let Some(parameters) = parameters {
        c.args(["--params-json", parameters]);
    }
    c.stdin(Stdio::null());
    c
}
fn run(input: &Input, sql: &str, parameters: Option<&str>) -> Value {
    let output = command(input, sql, parameters).output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(result.get("source_sha256").is_none());
    assert_eq!(result["verification"], "selected_ranges_only");
    assert_eq!(result["unread_content_verified"], false);
    result
}
#[test]
fn full_relation_uses_projection_filter_and_order_dependencies_with_typed_values() {
    let _window = super::super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    for version in [WriterVersion::PARQUET_1_0, WriterVersion::PARQUET_2_0] {
        let bytes = fixture(version, 6, false);
        let server = Server::new(bytes.clone(), Mode::Normal);
        let value = source(&bytes, server.port);
        let input = Input::new(&value);
        let result = run(
            &input,
            "SELECT number FROM records WHERE flag = $1 ORDER BY number",
            Some("{\"version\":1,\"values\":[{\"type\":\"bool\",\"value\":true}]}"),
        );
        assert_eq!(
            result["rows"],
            json!([[i64::MIN.to_string()], [i64::MIN.to_string()], ["0"]])
        );
        assert_eq!(result["source_rows"], 6);
        assert_eq!(result["decoded_rows"], 6);
        assert_eq!(result["row_groups"], json!([0, 1, 2]));
        assert_eq!(result["required_columns"], json!([0, 2]));
        assert_eq!(result["request_count"], 8);
        let mut expected = request(&bytes, server.port, vec![0, 2], vec![0, 1, 2]);
        expected["row_groups"] = json!([0, 1, 2]);
        assert_eq!(*server.ranges.lock().unwrap(), projected_ranges(&expected));
    }
}
#[test]
fn hidden_source_order_column_and_shadowing_alias_keep_original_shared_semantics() {
    let _window = super::super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let bytes = fixture(WriterVersion::PARQUET_1_0, 6, false);
    let server = Server::new(bytes.clone(), Mode::Normal);
    let value = source(&bytes, server.port);
    let input = Input::new(&value);
    let result = run(
        &input,
        "SELECT number AS text FROM records ORDER BY text DESC NULLS LAST",
        None,
    );
    assert_eq!(result["columns"], json!([{"name":"text","type":"int8"}]));
    assert_eq!(
        result["rows"],
        json!([
            [i64::MIN.to_string()],
            [i64::MIN.to_string()],
            ["0"],
            [null],
            [null],
            [i64::MAX.to_string()]
        ])
    );
    assert_eq!(result["required_columns"], json!([0, 1]));
    assert_eq!(result["request_count"], 8);
}
#[test]
fn nulls_empty_results_and_limit_zero_still_read_all_required_groups() {
    let _window = super::super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let bytes = fixture(WriterVersion::PARQUET_1_0, 6, false);
    for (sql,parameters,expected) in [
        ("SELECT number FROM records WHERE number IS NULL",None,json!([[null],[null]])),
        ("SELECT number FROM records WHERE number = $1",Some("{\"version\":1,\"values\":[{\"type\":\"int8\",\"value\":null}]}"),json!([])),
        ("SELECT number FROM records WHERE false",None,json!([])),
        ("SELECT number FROM records LIMIT 0",None,json!([])),
        ("SELECT number FROM records WHERE number >= $1 ORDER BY number DESC LIMIT 1",Some("{\"version\":1,\"values\":[{\"type\":\"int8\",\"value\":\"-9223372036854775808\"}]}"),json!([[i64::MAX.to_string()]])),
    ] {
        let server=Server::new(bytes.clone(),Mode::Normal);let input=Input::new(&source(&bytes,server.port));let result=run(&input,sql,parameters);
        assert_eq!(result["rows"],expected);assert_eq!(result["decoded_rows"],6);assert_eq!(result["required_columns"],json!([0]));assert_eq!(result["request_count"],5);assert_eq!(server.ranges.lock().unwrap().len(),5);
    }
}
#[test]
fn invalid_sql_and_oversized_physical_plan_never_fetch_partial_chunks() {
    let _window = super::super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let bytes = fixture(WriterVersion::PARQUET_1_0, 6, false);
    for (sql, code) in [
        ("SELECT * FROM records", "resource_limit"),
        (
            "SELECT number FROM records WHERE flag ORDER BY text LIMIT 0",
            "resource_limit",
        ),
        ("SELECT DISTINCT number FROM records", "unsupported"),
        ("SELECT COUNT(*) FROM records", "unsupported"),
        ("SELECT number FROM records GROUP BY number", "unsupported"),
        (
            "SELECT number AS renamed FROM records ORDER BY renamed",
            "unsupported",
        ),
    ] {
        let server = Server::new(bytes.clone(), Mode::Normal);
        let input = Input::new(&source(&bytes, server.port));
        rejected(command(&input, sql, None).output().unwrap(), code);
        assert_eq!(server.ranges.lock().unwrap().len(), 2);
    }
    // Source-visible global damage is rejected before WHERE false/LIMIT 0.
    let bytes = fixture(WriterVersion::PARQUET_1_0, 201, false);
    let server = Server::new(bytes.clone(), Mode::Normal);
    let input = Input::new(&source(&bytes, server.port));
    rejected(
        command(
            &input,
            "SELECT number FROM records WHERE false LIMIT 0",
            None,
        )
        .output()
        .unwrap(),
        "invalid_parquet_read",
    );
    assert_eq!(server.ranges.lock().unwrap().len(), 2);
}
#[test]
fn source_rejects_physical_selection_unknown_fields_links_and_bad_parameters() {
    let _window = super::super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let bytes = fixture(WriterVersion::PARQUET_1_0, 6, false);
    let server = Server::new(bytes.clone(), Mode::Normal);
    for field in ["columns", "row_groups", "other"] {
        let mut value = source(&bytes, server.port);
        value[field] = json!([0]);
        let input = Input::new(&value);
        rejected(
            command(&input, "SELECT number FROM records", None)
                .output()
                .unwrap(),
            "invalid_parquet_read",
        );
    }
    let input = Input::new(&source(&bytes, server.port));
    let raw = fs::read_to_string(input.root.join("request.json")).unwrap();
    fs::write(
        input.root.join("request.json"),
        format!("{{\"version\":1,{}", &raw[1..]),
    )
    .unwrap();
    rejected(
        command(&input, "SELECT number FROM records", None)
            .output()
            .unwrap(),
        "invalid_parquet_read",
    );
    assert!(server.ranges.lock().unwrap().is_empty());
    let input = Input::new(&source(&bytes, server.port));
    fs::rename(
        input.root.join("request.json"),
        input.root.join("actual.json"),
    )
    .unwrap();
    std::os::unix::fs::symlink(
        input.root.join("actual.json"),
        input.root.join("request.json"),
    )
    .unwrap();
    rejected(
        command(&input, "SELECT number FROM records", None)
            .output()
            .unwrap(),
        "invalid_parquet_read",
    );
    assert!(server.ranges.lock().unwrap().is_empty());
    let input = Input::new(&source(&bytes, server.port));
    rejected(
        command(
            &input,
            "SELECT number FROM records",
            Some("{\"version\":1,\"values\":[{\"type\":\"int8\",\"value\":\"01\"}]}"),
        )
        .output()
        .unwrap(),
        "unsupported",
    );
    assert!(server.ranges.lock().unwrap().is_empty());
}
#[test]
fn query_deadline_and_sigint_cover_the_same_multi_get_operation() {
    let _window = super::super::CLI_PROCESS_WINDOW
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let bytes = fixture(WriterVersion::PARQUET_1_0, 6, false);
    for interrupt in [false, true] {
        let server = Server::new(bytes.clone(), Mode::HoldThird);
        let mut input = Input::new(&source(&bytes, server.port));
        input.child = Some(
            command(&input, "SELECT number FROM records", None)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .unwrap(),
        );
        server.ready.recv_timeout(Duration::from_secs(3)).unwrap();
        let child = input.child.as_mut().unwrap();
        let pid = child.id();
        if interrupt {
            assert_eq!(unsafe { libc::kill(pid as i32, libc::SIGINT) }, 0);
        }
        let deadline = Instant::now() + Duration::from_secs(if interrupt { 3 } else { 12 });
        let status = loop {
            if let Some(s) = child.try_wait().unwrap() {
                break s;
            }
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        };
        assert_eq!(status.code(), Some(if interrupt { 130 } else { 124 }));
        let mut raw = Vec::new();
        child.stdout.take().unwrap().read_to_end(&mut raw).unwrap();
        assert!(raw.is_empty());
        let mut error = String::new();
        child
            .stderr
            .take()
            .unwrap()
            .read_to_string(&mut error)
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&error).unwrap()["code"],
            if interrupt { "cancelled" } else { "timeout" }
        );
        assert!(!std::path::Path::new(&format!("/proc/{pid}")).exists());
    }
    let server = Server::new(bytes.clone(), Mode::Normal);
    let input = Input::new(&source(&bytes, server.port));
    assert_eq!(
        run(&input, "SELECT number FROM records LIMIT 1", None)["rows"],
        json!([[i64::MIN.to_string()]])
    );
}
