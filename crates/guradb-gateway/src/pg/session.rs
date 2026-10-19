use super::{authorize, types, wire, Active};
use crate::{auth::Principal, state::State};
use guradb_common::{protocol::QueryRequest, Error, Result};
use guradb_query::{
    describe::{self, Description},
    Output,
};
use pgwire::messages::{
    data::ParameterDescription,
    extendedquery::{BindComplete, CloseComplete, ParseComplete, PortalSuspended},
    response::{CommandComplete, EmptyQueryResponse},
    Message, PgWireFrontendMessage as Front,
};
use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    net::{tcp::OwnedWriteHalf, TcpStream},
    sync::mpsc,
};
use tokio_util::sync::CancellationToken;

struct Statement {
    sql: String,
    description: Description,
    oids: Vec<u32>,
}
struct Portal {
    statement: Arc<Statement>,
    parameters: Vec<serde_json::Value>,
    formats: Vec<i16>,
    output: Option<Output>,
    offset: usize,
    finished: bool,
    created: Instant,
}
struct Session {
    state: Arc<State>,
    principal: Principal,
    active: Active,
    disconnected: CancellationToken,
    statements: HashMap<String, Arc<Statement>>,
    portals: HashMap<String, Portal>,
}

pub async fn run(
    socket: TcpStream,
    state: Arc<State>,
    principal: Principal,
    active: Active,
) -> Result<()> {
    let (mut reader, mut writer) = socket.into_split();
    let disconnected = CancellationToken::new();
    let (tx, mut rx) = mpsc::channel(8);
    let reader_closed = disconnected.clone();
    let reader_task = tokio::spawn(async move {
        loop {
            let incoming = wire::frame(&mut reader, false)
                .await
                .and_then(|frame| wire::decode(frame, false));
            if matches!(incoming, Ok(Front::Terminate(_))) {
                break;
            }
            match incoming {
                Ok(message) => {
                    if tx.try_send(Ok(message)).is_err() {
                        break;
                    }
                }
                Err(error) => {
                    let _ = tx.try_send(Err(error));
                    break;
                }
            }
        }
        reader_closed.cancel();
    });
    let mut session = Session {
        state,
        principal,
        active,
        disconnected: disconnected.clone(),
        statements: HashMap::new(),
        portals: HashMap::new(),
    };
    let result = async {
        let mut awaiting_sync = false;
        while let Some(message) = rx.recv().await {
            let message = match message {
                Ok(message) => message,
                Err(error) => {
                    let _ = wire::error(&mut writer, &error, true).await;
                    break;
                }
            };
            if matches!(message, Front::Sync(_)) {
                session.portals.clear();
                awaiting_sync = false;
                wire::ready(&mut writer).await?;
                continue;
            }
            if awaiting_sync {
                continue;
            }
            let simple = matches!(message, Front::Query(_));
            let result = session.message(message, &mut writer).await;
            session.active.lock().expect("active query").take();
            if let Err(error) = result {
                if error.code == "connection_closed" {
                    return Err(error);
                }
                // A failed portal cannot resume a partially returned result.
                session.portals.clear();
                wire::error(&mut writer, &error, false).await?;
                awaiting_sync = !simple;
            }
            if simple {
                wire::ready(&mut writer).await?;
            }
        }
        Ok(())
    }
    .await;
    disconnected.cancel();
    reader_task.abort();
    let _ = reader_task.await;
    result
}

