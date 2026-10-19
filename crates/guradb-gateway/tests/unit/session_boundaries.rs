use super::*;
use crate::gateway_tests::setup;
use pgwire::messages::{
    extendedquery::{Bind, Parse},
    simplequery::Query,
};
use tokio::net::TcpListener;

async fn sockets() -> (TcpStream, TcpStream) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let client = TcpStream::connect(listener.local_addr().unwrap())
        .await
        .unwrap();
    (client, listener.accept().await.unwrap().0)
}

#[tokio::test]
async fn retrieval_and_bind_recheck_dataset_grants() {
    let (_fixture, state, principal, _) = setup();
    let (_client, server) = sockets().await;
    let (_, mut writer) = server.into_split();
    let mut session = Session {
        state,
        principal,
        active: Active::default(),
        disconnected: CancellationToken::new(),
        statements: HashMap::new(),
        portals: HashMap::new(),
    };
    session
        .message(
            Front::Parse(Parse::new(
                Some("s".into()),
                "SELECT id FROM documents".into(),
                vec![],
            )),
            &mut writer,
        )
        .await
        .unwrap();
    let bind = |formats| {
        Front::Bind(Bind::new(
            Some("p".into()),
            Some("s".into()),
            vec![],
            vec![],
            formats,
        ))
    };
    assert_eq!(
        session
            .message(bind(vec![0, 0]), &mut writer)
            .await
            .unwrap_err()
            .code,
        "protocol_violation"
    );
    session.message(bind(vec![]), &mut writer).await.unwrap();
    let mut portal = session.portals.remove("p").unwrap();
    session
        .send_rows_inner(&mut portal, 0, &mut writer)
        .await
        .unwrap();
    let mut auth: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&session.state.auth_file).unwrap()).unwrap();
    auth["principals"][0]["datasets"] = serde_json::json!([]);
    std::fs::write(&session.state.auth_file, serde_json::to_vec(&auth).unwrap()).unwrap();
    assert_eq!(
        session
            .message(bind(vec![]), &mut writer)
            .await
            .unwrap_err()
            .code,
        "not_found"
    );
    assert_eq!(
        session.execute(&mut portal).await.unwrap_err().code,
        "not_found"
    );
    assert_eq!(
        session
            .send_rows_inner(&mut portal, 0, &mut writer)
            .await
            .unwrap_err()
            .code,
        "not_found"
    );
}

#[tokio::test]
async fn pipelined_queue_overflow_terminates_a_blocked_session() {
    let (_fixture, state, principal, _) = setup();
    let _held = state.slots.acquire_many(2).await.unwrap();
    let (mut client, server) = sockets().await;
    let mut bytes = bytes::BytesMut::new();
    use pgwire::messages::Message;
    for _ in 0..20 {
        Query::new("SELECT id FROM documents".into())
            .encode(&mut bytes)
            .unwrap();
    }
    use tokio::io::AsyncWriteExt;
    client.write_all(&bytes).await.unwrap();
    // All frames are available before the reader starts. Overflow cancels the
    // blocked executor; bounded termination is the observable assertion.
    tokio::time::timeout(
        Duration::from_secs(2),
        run(server, state.clone(), principal, Active::default()),
    )
    .await
    .unwrap()
    .unwrap();
}
