mod aggregate;
#[cfg(test)]
mod aggregate_tests;
mod compile;
mod execution;
mod features;
mod mcp;
mod media;
mod media_path;
mod sample;
mod search;
mod source;
mod sql;
#[cfg(test)]
mod tests;
mod vector;
mod view;

use serde::{Deserialize, Serialize};
use std::{path::PathBuf, sync::Arc, time::Duration};
use tokio::io::AsyncWriteExt;

type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Serialize)]
struct Error {
    code: String,
    message: String,
}
impl Error {
    fn new(code: &str, message: &str) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, out: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(out, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for Error {}

#[derive(Clone, Serialize)]
struct Column {
    name: String,
    r#type: String,
}
struct Manifest {
    schema: Vec<Column>,
}
struct Dataset {
    manifest: Manifest,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    source: PathBuf,
    sha256: String,
    #[serde(default = "timeout_default")]
    timeout_ms: u64,
}
fn timeout_default() -> u64 {
    5000
}
const SOURCE_LIMIT: usize = 32 << 20;
const DECODE_LIMIT: usize = 64 << 20;
const POOL_LIMIT: usize = 32 << 20;
const RESULT_LIMIT: usize = 2 << 20;
const ROW_LIMIT: usize = 1000;

fn fail(error: Error, status: i32) -> ! {
    eprintln!(
        "{}",
        serde_json::to_string(&error).expect("bounded error serialization")
    );
    std::process::exit(status)
}

/// Main owns cancellation/deadline; read work lives in a separate thread.
/// Exiting on cancellation releases every resource in this one-process CLI;
/// direct read commands create no files, children, listeners or persistent tasks;
/// view commands own only their explicitly supplied local store.
#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<_> = std::env::args().collect();
    if args.get(1).is_some_and(|s| s == "mcp") {
        let status = mcp::entry(&args);
        std::process::exit(status);
    }
    if args.get(1).is_some_and(|s| s == "dataset") {
        view::managed::entry(args).await;
        return;
    }
    if args.get(1).is_some_and(|s| s == "view") {
        view::entry(args).await;
        return;
    }
    let is_query =
        args.len() == 6 && args[1] == "query" && args[2] == "--config" && args[4] == "--sql";
    let is_media = args.len() == 8
        && args[1] == "media"
        && args[2] == "--config"
        && args[4] == "--asset-id"
        && args[6] == "--source-sha256";
    let is_search = (args.len() == 6 || (args.len() == 8 && args[6] == "--top-k"))
        && args[1] == "search"
        && args[2] == "--config"
        && args[4] == "--query";
    let is_sample =
        args.len() == 6 && args[1] == "sample" && args[2] == "--config" && args[4] == "--selection";
    let vector_request = match vector::parse(&args) {
        Ok(r) => r,
        Err(e) => fail(e, 1),
    };
    if !is_query && !is_media && !is_search && !is_sample && vector_request.is_none() {
        fail(Error::new("invalid_config", "usage: guradb query --config <file> --sql <SELECT> OR media --config <file> --asset-id <id> --source-sha256 <hit SHA> OR search --config <file> --query <text> [--top-k <1..20>] OR vector|hybrid with pinned features/query/top-k OR sample --config <file> --selection <file>"), 1);
    }
    let path = PathBuf::from(&args[3]);
    let bytes = match source::read_bounded(&path, 16384).await {
        Ok(bytes) => bytes,
        Err(_) => fail(
            Error::new("invalid_config", "cannot read bounded regular config file"),
            1,
        ),
    };
    let mut config: Config = match serde_json::from_slice(&bytes) {
        Ok(config) => config,
        Err(_) => fail(Error::new("invalid_config", "invalid config JSON"), 1),
    };
    if !(1..=10000).contains(&config.timeout_ms)
        || config.sha256.len() != 64
        || !config
            .sha256
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        fail(
            Error::new("invalid_config", "invalid sha256 or timeout_ms (1..10000)"),
            1,
        );
    }
    if config.source.is_relative() {
        config.source = path
            .parent()
            .unwrap_or(std::path::Path::new("."))
            .join(&config.source);
    }
    let media_id = if is_media {
        if args[7] != config.sha256 {
            fail(
                Error::new(
                    "source_mismatch",
                    "hit source SHA differs from configured input",
                ),
                1,
            );
        }
        match args[5].parse::<i64>() {
            Ok(id) if (1..=999_999_999_999).contains(&id) => Some(id),
            _ => fail(
                Error::new(
                    "invalid_config",
                    "asset ID must be a positive integer of at most twelve digits",
                ),
                1,
            ),
        }
    } else {
        None
    };
    let search_top_k = if is_search {
        let k = if args.len() == 8 {
            args[7].parse::<usize>().unwrap_or(0)
        } else {
            10
        };
        if !(1..=20).contains(&k) {
            fail(Error::new("invalid_config", "top-k must be 1..20"), 1);
        }
        Some(k)
    } else {
        None
    };
    let media_root = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(std::path::Path::new("."))
        .to_path_buf();
    let duration = Duration::from_millis(config.timeout_ms);
    let statement = args[5].clone();
    operation(duration, move || {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build();
        match runtime {
            Ok(runtime) => runtime.block_on(async move {
                if is_sample {
                    return sample::run(config, PathBuf::from(statement), media_root).await;
                }
                if let Some(request) = vector_request {
                    return vector::run(config, request).await;
                }
                match media_id {
                    Some(id) => media::read(config, media_root, id).await,
                    None => match search_top_k {
                        Some(k) => search::run(config, statement, k).await,
                        None => query(config, statement).await,
                    },
                }
            }),
            Err(_) => Err(Error::new("execution_failed", "cannot start query runtime")),
        }
    })
    .await;
}

