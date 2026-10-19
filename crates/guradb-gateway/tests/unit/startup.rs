use super::*;
use crate::gateway_tests::setup;
use pgwire::messages::{
    simplequery::Query,
    startup::{Password, Startup},
    terminate::Terminate,
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

async fn sockets() -> (TcpStream, TcpStream) {
    let listener = bind("127.0.0.1:0").await.unwrap();
    let client = TcpStream::connect(listener.local_addr().unwrap())
        .await
        .unwrap();
    let (server, _) = listener.accept().await.unwrap();
    (client, server)
}
fn packet(
    database: Option<&str>,
    user: Option<&str>,
    extra: Option<(&str, &str)>,
    minor: u16,
) -> Startup {
    let mut message = Startup::new();
    message.protocol_number_minor = minor;
    if let Some(db) = database {
        message.parameters.insert("database".into(), db.into());
    }
    if let Some(user) = user {
        message.parameters.insert("user".into(), user.into());
    }
    if let Some((key, value)) = extra {
        message.parameters.insert(key.into(), value.into());
    }
    message
}

#[tokio::test]
async fn startup_negotiation_authentication_and_explicit_rejections() {
    let (_fixture, state, principal, _) = setup();
    assert!(bind("0.0.0.0:0").await.is_err());
    assert!(bind("invalid").await.is_err());
    let listener = bind("127.0.0.1:0").await.unwrap();
    assert!(bind(&listener.local_addr().unwrap().to_string())
        .await
        .is_err());
    for (database, user, extra, password, minor, code) in [
        (
            Some("guradb"),
            Some("reader"),
            Some(("client_encoding", "UTF-8")),
            "secret",
            2,
            "ok",
        ),
        (
            Some("guradb"),
            Some("reader"),
            Some(("options", "")),
            "secret",
            0,
            "ok",
        ),
        (
            Some("guradb"),
            Some("reader"),
            Some(("application_name", "unit")),
            "secret",
            0,
            "ok",
        ),
        (
            Some("other"),
            Some("reader"),
            None,
            "secret",
            0,
            "database_unknown",
        ),
        (Some("guradb"), None, None, "secret", 0, "unauthorized"),
        (Some("guradb"), Some("reader"), None, "", 0, "unauthorized"),
        (
            Some("guradb"),
            Some("reader"),
            None,
            "wrong",
            0,
            "unauthorized",
        ),
        (
            Some("guradb"),
            Some("reader"),
            Some(("options", "bad")),
            "secret",
            0,
            "unsupported",
        ),
    ] {
        let (mut client, mut server) = sockets().await;
        wire::send(&mut client, packet(database, user, extra, minor))
            .await
            .unwrap();
        wire::send(&mut client, Password::new(password.into()))
            .await
            .unwrap();
        let result = startup(
            &mut server,
            &state,
            &Arc::new(Semaphore::new(1)),
            &Cancellations::default(),
        )
        .await;
        if code == "ok" {
            assert_eq!(
                result.unwrap().unwrap().0.principal_id,
                principal.principal_id
            );
        } else {
            assert_eq!(result.err().unwrap().code, code);
        }
    }
    let (mut client, mut server) = sockets().await;
    wire::send(&mut client, packet(Some("guradb"), Some("reader"), None, 0))
        .await
        .unwrap();
    assert_eq!(
        startup(
            &mut server,
            &state,
            &Arc::new(Semaphore::new(0)),
            &Cancellations::default()
        )
        .await
        .err()
        .unwrap()
        .code,
        "connection_limit"
    );
    let (mut client, mut server) = sockets().await;
    client
        .write_all(&[0, 0, 0, 8, 4, 210, 22, 47].repeat(3))
        .await
        .unwrap();
    assert_eq!(
        startup(
            &mut server,
            &state,
            &Arc::new(Semaphore::new(1)),
            &Cancellations::default()
        )
        .await
        .err()
        .unwrap()
        .code,
        "protocol_violation"
    );
    let (mut client, mut server) = sockets().await;
    client
        .write_all(&[0, 0, 0, 8, 4, 210, 22, 47])
        .await
        .unwrap();
    wire::send(&mut client, packet(Some("guradb"), Some("reader"), None, 0))
        .await
        .unwrap();
    wire::send(&mut client, Query::new("wrong packet".into()))
        .await
        .unwrap();
    assert_eq!(
        startup(
            &mut server,
            &state,
            &Arc::new(Semaphore::new(1)),
            &Cancellations::default()
        )
        .await
        .err()
        .unwrap()
        .code,
        "protocol_violation"
    );
    // A cancellation request uses a separate connection and secret tuple.
    let token = CancellationToken::new();
    let cancellations = Cancellations::default();
    cancellations
        .lock()
        .unwrap()
        .insert((12, 34), Arc::new(Mutex::new(Some(token.clone()))));
    let (mut client, mut server) = sockets().await;
    let raw = [16_i32, 80877102, 12, 34]
        .into_iter()
        .flat_map(i32::to_be_bytes)
        .collect::<Vec<_>>();
    client.write_all(&raw).await.unwrap();
    assert!(startup(
        &mut server,
        &state,
        &Arc::new(Semaphore::new(1)),
        &cancellations
    )
    .await
    .unwrap()
    .is_none());
    assert!(token.is_cancelled());
    for (pid, secret) in [(12, 35), (13, 34), (14, 34)] {
        cancellations
            .lock()
            .unwrap()
            .insert((14, 34), Active::default());
        let (mut client, mut server) = sockets().await;
        let raw = [16_i32, 80877102, pid, secret]
            .into_iter()
            .flat_map(i32::to_be_bytes)
            .collect::<Vec<_>>();
        client.write_all(&raw).await.unwrap();
        assert!(startup(
            &mut server,
            &state,
            &Arc::new(Semaphore::new(1)),
            &cancellations
        )
        .await
        .unwrap()
        .is_none());
    }
}

#[tokio::test]
async fn accept_loop_assigns_backend_key_and_runs_session() {
    let (_fixture, state, _principal, _) = setup();
    let listener = bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let running = tokio::spawn(serve(listener, state));
    let mut client = TcpStream::connect(address).await.unwrap();
    wire::send(&mut client, packet(Some("guradb"), Some("reader"), None, 0))
        .await
        .unwrap();
    wire::send(&mut client, Password::new("secret".into()))
        .await
        .unwrap();
    let mut key = None;
    loop {
        let tag = client.read_u8().await.unwrap();
        let length = client.read_u32().await.unwrap();
        let mut data = vec![0; length as usize - 4];
        client.read_exact(&mut data).await.unwrap();
        if tag == b'K' {
            key = Some(data);
        }
        if tag == b'Z' {
            break;
        }
    }
    assert_eq!(key.unwrap().len(), 8);
    wire::send(&mut client, Terminate::new()).await.unwrap();
    drop(client);
    // Startup rejection travels through the accept loop's fatal error response.
    let mut client = TcpStream::connect(address).await.unwrap();
    wire::send(&mut client, packet(Some("other"), Some("reader"), None, 0))
        .await
        .unwrap();
    assert_eq!(client.read_u8().await.unwrap(), b'E');
    drop(client);
    let mut cancellation = TcpStream::connect(address).await.unwrap();
    let raw = [16_i32, 80877102, 0, 0]
        .into_iter()
        .flat_map(i32::to_be_bytes)
        .collect::<Vec<_>>();
    cancellation.write_all(&raw).await.unwrap();
    let mut eof = [0];
    assert_eq!(cancellation.read(&mut eof).await.unwrap(), 0);
    let client = TcpStream::connect(address).await.unwrap();
    drop(client);
    tokio::time::sleep(Duration::from_millis(10)).await;
    running.abort();
    let _ = running.await;
}

#[tokio::test(start_paused = true)]
async fn startup_timeout_and_unauthenticated_capacity_are_bounded() {
    let (_fixture, state, _principal, _) = setup();
    let listener = bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let running = tokio::spawn(serve(listener, state));
    let mut clients = Vec::new();
    for _ in 0..74 {
        clients.push(TcpStream::connect(address).await.unwrap());
        tokio::task::yield_now().await;
    }
    tokio::time::advance(Duration::from_secs(11)).await;
    tokio::task::yield_now().await;
    let mut data = [0; 1];
    assert!(clients[0].read_exact(&mut data).await.is_ok());
    assert_eq!(data[0], b'E');
    assert!(clients
        .last_mut()
        .unwrap()
        .read_exact(&mut data)
        .await
        .is_err());
    drop(clients);
    running.abort();
    let _ = running.await;
}