impl Session {
    async fn describe(&self, sql: &str, oids: &[u32]) -> Result<Description> {
        let principal = authorize(&self.state, &self.principal).await?;
        let kinds = oids
            .iter()
            .map(|oid| types::kind(*oid))
            .collect::<Result<Vec<_>>>()?;
        describe::describe(sql, &self.state.catalog, &principal.datasets, &kinds)
    }
    async fn message(&mut self, message: Front, writer: &mut OwnedWriteHalf) -> Result<()> {
        match message {
            Front::Query(query) => {
                self.portals.clear();
                self.statements.remove("");
                if query.query.trim().is_empty() {
                    authorize(&self.state, &self.principal).await?;
                    return wire::send(writer, EmptyQueryResponse::new()).await;
                }
                let description = self.describe(&query.query, &[]).await?;
                if !description.parameter_types.is_empty() {
                    return Err(Error::new(
                        "invalid_parameter",
                        "simple query cannot bind parameters",
                    ));
                }
                let statement = Arc::new(Statement {
                    sql: query.query,
                    description,
                    oids: vec![],
                });
                let mut portal = Portal {
                    formats: vec![0; statement.description.columns.len()],
                    statement,
                    parameters: vec![],
                    output: None,
                    offset: 0,
                    finished: false,
                    created: Instant::now(),
                };
                self.execute(&mut portal).await?;
                wire::send(
                    writer,
                    types::description(&portal.statement.description.columns, &portal.formats),
                )
                .await?;
                self.send_rows(&mut portal, 0, writer).await
            }
            Front::Parse(parse) => {
                let name = parse.name.unwrap_or_default();
                if name.is_empty() {
                    self.close_statement(&name);
                }
                if !name.is_empty() && self.statements.contains_key(&name) {
                    return Err(Error::new(
                        "statement_exists",
                        "prepared statement already exists",
                    ));
                }
                if !self.statements.contains_key(&name) && self.statements.len() >= 32 {
                    return Err(Error::new(
                        "resource_limit",
                        "prepared statement capacity reached",
                    ));
                }
                let description = self.describe(&parse.query, &parse.type_oids).await?;
                let oids = description
                    .parameter_types
                    .iter()
                    .enumerate()
                    .map(|(i, kind)| {
                        parse
                            .type_oids
                            .get(i)
                            .copied()
                            .filter(|oid| *oid != 0)
                            .unwrap_or_else(|| types::oid(kind))
                    })
                    .collect();
                self.statements.insert(
                    name,
                    Arc::new(Statement {
                        sql: parse.query,
                        description,
                        oids,
                    }),
                );
                wire::send(writer, ParseComplete::new()).await
            }
            Front::Bind(bind) => {
                authorize(&self.state, &self.principal).await?;
                let statement = self
                    .statements
                    .get(bind.statement_name.as_deref().unwrap_or_default())
                    .ok_or_else(|| {
                        Error::new("statement_missing", "prepared statement does not exist")
                    })?
                    .clone();
                let name = bind.portal_name.unwrap_or_default();
                if !name.is_empty() && self.portals.contains_key(&name) {
                    return Err(Error::new("portal_exists", "portal already exists"));
                }
                if !self.portals.contains_key(&name) && self.portals.len() >= 16 {
                    return Err(Error::new("resource_limit", "portal capacity reached"));
                }
                if bind.parameters.len() != statement.oids.len() {
                    return Err(Error::new(
                        "invalid_parameter",
                        "bind parameter count mismatch",
                    ));
                }
                let input_formats =
                    types::formats(&bind.parameter_format_codes, statement.oids.len())?;
                let parameters = bind
                    .parameters
                    .iter()
                    .zip(&statement.oids)
                    .zip(input_formats)
                    .map(|((value, oid), format)| {
                        types::parameter(value.as_deref(), *oid, format == 1)
                    })
                    .collect::<Result<Vec<_>>>()?;
                let formats = types::formats(
                    &bind.result_column_format_codes,
                    statement.description.columns.len(),
                )?;
                // Recompile at Bind to reject incompatible values before BindComplete.
                let principal = authorize(&self.state, &self.principal).await?;
                guradb_query::sql::prepare(
                    &request(&statement.sql, parameters.clone()),
                    &self.state.catalog,
                    &principal.datasets,
                )?;
                self.portals.insert(
                    name,
                    Portal {
                        statement,
                        parameters,
                        formats,
                        output: None,
                        offset: 0,
                        finished: false,
                        created: Instant::now(),
                    },
                );
                wire::send(writer, BindComplete::new()).await
            }
            Front::Describe(describe) => {
                let name = describe.name.unwrap_or_default();
                if describe.target_type == b'S' {
                    let statement = self.statements.get(&name).ok_or_else(|| {
                        Error::new("statement_missing", "prepared statement does not exist")
                    })?;
                    self.describe(&statement.sql, &statement.oids).await?;
                    wire::send(writer, ParameterDescription::new(statement.oids.clone())).await?;
                    wire::send(
                        writer,
                        types::description(
                            &statement.description.columns,
                            &vec![0; statement.description.columns.len()],
                        ),
                    )
                    .await
                } else {
                    let portal = self
                        .portals
                        .get(&name)
                        .ok_or_else(|| Error::new("portal_missing", "portal does not exist"))?;
                    self.describe(&portal.statement.sql, &portal.statement.oids)
                        .await?;
                    wire::send(
                        writer,
                        types::description(&portal.statement.description.columns, &portal.formats),
                    )
                    .await
                }
            }
            Front::Execute(execute) => {
                let name = execute.name.unwrap_or_default();
                let mut portal = self
                    .portals
                    .remove(&name)
                    .ok_or_else(|| Error::new("portal_missing", "portal does not exist"))?;
                if portal.created.elapsed()
                    > Duration::from_secs(self.state.limits.retention_seconds)
                {
                    return Err(Error::new("portal_missing", "portal expired"));
                }
                if portal.output.is_none() && !portal.finished {
                    if self.portals.values().any(|p| p.output.is_some()) {
                        return Err(Error::new(
                            "resource_limit",
                            "only one suspended result per connection is supported",
                        ));
                    }
                    self.execute(&mut portal).await?;
                }
                self.send_rows(&mut portal, execute.max_rows as usize, writer)
                    .await?;
                self.portals.insert(name, portal);
                Ok(())
            }
            Front::Close(close) => {
                let name = close.name.unwrap_or_default();
                if close.target_type == b'S' {
                    self.close_statement(&name);
                } else {
                    self.portals.remove(&name);
                }
                wire::send(writer, CloseComplete::new()).await
            }
            Front::Flush(_) => Ok(()),
            _ => Err(wire::protocol()),
        }
    }