async fn operation<F>(duration: Duration, action: F)
where
    F: FnOnce() -> Result<String> + Send + 'static,
{
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let worker = std::thread::spawn(move || {
        let _ = sender.send(action());
    });
    let complete = async move {
        let output = receiver
            .await
            .map_err(|_| Error::new("execution_failed", "query worker stopped"))??;
        tokio::task::spawn_blocking(move || worker.join())
            .await
            .map_err(|_| Error::new("execution_failed", "cannot join query worker"))?
            .map_err(|_| Error::new("execution_failed", "query worker panicked"))?;
        let mut stdout = tokio::io::stdout();
        stdout
            .write_all(output.as_bytes())
            .await
            .map_err(|_| Error::new("output_failed", "cannot write result"))?;
        stdout
            .write_all(b"\n")
            .await
            .map_err(|_| Error::new("output_failed", "cannot write result"))?;
        stdout
            .flush()
            .await
            .map_err(|_| Error::new("output_failed", "cannot flush result"))?;
        Ok::<(), Error>(())
    };
    let result = tokio::select! {
        biased;
        _ = tokio::signal::ctrl_c() => fail(Error::new("cancelled", "query interrupted"), 130),
        _ = tokio::time::sleep(duration) => fail(Error::new("timeout", "query deadline exceeded"), 124),
        result = complete => result,
    };
    if let Err(error) = result {
        fail(error, 1);
    }
}

async fn query(config: Config, statement: String) -> Result<String> {
    let bytes = source::snapshot(&config.source, &config.sha256).await?;
    let (schema, batches) = source::decode(bytes)?;
    let columns = schema
        .fields()
        .iter()
        .map(|field| Column {
            name: field.name().clone(),
            r#type: match field.data_type() {
                arrow::datatypes::DataType::Int64 => "int8",
                arrow::datatypes::DataType::Boolean => "bool",
                _ => "text",
            }
            .into(),
        })
        .collect();
    let dataset = Arc::new(Dataset {
        manifest: Manifest { schema: columns },
    });
    let plan = sql::prepare(&statement, dataset)?;
    let result = execution::execute(plan, schema, batches, &config.sha256).await?;
    // Never publish a successful result if the configured bytes changed while
    // executing. Queries consume only the first verified immutable snapshot.
    source::snapshot(&config.source, &config.sha256).await?;
    Ok(result)
}
