use crate::fixture::{Fixture, DATASET};
use crate::{
    auth, routes,
    state::{Registry, State},
};
use axum::{
    extract::{Path, Query, State as ExtractState},
    http::{HeaderMap, HeaderValue, StatusCode},
    response::IntoResponse,
    Json,
};
use guradb_common::{digest, protocol::QueryRequest, Error, Limits};
use serde_json::json;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::{Mutex, Semaphore};

pub fn setup() -> (Fixture, Arc<State>, auth::Principal, HeaderMap) {
    let fixture = Fixture::new();
    let principal = auth::Principal {
        token_sha256: digest(b"secret"),
        tenant_id: "tenant".into(),
        principal_id: "reader".into(),
        datasets: vec![DATASET.into()],
    };
    let auth_file = fixture.root.join("auth.json");
    std::fs::write(&auth_file, serde_json::to_vec(&json!({"principals":[{"token_sha256":principal.token_sha256,"tenant_id":"tenant","principal_id":"reader","datasets":[DATASET]}]})).unwrap()).unwrap();
    let state = Arc::new(State {
        catalog: fixture.catalog.clone(),
        auth_file,
        limits: Limits::default(),
        registry: Mutex::new(Registry::default()),
        slots: Semaphore::new(2),
        key: vec![1; 32],
    });
    let mut headers = HeaderMap::new();
    headers.insert("authorization", HeaderValue::from_static("Bearer secret"));
    (fixture, state, principal, headers)
}

async fn finished(state: &State, principal: &auth::Principal, id: &str) {
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if state
                .registry
                .lock()
                .await
                .get_mut(id, principal)
                .unwrap()
                .finished
                .is_some()
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(2)).await;
        }
    })
    .await
    .expect("bounded worker completion");
}

pub fn request(sql: &str) -> QueryRequest {
    serde_json::from_value(json!({"sql":sql})).unwrap()
}

#[tokio::test]
async fn auth_configuration_errors_and_revocation() {
    let (_fixture, state, principal, headers) = setup();
    assert_eq!(
        auth::authenticate(&state.auth_file, &headers)
            .await
            .unwrap()
            .principal_id,
        principal.principal_id
    );
    assert!(auth::authenticate(&state.auth_file, &HeaderMap::new())
        .await
        .is_err());
    let mut bad = headers.clone();
    bad.insert("authorization", HeaderValue::from_static("Bearer bad"));
    assert!(auth::authenticate(&state.auth_file, &bad).await.is_err());
    let original = std::fs::read(&state.auth_file).unwrap();
    for raw in [
        b"not JSON".to_vec(),
        vec![b'x'; 65537],
        br#"{"principals":[]}"#.to_vec(),
    ] {
        std::fs::write(&state.auth_file, raw).unwrap();
        assert_eq!(
            auth::load(&state.auth_file).await.err().unwrap().code,
            "auth_unavailable"
        );
    }
    let mut config: serde_json::Value = serde_json::from_slice(&original).unwrap();
    config["principals"][0]["datasets"] = json!(["invalid"]);
    std::fs::write(&state.auth_file, serde_json::to_vec(&config).unwrap()).unwrap();
    assert!(auth::load(&state.auth_file).await.is_err());
    config["principals"][0]["datasets"] = json!([]);
    std::fs::write(&state.auth_file, serde_json::to_vec(&config).unwrap()).unwrap();
    assert!(crate::pg::authorize(&state, &principal)
        .await
        .unwrap()
        .datasets
        .is_empty());
    config["principals"][0]["token_sha256"] = json!(digest(b"different"));
    std::fs::write(&state.auth_file, serde_json::to_vec(&config).unwrap()).unwrap();
    assert_eq!(
        crate::pg::authorize(&state, &principal)
            .await
            .err()
            .unwrap()
            .code,
        "forbidden"
    );
    assert!(auth::load(state.auth_file.parent().unwrap()).await.is_err());
    std::fs::remove_file(&state.auth_file).unwrap();
    assert!(auth::load(&state.auth_file).await.is_err());
}

