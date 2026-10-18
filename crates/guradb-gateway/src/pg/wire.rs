//! Bound allocation and validate the complete frame before calling pgwire codecs.
//! The upstream low-level decoder assumes complete, well-formed field lengths.
use bytes::BytesMut;
use guradb_common::{Error, Result};
use pgwire::messages::{
    response::{ErrorResponse, ReadyForQuery, TransactionStatus},
    DecodeContext, Message, PgWireFrontendMessage, ProtocolVersion,
};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::time::{timeout, Duration};

pub const FRAME_BYTES: usize = 65_536;
pub fn protocol() -> Error {
    Error::new("protocol_violation", "invalid PostgreSQL protocol message")
}
pub fn io_error(_: std::io::Error) -> Error {
    Error::new("connection_closed", "PostgreSQL connection closed")
}
pub async fn frame<R: AsyncRead + Unpin>(reader: &mut R, startup: bool) -> Result<BytesMut> {
    let read = async {
        let tag = if startup {
            None
        } else {
            Some(reader.read_u8().await.map_err(io_error)?)
        };
        let len = reader.read_i32().await.map_err(io_error)?;
        let max = if startup { 10_000 } else { FRAME_BYTES };
        if len < if startup { 8 } else { 4 } || len as usize > max {
            return Err(protocol());
        }
        let mut out = BytesMut::with_capacity(len as usize + usize::from(tag.is_some()));
        if let Some(tag) = tag {
            out.extend_from_slice(&[tag]);
        }
        out.extend_from_slice(&len.to_be_bytes());
        let header = out.len();
        out.resize(header + len as usize - 4, 0);
        reader
            .read_exact(&mut out[header..])
            .await
            .map_err(io_error)?;
        Ok(out)
    };
    timeout(Duration::from_secs(300), read)
        .await
        .map_err(|_| Error::new("timeout", "connection idle timeout"))?
}

pub fn decode(mut frame: BytesMut, startup: bool) -> Result<PgWireFrontendMessage> {
    validate(&frame, startup)?;
    let mut context = DecodeContext::new(ProtocolVersion::PROTOCOL3_0);
    context.awaiting_frontend_ssl = false;
    context.awaiting_frontend_startup = startup;
    let message = PgWireFrontendMessage::decode(&mut frame, &context)
        .map_err(|_| protocol())?
        .ok_or_else(protocol)?;
    if !frame.is_empty() {
        return Err(protocol());
    }
    Ok(message)
}

struct Fields<'a>(&'a [u8]);
impl Fields<'_> {
    fn take(&mut self, len: usize) -> Result<&[u8]> {
        if len > self.0.len() {
            return Err(protocol());
        }
        let (head, tail) = self.0.split_at(len);
        self.0 = tail;
        Ok(head)
    }
    fn string(&mut self, max: usize) -> Result<()> {
        let n = self.0.iter().position(|v| *v == 0).ok_or_else(protocol)?;
        if n > max || std::str::from_utf8(&self.0[..n]).is_err() {
            return Err(protocol());
        }
        self.take(n + 1)?;
        Ok(())
    }
    fn count(&mut self) -> Result<usize> {
        let v = self.take(2)?;
        let n = u16::from_be_bytes([v[0], v[1]]) as usize;
        if n > 64 {
            return Err(protocol());
        }
        Ok(n)
    }
    fn i32(&mut self) -> Result<i32> {
        Ok(i32::from_be_bytes(
            self.take(4)?.try_into().map_err(|_| protocol())?,
        ))
    }
    fn formats(&mut self) -> Result<()> {
        let n = self.count()?;
        for _ in 0..n {
            if !matches!(self.take(2)?, [0, 0] | [0, 1]) {
                return Err(protocol());
            }
        }
        Ok(())
    }
}

