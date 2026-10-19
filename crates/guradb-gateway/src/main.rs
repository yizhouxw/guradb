mod auth;
mod pg;
mod routes;
mod state;

use axum::{
    extract::DefaultBodyLimit,
    routing::{get, post},
    Router,
};

use guradb_common::{manifest::ManifestRef, Error, Limits, Result};
use serde::Deserialize;
use std::{path::PathBuf, sync::Arc};
use tokio::{
    io::AsyncReadExt,
    sync::{Mutex, Semaphore},
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    #[serde(default = "listen")]
    listen: String,
    #[serde(default)]
    pg_listen: Option<String>,
    manifests: Vec<ManifestRef>,
    auth_file: PathBuf,
    #[serde(default)]
    limits: Limits,
}
fn listen() -> String {
    "127.0.0.1:8080".into()
}
#[tokio::main]
async fn main() {
    if let Err(error) = serve(std::env::args().collect()).await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
async fn serve(args: Vec<String>) -> Result<()> {
    if args.len() != 3 || args[1] != "--config" {
        return Err(Error::new(
            "invalid_config",
            "usage: guradb --config <path>",
        ));
    }
    let file = tokio::fs::File::open(&args[2])
        .await
        .map_err(|_| Error::new("invalid_config", "cannot open config"))?;
    let mut bytes = Vec::new();
    file.take(262145)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| Error::new("invalid_config", "cannot read config"))?;
    if bytes.len() > 262144 {
        return Err(Error::new("invalid_config", "config too large"));
    }
    let config: Config = serde_json::from_slice(&bytes)
        .map_err(|_| Error::new("invalid_config", "invalid config JSON"))?;
    config.limits.validate()?;
    auth::load(&config.auth_file).await?;
    let catalog = guradb_catalog::load(&config.manifests)?;
    let state = Arc::new(state::State {
        catalog,
        auth_file: config.auth_file,
        slots: Semaphore::new(config.limits.concurrent_queries),
        limits: config.limits,
        registry: Mutex::new(state::Registry::default()),
        key: [
            uuid::Uuid::new_v4().as_bytes().as_slice(),
            uuid::Uuid::new_v4().as_bytes().as_slice(),
        ]
        .concat(),
    });
    let pg_listener = match config.pg_listen {
        Some(address) => Some(pg::bind(&address).await?),
        None => None,
    };
    let pg_state = state.clone();
    let app = Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/v1/queries", post(routes::submit))
        .route(
            "/v1/queries/{id}",
            get(routes::status).delete(routes::cancel),
        )
        .route("/v1/queries/{id}/results", get(routes::results))
        .layer(DefaultBodyLimit::max(65536))
        .with_state(state);
    let listener = tokio::net::TcpListener::bind(&config.listen)
        .await
        .map_err(|_| Error::new("invalid_config", "cannot bind listener"))?;
    let http = async {
        axum::serve(listener, app)
            .with_graceful_shutdown(async {
                let _ = tokio::signal::ctrl_c().await;
            })
            .await
            .map_err(|_| Error::new("service_failed", "HTTP service stopped"))
    };
    if let Some(listener) = pg_listener {
        tokio::select! {
            result = http => result,
            result = pg::serve(listener, pg_state) => result,
        }
    } else {
        http.await
    }
}

#[cfg(test)]
#[path = "../../../tests/rust_fixture.rs"]
mod fixture;
#[cfg(test)]
#[path = "../tests/unit/gateway.rs"]
mod gateway_tests;