#[tokio::test]
async fn handles_results_cursors_and_error_statuses() {
    let (_fixture, state, principal, headers) = setup();
    let req = request("SELECT * FROM documents ORDER BY id");
    let plan = guradb_query::sql::prepare(&req, &state.catalog, &principal.datasets).unwrap();
    let handle = state
        .submit(plan, principal.clone(), 10000, 100)
        .await
        .ok()
        .unwrap();
    for _ in 0..100 {
        if state
            .registry
            .lock()
            .await
            .get_mut(&handle.query_id, &principal)
            .unwrap()
            .finished
            .is_some()
        {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert_eq!(
        state
            .registry
            .lock()
            .await
            .get_mut(&handle.query_id, &principal)
            .unwrap()
            .handle
            .status,
        "succeeded"
    );
    assert_eq!(
        routes::status(
            ExtractState(state.clone()),
            headers.clone(),
            Path(handle.query_id.clone())
        )
        .await
        .ok()
        .unwrap()
        .status(),
        StatusCode::OK
    );
    assert_eq!(
        routes::cancel(
            ExtractState(state.clone()),
            headers.clone(),
            Path(handle.query_id.clone())
        )
        .await
        .ok()
        .unwrap()
        .status(),
        StatusCode::OK
    );
    let page = serde_json::from_value(json!({"page_size":1})).unwrap();
    assert_eq!(
        routes::results(
            ExtractState(state.clone()),
            headers.clone(),
            Path(handle.query_id.clone()),
            Ok(Query(page))
        )
        .await
        .ok()
        .unwrap()
        .status(),
        StatusCode::OK
    );
    let cursor = state.cursor(&handle.query_id, &principal, "view", 1);
    assert_eq!(
        state
            .offset(&cursor, &handle.query_id, &principal, "view")
            .unwrap(),
        1
    );
    let page = serde_json::from_value(json!({"cursor":cursor,"page_size":2})).unwrap();
    routes::results(
        ExtractState(state.clone()),
        headers.clone(),
        Path(handle.query_id.clone()),
        Ok(Query(page)),
    )
    .await
    .ok()
    .unwrap();
    for cursor in [
        "x".to_string(),
        "x.x".into(),
        format!("{}.x", "a".repeat(100)),
        "x".repeat(2049),
        state.cursor("other", &principal, "view", 1),
    ] {
        assert!(state
            .offset(&cursor, &handle.query_id, &principal, "view")
            .is_err());
    }
    for code in [
        "unauthorized",
        "auth_unavailable",
        "not_found",
        "expired",
        "not_ready",
        "resource_limit",
        "invalid_request",
    ] {
        assert!(
            routes::ApiError::from(Error::new(code, "error"))
                .into_response()
                .status()
                .is_client_error()
                || code == "auth_unavailable"
        );
    }
    let req = request("SELECT id FROM documents WHERE id = 2");
    assert_eq!(
        routes::submit(ExtractState(state.clone()), headers.clone(), Ok(Json(req)))
            .await
            .ok()
            .unwrap()
            .status(),
        StatusCode::ACCEPTED
    );
    let mut req = request("SELECT id FROM documents");
    req.max_rows = Some(0);
    assert!(
        routes::submit(ExtractState(state.clone()), headers.clone(), Ok(Json(req)))
            .await
            .is_err()
    );
    for page in [
        json!({"page_size":0}),
        json!({"cursor":state.cursor(&handle.query_id,&principal,"view",100)}),
    ] {
        assert!(routes::results(
            ExtractState(state.clone()),
            headers.clone(),
            Path(handle.query_id.clone()),
            Ok(Query(serde_json::from_value(page).unwrap()))
        )
        .await
        .is_err());
    }
    // Force a queued operation to stay queued, so cancel/prune cannot race execution.
    let _permits = state.slots.acquire_many(2).await.ok().unwrap();
    let plan = guradb_query::sql::prepare(
        &request("SELECT id FROM documents"),
        &state.catalog,
        &principal.datasets,
    )
    .unwrap();
    let queued = state
        .submit(plan, principal.clone(), 10000, 100)
        .await
        .ok()
        .unwrap();
    let page = serde_json::from_value(json!({})).unwrap();
    assert!(routes::results(
        ExtractState(state.clone()),
        headers.clone(),
        Path(queued.query_id.clone()),
        Ok(Query(page))
    )
    .await
    .is_err());
    assert_eq!(
        routes::cancel(
            ExtractState(state.clone()),
            headers,
            Path(queued.query_id.clone())
        )
        .await
        .ok()
        .unwrap()
        .status(),
        StatusCode::ACCEPTED
    );
    drop(_permits);
    tokio::time::sleep(Duration::from_millis(10)).await;
    assert_eq!(
        state
            .registry
            .lock()
            .await
            .get_mut(&queued.query_id, &principal)
            .unwrap()
            .handle
            .status,
        "cancelled"
    );
    let mut registry = state.registry.lock().await;
    registry
        .get_mut(&handle.query_id, &principal)
        .unwrap()
        .finished = Some(Instant::now() - Duration::from_secs(61));
    registry.prune(&Limits::default());
    assert_eq!(
        registry
            .get_mut(&handle.query_id, &principal)
            .err()
            .unwrap()
            .code,
        "expired"
    );
    registry.prune(&Limits {
        handles: 0,
        ..Limits::default()
    });
    assert_eq!(
        registry
            .get_mut(&handle.query_id, &principal)
            .err()
            .unwrap()
            .code,
        "not_found"
    );
}

#[tokio::test]
async fn execution_reauthorizes_and_reports_failures() {
    let (_fixture, state, principal, _headers) = setup();
    std::fs::write(&state.auth_file,b"{\"principals\":[{\"token_sha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"tenant_id\":\"tenant\",\"principal_id\":\"reader\",\"datasets\":[]}]}").unwrap();
    let plan = guradb_query::sql::prepare(
        &request("SELECT * FROM documents"),
        &state.catalog,
        &principal.datasets,
    )
    .unwrap();
    let handle = state
        .submit(plan, principal.clone(), 10000, 10)
        .await
        .ok()
        .unwrap();
    finished(&state, &principal, &handle.query_id).await;
    assert_eq!(
        state
            .registry
            .lock()
            .await
            .get_mut(&handle.query_id, &principal)
            .unwrap()
            .handle
            .error
            .as_ref()
            .unwrap()
            .code,
        "forbidden"
    );
    let (_fixture, state, principal, _headers) = setup();
    state.slots.close();
    let plan = guradb_query::sql::prepare(
        &request("SELECT * FROM documents"),
        &state.catalog,
        &principal.datasets,
    )
    .unwrap();
    let handle = state
        .submit(plan, principal.clone(), 10000, 10)
        .await
        .ok()
        .unwrap();
    finished(&state, &principal, &handle.query_id).await;
    assert_eq!(
        state
            .registry
            .lock()
            .await
            .get_mut(&handle.query_id, &principal)
            .unwrap()
            .handle
            .status,
        "failed"
    );
}

#[test]
fn cli_error_is_reported_by_real_entrypoint() {
    if std::env::var_os("GURA_ENTRY_UNIT").is_some() {
        crate::main();
        return;
    }
    let result = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "gateway_tests::cli_error_is_reported_by_real_entrypoint",
            "--nocapture",
        ])
        .env("GURA_ENTRY_UNIT", "1")
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&result.stderr).contains("usage: guradb --config"));
}

