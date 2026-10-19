use super::*;
use crate::gateway_tests::{request, setup};
use bytes::Bytes;
use pgwire::messages::{
    extendedquery::{Bind, Close, Describe, Execute, Flush, Parse, Sync},
    simplequery::Query,
    terminate::Terminate,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

async fn sockets() -> (TcpStream, TcpStream) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let client = TcpStream::connect(listener.local_addr().unwrap())
        .await
        .unwrap();
    let (server, _) = listener.accept().await.unwrap();
    (client, server)
}
fn session(state: Arc<State>, principal: Principal) -> Session {
    Session {
        state,
        principal,
        active: Active::default(),
        disconnected: CancellationToken::new(),
        statements: HashMap::new(),
        portals: HashMap::new(),
    }
}
fn parse(name: &str, sql: &str) -> Front {
    Front::Parse(Parse::new(Some(name.into()), sql.into(), vec![]))
}
fn bind(portal: &str, statement: &str, value: Option<Bytes>) -> Front {
    Front::Bind(Bind::new(
        Some(portal.into()),
        Some(statement.into()),
        vec![],
        vec![value],
        vec![1],
    ))
}
fn execute(name: &str, limit: i32) -> Front {
    Front::Execute(Execute::new(Some(name.into()), limit))
}

#[tokio::test]
async fn statement_portal_lifecycle_and_parameter_validation() {
    let (_fixture, state, principal, _) = setup();
    let (_client, socket) = sockets().await;
    let (_, mut writer) = socket.into_split();
    let mut s = session(state, principal);
    s.message(Front::Query(Query::new(" ".into())), &mut writer)
        .await
        .unwrap();
    s.message(
        Front::Query(Query::new("SELECT * FROM documents ORDER BY id".into())),
        &mut writer,
    )
    .await
    .unwrap();
    assert!(s
        .message(
            Front::Query(Query::new("SELECT id FROM documents WHERE id = $1".into())),
            &mut writer
        )
        .await
        .is_err());
    s.message(
        parse(
            "stmt",
            "SELECT id, title, active FROM documents WHERE id >= $1 ORDER BY id",
        ),
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(
        s.message(parse("stmt", "SELECT id FROM documents"), &mut writer)
            .await
            .unwrap_err()
            .code,
        "statement_exists"
    );
    s.message(
        Front::Describe(Describe::new(b'S', Some("stmt".into()))),
        &mut writer,
    )
    .await
    .unwrap();
    s.message(
        bind("portal", "stmt", Some(Bytes::from_static(b"1"))),
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(
        s.message(
            bind("portal", "stmt", Some(Bytes::from_static(b"1"))),
            &mut writer
        )
        .await
        .unwrap_err()
        .code,
        "portal_exists"
    );
    s.message(
        Front::Describe(Describe::new(b'P', Some("portal".into()))),
        &mut writer,
    )
    .await
    .unwrap();
    s.message(execute("portal", 1), &mut writer).await.unwrap();
    assert_eq!(s.portals["portal"].offset, 1);
    assert!(s.portals["portal"].output.is_some());
    s.message(execute("portal", 0), &mut writer).await.unwrap();
    assert!(s.portals["portal"].finished);
    s.message(execute("portal", 0), &mut writer).await.unwrap();
    s.message(
        Front::Close(Close::new(b'P', Some("portal".into()))),
        &mut writer,
    )
    .await
    .unwrap();
    s.message(
        Front::Close(Close::new(b'S', Some("stmt".into()))),
        &mut writer,
    )
    .await
    .unwrap();
    assert!(s.statements.is_empty());
    for message in [
        bind("", "missing", None),
        Front::Describe(Describe::new(b'S', Some("missing".into()))),
        Front::Describe(Describe::new(b'P', Some("missing".into()))),
        execute("missing", 0),
    ] {
        assert!(s.message(message, &mut writer).await.is_err());
    }
    s.message(
        parse("", "SELECT id FROM documents WHERE id = $1"),
        &mut writer,
    )
    .await
    .unwrap();
    s.message(bind("", "", Some(Bytes::from_static(b"2"))), &mut writer)
        .await
        .unwrap();
    s.message(parse("", "SELECT id FROM documents"), &mut writer)
        .await
        .unwrap();
    assert!(s.portals.is_empty());
    let bad = Front::Bind(Bind::new(None, None, vec![], vec![None], vec![]));
    assert_eq!(
        s.message(bad, &mut writer).await.unwrap_err().code,
        "invalid_parameter"
    );
    s.message(Front::Flush(Flush::new()), &mut writer)
        .await
        .unwrap();
    assert!(s
        .message(Front::Sync(Sync::new()), &mut writer)
        .await
        .is_err());
}

#[tokio::test]
async fn suspended_results_capacity_expiration_and_cancellation() {
    let (_fixture, state, principal, _) = setup();
    let (_client, socket) = sockets().await;
    let (_, mut writer) = socket.into_split();
    let mut s = session(state, principal);
    s.message(
        parse("s", "SELECT * FROM documents WHERE id >= $1"),
        &mut writer,
    )
    .await
    .unwrap();
    for i in 0..16 {
        s.message(
            bind(&format!("p{i}"), "s", Some(Bytes::from_static(b"1"))),
            &mut writer,
        )
        .await
        .unwrap();
    }
    assert_eq!(
        s.message(bind("overflow", "s", None), &mut writer)
            .await
            .unwrap_err()
            .code,
        "resource_limit"
    );
    s.message(execute("p0", 1), &mut writer).await.unwrap();
    assert_eq!(
        s.message(execute("p1", 1), &mut writer)
            .await
            .unwrap_err()
            .code,
        "resource_limit"
    );
    s.portals.get_mut("p2").unwrap().created = Instant::now() - Duration::from_secs(61);
    assert_eq!(
        s.message(execute("p2", 1), &mut writer)
            .await
            .unwrap_err()
            .code,
        "portal_missing"
    );
    for i in 1..32 {
        s.message(
            parse(&format!("s{i}"), "SELECT id FROM documents"),
            &mut writer,
        )
        .await
        .unwrap();
    }
    assert_eq!(
        s.message(parse("overflow", "SELECT id FROM documents"), &mut writer)
            .await
            .unwrap_err()
            .code,
        "resource_limit"
    );
    let mut portal = s.portals.remove("p0").unwrap();
    s.disconnected.cancel();
    assert_eq!(
        s.send_rows(&mut portal, 0, &mut writer)
            .await
            .unwrap_err()
            .code,
        "connection_closed"
    );
    assert_eq!(s.execute(&mut portal).await.unwrap_err().code, "cancelled");
}

#[tokio::test]
async fn session_loop_sync_error_recovery_and_disconnect() {
    let (_fixture, state, principal, _) = setup();
    let (mut client, server) = sockets().await;
    let active = Active::default();
    let running = tokio::spawn(run(server, state, principal, active));
    wire::send(
        &mut client,
        Parse::new(Some("s".into()), "BEGIN".into(), vec![]),
    )
    .await
    .unwrap();
    wire::send(
        &mut client,
        Parse::new(
            Some("ignored".into()),
            "SELECT id FROM documents".into(),
            vec![],
        ),
    )
    .await
    .unwrap();
    wire::send(&mut client, Sync::new()).await.unwrap();
    wire::send(
        &mut client,
        Query::new("SELECT id FROM documents WHERE id = 1".into()),
    )
    .await
    .unwrap();
    // Consume through ReadyForQuery twice rather than relying on a timing guess.
    let mut ready = 0;
    while ready < 2 {
        let tag = client.read_u8().await.unwrap();
        let length = client.read_u32().await.unwrap();
        let mut data = vec![0; length as usize - 4];
        client.read_exact(&mut data).await.unwrap();
        if tag == b'Z' {
            ready += 1;
        }
    }
    wire::send(&mut client, Terminate::new()).await.unwrap();
    drop(client);
    running.await.unwrap().unwrap();
    let (mut client, server) = sockets().await;
    let (_fixture, state, principal, _) = setup();
    let running = tokio::spawn(run(server, state, principal, Active::default()));
    client.write_all(b"Q\0\0\0\x03").await.unwrap();
    drop(client);
    running.await.unwrap().unwrap();
}

#[tokio::test]
async fn bind_values_capacity_and_delivery_cancellation_errors() {
    let (_fixture, state, principal, _) = setup();
    let (_client, socket) = sockets().await;
    let (_, mut writer) = socket.into_split();
    let mut s = session(state, principal);
    s.message(
        parse("s", "SELECT id FROM documents WHERE id=$1"),
        &mut writer,
    )
    .await
    .unwrap();
    assert!(s
        .message(
            bind("p", "s", Some(Bytes::from_static(b"not-int"))),
            &mut writer
        )
        .await
        .is_err());
    s.message(bind("p", "s", Some(Bytes::from_static(b"1"))), &mut writer)
        .await
        .unwrap();
    let mut portal = s.portals.remove("p").unwrap();
    let held = s.state.slots.acquire_many(2).await.unwrap();
    let cancel = async {
        loop {
            let token = s.active.lock().unwrap().clone();
            if let Some(token) = token {
                token.cancel();
                break;
            }
            tokio::task::yield_now().await;
        }
    };
    let (result, _) = tokio::join!(s.execute(&mut portal), cancel);
    drop(held);
    assert_eq!(result.unwrap_err().code, "cancelled");
    assert_eq!(
        s.send_rows(&mut portal, 0, &mut writer)
            .await
            .unwrap_err()
            .code,
        "connection_closed"
    );
    assert_eq!(
        s.send_rows_inner(&mut portal, 0, &mut writer)
            .await
            .unwrap_err()
            .code,
        "cancelled"
    );
    let (_fixture, state, principal, _) = setup();
    let mut s = session(state, principal);
    s.message(
        parse("s", "SELECT id FROM documents WHERE id=$1"),
        &mut writer,
    )
    .await
    .unwrap();
    let bad = Front::Bind(Bind::new(
        Some("p".into()),
        Some("s".into()),
        vec![0],
        vec![Some(Bytes::from_static(b"x"))],
        vec![],
    ));
    assert!(s.message(bad, &mut writer).await.is_err());
    s.state.slots.close();
    let statement = Arc::new(Statement {
        sql: "SELECT id FROM documents".into(),
        description: s.describe("SELECT id FROM documents", &[]).await.unwrap(),
        oids: vec![],
    });
    let mut portal = Portal {
        statement,
        parameters: vec![],
        formats: vec![0],
        output: None,
        offset: 0,
        finished: false,
        created: Instant::now(),
    };
    assert_eq!(
        s.execute(&mut portal).await.unwrap_err().code,
        "execution_failed"
    );
}

#[tokio::test]
async fn pg_truncation_and_binary_wire_byte_budgets_fail_closed() {
    use arrow::{
        array::{ArrayRef, BooleanArray, Int64Array, StringArray},
        record_batch::RecordBatch,
    };
    use guradb_common::{digest, manifest::ManifestRef};
    use parquet::arrow::ArrowWriter;
    use serde_json::json;
    let (fixture, mut state, principal, _) = setup();
    let original = std::fs::read(fixture.root.join("manifest.json")).unwrap();
    let mut manifest: serde_json::Value = serde_json::from_slice(&original).unwrap();
    let schema = guradb_query::sql::prepare(
        &request("SELECT * FROM documents"),
        &state.catalog,
        &principal.datasets,
    )
    .unwrap()
    .dataset
    .manifest
    .clone();
    let schema = Arc::new(arrow::datatypes::Schema::new(
        schema
            .schema
            .iter()
            .map(|f| {
                arrow::datatypes::Field::new(
                    &f.name,
                    match f.data_type.as_str() {
                        "int8" => arrow::datatypes::DataType::Int64,
                        "bool" => arrow::datatypes::DataType::Boolean,
                        _ => arrow::datatypes::DataType::Utf8,
                    },
                    f.nullable,
                )
            })
            .collect::<Vec<_>>(),
    ));
    let arrays: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from(vec![1; 500])),
        Arc::new(StringArray::from(vec!["a"; 500])),
        Arc::new(BooleanArray::from(vec![true; 500])),
    ];
    let batch = RecordBatch::try_new(schema.clone(), arrays).unwrap();
    let mut raw = Vec::new();
    let mut writer = ArrowWriter::try_new(&mut raw, schema, None).unwrap();
    writer.write(&batch).unwrap();
    writer.close().unwrap();
    std::fs::write(fixture.root.join("data.parquet"), &raw).unwrap();
    manifest["files"][0]["size_bytes"] = json!(raw.len());
    manifest["files"][0]["sha256"] = json!(digest(&raw));
    let bytes = serde_json::to_vec(&manifest).unwrap();
    std::fs::write(fixture.root.join("manifest.json"), &bytes).unwrap();
    Arc::get_mut(&mut state).unwrap().catalog = guradb_catalog::load(&[ManifestRef {
        path: fixture.root.join("manifest.json").to_str().unwrap().into(),
        sha256: digest(&bytes),
    }])
    .unwrap();
    Arc::get_mut(&mut state).unwrap().limits.result_bytes = 14000;
    let s = session(state, principal);
    let statement = Arc::new(Statement {
        sql: "SELECT * FROM documents".into(),
        description: s.describe("SELECT * FROM documents", &[]).await.unwrap(),
        oids: vec![],
    });
    let mut portal = Portal {
        statement,
        parameters: vec![],
        formats: vec![1, 1, 1],
        output: None,
        offset: 0,
        finished: false,
        created: Instant::now(),
    };
    assert_eq!(
        s.execute(&mut portal).await.unwrap_err().message,
        "PG result exceeds byte budget"
    );
    let (_fixture, mut state, principal, _) = setup();
    Arc::get_mut(&mut state).unwrap().limits.max_rows = 1;
    let s = session(state, principal);
    let statement = Arc::new(Statement {
        sql: "SELECT * FROM documents".into(),
        description: s.describe("SELECT * FROM documents", &[]).await.unwrap(),
        oids: vec![],
    });
    let mut portal = Portal {
        statement,
        parameters: vec![],
        formats: vec![0, 0, 0],
        output: None,
        offset: 0,
        finished: false,
        created: Instant::now(),
    };
    assert!(s
        .execute(&mut portal)
        .await
        .unwrap_err()
        .message
        .contains("result exceeds max_rows"));
}
