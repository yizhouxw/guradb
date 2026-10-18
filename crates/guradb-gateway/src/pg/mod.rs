mod session;
mod types;
mod wire;

use crate::{
    auth::{self, Principal},
    state::State,
};
use guradb_common::{digest, Error, Result};
use pgwire::messages::{
    startup::{
        Authentication, BackendKeyData, NegotiateProtocolVersion, ParameterStatus, SecretKey,
    },
    PgWireFrontendMessage as Front,
};
use std::{
    collections::HashMap,
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    io::AsyncWriteExt,
    net::{TcpListener, TcpStream},
    sync::Semaphore,
};
use tokio_util::sync::CancellationToken;

pub(super) type Active = Arc<Mutex<Option<CancellationToken>>>;
type Cancellations = Arc<Mutex<HashMap<(i32, i32), Active>>>;

pub async fn bind(address: &str) -> Result<TcpListener> {
    let address: SocketAddr = address.parse().map_err(|_| {
        Error::new(
            "invalid_config",
            "pg_listen must be a loopback IP address and port",
        )
    })?;
    if !address.ip().is_loopback() {
        return Err(Error::new(
            "invalid_config",
            "unencrypted PostgreSQL listener must use loopback",
        ));
    }
    TcpListener::bind(address)
        .await
        .map_err(|_| Error::new("invalid_config", "cannot bind PostgreSQL listener"))
}
pub async fn serve(listener: TcpListener, state: Arc<State>) -> Result<()> {
    let connections = Arc::new(Semaphore::new(64));
    let incoming = Arc::new(Semaphore::new(72));
    let cancellations = Cancellations::default();
    loop {
        let (mut socket, _) = listener
            .accept()
            .await
            .map_err(|_| Error::new("service_failed", "PostgreSQL accept failed"))?;
        let Ok(permit) = incoming.clone().try_acquire_owned() else {
            // No task or allocation per rejected connection.
            let _ = socket.shutdown().await;
            continue;
        };
        let (state, connections, cancellations) =
            (state.clone(), connections.clone(), cancellations.clone());
        tokio::spawn(async move {
            let _permit = permit;
            let result = tokio::time::timeout(
                Duration::from_secs(10),
                startup(&mut socket, &state, &connections, &cancellations),
            )
            .await;
            match result {
                Ok(Ok(Some((principal, capacity)))) => {
                    let _capacity = capacity;
                    let active = Active::default();
                    let key = {
                        let mut map = cancellations.lock().expect("cancel registry");
                        loop {
                            let random = uuid::Uuid::new_v4();
                            let bytes = random.as_bytes();
                            let key = (
                                (i32::from_be_bytes(bytes[0..4].try_into().expect("UUID width"))
                                    & i32::MAX)
                                    .max(1),
                                i32::from_be_bytes(bytes[4..8].try_into().expect("UUID width")),
                            );
                            if let std::collections::hash_map::Entry::Vacant(entry) = map.entry(key)
                            {
                                entry.insert(active.clone());
                                break key;
                            }
                        }
                    };
                    if wire::send(
                        &mut socket,
                        BackendKeyData::new(key.0, SecretKey::I32(key.1)),
                    )
                    .await
                    .is_ok()
                        && wire::ready(&mut socket).await.is_ok()
                    {
                        let _ = session::run(socket, state, principal, active.clone()).await;
                    }
                    if let Some(token) = active.lock().expect("active query").take() {
                        token.cancel();
                    }
                    cancellations.lock().expect("cancel registry").remove(&key);
                }
                Ok(Err(error)) => {
                    if error.code != "connection_closed" {
                        let _ = wire::error(&mut socket, &error, true).await;
                    }
                }
                Err(_) => {
                    let _ = wire::error(
                        &mut socket,
                        &Error::new("timeout", "PostgreSQL startup timeout"),
                        true,
                    )
                    .await;
                }
                _ => {}
            }
        });
    }
}
async fn startup(
    socket: &mut TcpStream,
    state: &State,
    connections: &Arc<Semaphore>,
    cancellations: &Cancellations,
) -> Result<Option<(Principal, tokio::sync::OwnedSemaphorePermit)>> {
    let mut negotiation = 0;
    let startup = loop {
        let bytes = wire::frame(socket, true).await?;
        if bytes.len() == 8 && matches!(&bytes[4..], [4, 210, 22, 47] | [4, 210, 22, 48]) {
            negotiation += 1;
            if negotiation > 2 {
                return Err(wire::protocol());
            }
            socket.write_all(b"N").await.map_err(wire::io_error)?;
            continue;
        }
        match wire::decode(bytes, true)? {
            Front::Startup(startup) => break startup,
            Front::CancelRequest(cancel) => {
                if let Some(secret) = cancel.secret_key.as_i32() {
                    if let Some(active) = cancellations
                        .lock()
                        .expect("cancel registry")
                        .get(&(cancel.pid, secret))
                    {
                        if let Some(token) = active.lock().expect("active query").as_ref() {
                            token.cancel();
                        }
                    }
                }
                return Ok(None);
            }
            _ => return Err(wire::protocol()),
        }
    };
    let capacity = connections
        .clone()
        .try_acquire_owned()
        .map_err(|_| Error::new("connection_limit", "PostgreSQL connection capacity reached"))?;
    // PostgreSQL 18 sends the full FrontendProtocol value here (REL_18_STABLE
    // backend_startup.c), despite the older manual naming this a minor version.
    if startup.protocol_number_minor != 0 {
        wire::send(socket, NegotiateProtocolVersion::new(196608, vec![])).await?;
    }
    for (name, value) in &startup.parameters {
        match name.as_str() {
            "user" | "database" | "application_name" => {}
            "client_encoding"
                if value.eq_ignore_ascii_case("UTF8") || value.eq_ignore_ascii_case("UTF-8") => {}
            "options" if value.is_empty() => {}
            _ => {
                return Err(Error::new(
                    "unsupported",
                    "unsupported PostgreSQL startup option",
                ))
            }
        }
    }
    if startup.parameters.get("database").map(String::as_str) != Some("guradb") {
        return Err(Error::new("database_unknown", "database must be guradb"));
    }
    let user = startup
        .parameters
        .get("user")
        .ok_or_else(|| Error::new("unauthorized", "PostgreSQL user required"))?;
    wire::send(socket, Authentication::CleartextPassword).await?;
    let Front::PasswordMessageFamily(password) =
        wire::decode(wire::frame(socket, false).await?, false)?
    else {
        return Err(wire::protocol());
    };
    let password = password.into_password().map_err(|_| wire::protocol())?;
    if password.password.is_empty() {
        return Err(Error::new("unauthorized", "invalid authentication"));
    }
    let hash = digest(password.password.as_bytes());
    let principal = auth::load(&state.auth_file)
        .await?
        .into_iter()
        .find(|p| {
            p.principal_id == *user
                && p.token_sha256
                    .bytes()
                    .zip(hash.bytes())
                    .fold(0u8, |diff, (a, b)| diff | (a ^ b))
                    == 0
        })
        .ok_or_else(|| Error::new("unauthorized", "invalid authentication"))?;
    wire::send(socket, Authentication::Ok).await?;
    for (name, value) in [
        ("server_version", "18.0"),
        ("server_encoding", "UTF8"),
        ("client_encoding", "UTF8"),
        ("DateStyle", "ISO, MDY"),
        ("integer_datetimes", "on"),
        ("standard_conforming_strings", "on"),
        ("TimeZone", "UTC"),
        ("guradb_version", "0.1.0"),
    ] {
        wire::send(socket, ParameterStatus::new(name.into(), value.into())).await?;
    }
    Ok(Some((principal, capacity)))
}

pub(super) async fn authorize(state: &State, original: &Principal) -> Result<Principal> {
    auth::load(&state.auth_file)
        .await?
        .into_iter()
        .find(|p| {
            p.token_sha256 == original.token_sha256
                && p.tenant_id == original.tenant_id
                && p.principal_id == original.principal_id
        })
        .ok_or_else(|| Error::new("forbidden", "PostgreSQL session authorization revoked"))
}