    fn close_statement(&mut self, name: &str) {
        if let Some(statement) = self.statements.remove(name) {
            self.portals
                .retain(|_, portal| !Arc::ptr_eq(&portal.statement, &statement));
        }
    }

    async fn execute(&self, portal: &mut Portal) -> Result<()> {
        let cancel = CancellationToken::new();
        *self.active.lock().expect("active query") = Some(cancel.clone());
        let work = async {
            let _permit = self
                .state
                .slots
                .acquire()
                .await
                .map_err(|_| Error::new("execution_failed", "executor closed"))?;
            let principal = authorize(&self.state, &self.principal).await?;
            let plan = guradb_query::sql::prepare(
                &request(&portal.statement.sql, portal.parameters.clone()),
                &self.state.catalog,
                &principal.datasets,
            )?;
            let output = guradb_query::execute(
                plan,
                &self.state.limits,
                self.state.limits.max_rows,
                &cancel,
            )
            .await?;
            if output.truncated {
                return Err(Error::new(
                    "resource_limit",
                    "result exceeds max_rows; add an explicit SQL LIMIT",
                ));
            }
            // Validate every row and the wire byte budget before sending any result.
            let mut bytes =
                types::description(&output.columns, &portal.formats).message_length() + 64;
            for row in &output.rows {
                bytes += types::row(&output.columns, row, &portal.formats)?.message_length() + 1;
                if bytes > self.state.limits.result_bytes {
                    return Err(Error::new(
                        "resource_limit",
                        "PG result exceeds byte budget",
                    ));
                }
            }
            Ok(output)
        };
        let result = tokio::select! {
            biased;
            _ = self.disconnected.cancelled() => Err(Error::new("cancelled", "PostgreSQL client disconnected")),
            _ = cancel.cancelled() => Err(Error::new("cancelled", "query cancelled")),
            result = tokio::time::timeout(Duration::from_millis(self.state.limits.timeout_ms), work) =>
                result.unwrap_or_else(|_| Err(Error::new("timeout", "query deadline exceeded"))),
        };
        if result.is_err() {
            cancel.cancel();
        }
        portal.output = Some(result?);
        Ok(())
    }
    async fn send_rows(
        &self,
        portal: &mut Portal,
        max_rows: usize,
        writer: &mut OwnedWriteHalf,
    ) -> Result<()> {
        let cancel = {
            let mut active = self.active.lock().expect("active query");
            active.get_or_insert_with(CancellationToken::new).clone()
        };
        // Interrupting write_all may leave a partially written packet. Close the
        // connection on cancellation/timeout during delivery instead of appending
        // an ErrorResponse to a corrupt frame. Execution cancellation uses 57014.
        tokio::select! {
            biased;
            _ = self.disconnected.cancelled() => Err(Error::new("connection_closed", "PostgreSQL client disconnected")),
            _ = cancel.cancelled() => Err(Error::new("connection_closed", "PostgreSQL result delivery cancelled")),
            result = tokio::time::timeout(Duration::from_secs(10), self.send_rows_inner(portal, max_rows, writer)) =>
                result.unwrap_or_else(|_| Err(Error::new("connection_closed", "PostgreSQL result delivery timeout"))),
        }
    }
    async fn send_rows_inner(
        &self,
        portal: &mut Portal,
        max_rows: usize,
        writer: &mut OwnedWriteHalf,
    ) -> Result<()> {
        // Reauthorize each result retrieval, including suspended portal resumes.
        let principal = authorize(&self.state, &self.principal).await?;
        guradb_query::sql::prepare(
            &request(&portal.statement.sql, portal.parameters.clone()),
            &self.state.catalog,
            &principal.datasets,
        )?;
        if let Some(cancel) = self.active.lock().expect("active query").as_ref() {
            if cancel.is_cancelled() {
                return Err(Error::new("cancelled", "query cancelled"));
            }
        }
        let Some(output) = &portal.output else {
            return wire::send(
                writer,
                CommandComplete::new(format!("SELECT {}", portal.offset)),
            )
            .await;
        };
        let end = if max_rows == 0 {
            output.rows.len()
        } else {
            portal
                .offset
                .saturating_add(max_rows)
                .min(output.rows.len())
        };
        for row in &output.rows[portal.offset..end] {
            wire::send(writer, types::row(&output.columns, row, &portal.formats)?).await?;
        }
        portal.offset = end;
        if end == output.rows.len() {
            wire::send(writer, CommandComplete::new(format!("SELECT {}", end))).await?;
            portal.output = None;
            portal.finished = true;
        } else {
            wire::send(writer, PortalSuspended::new()).await?;
        }
        Ok(())
    }
}
fn request(sql: &str, parameters: Vec<serde_json::Value>) -> QueryRequest {
    QueryRequest {
        sql: sql.into(),
        parameters,
        mode: "read_only".into(),
        timeout_ms: None,
        max_rows: None,
        read_consistency: "published".into(),
        read_view_id: None,
    }
}

#[cfg(test)]
#[path = "../../tests/unit/session.rs"]
mod tests;

#[cfg(test)]
#[path = "../../tests/unit/session_boundaries.rs"]
mod boundary_tests;