#[tokio::test]
async fn startup_config_validation_and_listener_lifecycle() {
    use tokio::net::{TcpListener, TcpStream};
    let (fixture, state, _, _) = setup();
    let path = fixture.root.join("config.json");
    for raw in [b"bad".to_vec(), vec![b'x'; 262145]] {
        std::fs::write(&path, raw).unwrap();
        assert!(crate::serve(vec![
            "guradb".into(),
            "--config".into(),
            path.to_str().unwrap().into()
        ])
        .await
        .is_err());
    }
    assert!(crate::serve(vec![
        "guradb".into(),
        "--config".into(),
        fixture.root.to_str().unwrap().into()
    ])
    .await
    .is_err());
    assert!(crate::serve(vec![]).await.is_err());
    assert!(crate::serve(vec![
        "guradb".into(),
        "--config".into(),
        "/nonexistent".into()
    ])
    .await
    .is_err());
    assert_eq!(crate::listen(), "127.0.0.1:8080");
    let bytes = std::fs::read(fixture.root.join("manifest.json")).unwrap();
    for pg in [None, Some("127.0.0.1:0")] {
        let reserved = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = reserved.local_addr().unwrap();
        drop(reserved);
        let mut config = json!({"listen":address.to_string(),"auth_file":state.auth_file,"manifests":[{"path":fixture.root.join("manifest.json"),"sha256":digest(&bytes)}]});
        if let Some(pg) = pg {
            config["pg_listen"] = json!(pg);
        }
        std::fs::write(&path, serde_json::to_vec(&config).unwrap()).unwrap();
        let task = tokio::spawn(crate::serve(vec![
            "guradb".into(),
            "--config".into(),
            path.to_str().unwrap().into(),
        ]));
        let mut connected = false;
        for _ in 0..100 {
            if TcpStream::connect(address).await.is_ok() {
                connected = true;
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        assert!(connected);
        // Stop the owned service through its real graceful shutdown listener.
        std::process::Command::new("kill")
            .args(["-INT", &std::process::id().to_string()])
            .status()
            .unwrap();
        task.await.unwrap().unwrap();
    }
}

#[tokio::test]
async fn handle_capacity_queued_timeout_and_signed_invalid_cursor() {
    use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let (_fixture, mut state, principal, _) = setup();
    Arc::get_mut(&mut state).unwrap().limits.handles = 0;
    let plan = guradb_query::sql::prepare(
        &request("SELECT id FROM documents"),
        &state.catalog,
        &principal.datasets,
    )
    .unwrap();
    assert_eq!(
        state
            .submit(plan, principal.clone(), 10, 10)
            .await
            .err()
            .unwrap()
            .code,
        "resource_limit"
    );
    Arc::get_mut(&mut state).unwrap().limits.handles = 32;
    let held = state.slots.acquire_many(2).await.unwrap();
    let plan = guradb_query::sql::prepare(
        &request("SELECT id FROM documents"),
        &state.catalog,
        &principal.datasets,
    )
    .unwrap();
    let queued = state.submit(plan, principal.clone(), 1, 10).await.unwrap();
    finished(&state, &principal, &queued.query_id).await;
    assert_eq!(
        state
            .registry
            .lock()
            .await
            .get_mut(&queued.query_id, &principal)
            .unwrap()
            .handle
            .error
            .as_ref()
            .unwrap()
            .code,
        "timeout"
    );
    drop(held);
    let message = b"valid HMAC, malformed JSON";
    let mut mac = Hmac::<Sha256>::new_from_slice(&state.key).unwrap();
    mac.update(message);
    let cursor = format!(
        "{}.{}",
        URL_SAFE_NO_PAD.encode(message),
        URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes())
    );
    assert_eq!(
        state
            .offset(&cursor, "id", &principal, "view")
            .unwrap_err()
            .code,
        "invalid_cursor"
    );
}