fn validate(frame: &[u8], startup: bool) -> Result<()> {
    let mut f = Fields(&frame[if startup { 4 } else { 5 }..]);
    if startup {
        let version = f.i32()?;
        if version == 80_877_102 {
            f.take(8)?;
        } else {
            if version >> 16 != 3 {
                return Err(protocol());
            }
            let mut count = 0;
            while f.0.first().is_some_and(|v| *v != 0) {
                count += 1;
                if count > 16 {
                    return Err(protocol());
                }
                f.string(128)?;
                f.string(512)?;
            }
            f.take(1)?;
        }
    } else {
        match frame[0] {
            b'Q' => f.string(16 * 1024)?,
            b'p' => f.string(512)?,
            b'P' => {
                f.string(128)?;
                f.string(16 * 1024)?;
                let n = f.count()?;
                f.take(n * 4)?;
            }
            b'B' => {
                f.string(128)?;
                f.string(128)?;
                f.formats()?;
                let n = f.count()?;
                for _ in 0..n {
                    let len = f.i32()?;
                    if len < -1 {
                        return Err(protocol());
                    }
                    if len >= 0 {
                        f.take(len as usize)?;
                    }
                }
                f.formats()?;
            }
            b'C' | b'D' => {
                if !matches!(f.take(1)?, b"S" | b"P") {
                    return Err(protocol());
                }
                f.string(128)?;
            }
            b'E' => {
                f.string(128)?;
                if f.i32()? < 0 {
                    return Err(protocol());
                }
            }
            b'H' | b'S' | b'X' => {}
            _ => return Err(protocol()),
        }
    }
    if !f.0.is_empty() {
        return Err(protocol());
    }
    Ok(())
}

pub async fn send<W: AsyncWrite + Unpin, M: Message>(writer: &mut W, message: M) -> Result<()> {
    let mut bytes = BytesMut::new();
    message
        .encode(&mut bytes)
        .map_err(|_| Error::new("execution_failed", "PG result encoding failed"))?;
    timeout(Duration::from_secs(10), writer.write_all(&bytes))
        .await
        .map_err(|_| Error::new("connection_closed", "PG client write timeout"))?
        .map_err(io_error)
}
pub async fn ready<W: AsyncWrite + Unpin>(writer: &mut W) -> Result<()> {
    send(writer, ReadyForQuery::new(TransactionStatus::Idle)).await
}
pub async fn error<W: AsyncWrite + Unpin>(
    writer: &mut W,
    error: &Error,
    fatal: bool,
) -> Result<()> {
    let code = match error.code.as_str() {
        "unauthorized" => "28P01",
        "database_unknown" => "3D000",
        "auth_unavailable" => "58000",
        "forbidden" | "not_found" => "42501",
        "resource_limit" => "54000",
        "connection_limit" => "53300",
        "unsupported" => "0A000",
        "indeterminate_datatype" => "42P18",
        "invalid_parameter" => "22023",
        "cancelled" | "timeout" => "57014",
        "protocol_violation" => "08P01",
        "statement_missing" => "26000",
        "statement_exists" => "42P05",
        "portal_missing" => "34000",
        "portal_exists" => "42P03",
        _ => "XX000",
    };
    send(
        writer,
        ErrorResponse::new(vec![
            (b'S', if fatal { "FATAL" } else { "ERROR" }.into()),
            (b'V', if fatal { "FATAL" } else { "ERROR" }.into()),
            (b'C', code.into()),
            (b'M', error.message.clone()),
        ]),
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::*;
    fn packet(tag: u8, body: &[u8]) -> BytesMut {
        let mut bytes = BytesMut::from(&[tag][..]);
        bytes.extend_from_slice(&((body.len() + 4) as i32).to_be_bytes());
        bytes.extend_from_slice(body);
        bytes
    }
    #[test]
    fn rejects_malformed_packets_before_upstream_decode() {
        for (tag, body) in [
            (b'P', &b"\0SELECT\0\0\x01"[..]),
            (b'B', &b"\0\0\0\0\0\x01\xff\xff\xff\xfe\0\0"[..]),
            (b'Q', &b"SELECT"[..]),
            (b'Q', &b"\xff\0"[..]),
            (b'X', &b"trailing"[..]),
            (b'E', &b"\0\xff\xff\xff\xff"[..]),
        ] {
            assert!(decode(packet(tag, body), false).is_err());
        }
    }
    #[test]
    fn every_truncation_is_rejected() {
        let bodies = [
            (b'P', &b"s\0select id from documents\0\0\x01\0\0\0\x14"[..]),
            (
                b'B',
                &b"p\0s\0\0\x01\0\x01\0\x01\0\0\0\x08\0\0\0\0\0\0\0\x01\0\x01\0\x01"[..],
            ),
        ];
        for (tag, body) in bodies {
            assert!(decode(packet(tag, body), false).is_ok());
            for n in 0..body.len() {
                assert!(decode(packet(tag, &body[..n]), false).is_err());
            }
        }
    }
    #[tokio::test]
    async fn refuses_oversized_header_without_reading_body() {
        let mut input = &b"Q\x7f\xff\xff\xff"[..];
        assert!(frame(&mut input, false).await.is_err());
    }
}
