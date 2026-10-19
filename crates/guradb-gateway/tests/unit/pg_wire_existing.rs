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

#[tokio::test]
async fn frames_and_error_responses_are_bounded() {
    use pgwire::messages::simplequery::Query;
    use tokio::io::AsyncWriteExt;
    let (mut write, mut read) = tokio::io::duplex(8192);
    send(&mut write, Query::new("SELECT id FROM documents".into()))
        .await
        .unwrap();
    let bytes = frame(&mut read, false).await.unwrap();
    assert!(decode(bytes, false).is_ok());
    for code in [
        "unauthorized",
        "database_unknown",
        "auth_unavailable",
        "forbidden",
        "not_found",
        "resource_limit",
        "connection_limit",
        "unsupported",
        "indeterminate_datatype",
        "invalid_parameter",
        "cancelled",
        "timeout",
        "protocol_violation",
        "statement_missing",
        "statement_exists",
        "portal_missing",
        "portal_exists",
        "execution_failed",
    ] {
        let mut bytes = Vec::new();
        error(&mut bytes, &Error::new(code, "message"), false)
            .await
            .unwrap();
        assert_eq!(bytes[0], b'E');
    }
    let mut bytes = Vec::new();
    error(&mut bytes, &Error::new("unsupported", "message"), true)
        .await
        .unwrap();
    assert!(bytes.windows(5).any(|part| part == b"FATAL"));
    let mut invalid: &[u8] = b"Q\0\0\0\x03";
    assert!(frame(&mut invalid, false).await.is_err());
    let mut closed: &[u8] = b"";
    assert_eq!(
        frame(&mut closed, false).await.unwrap_err().code,
        "connection_closed"
    );
    let mut bytes: &[u8] = b"\0\0\0\x09\0\x03\0\0\0";
    assert!(decode(frame(&mut bytes, true).await.unwrap(), true).is_ok());
    let (mut write, read) = tokio::io::duplex(1);
    drop(read);
    assert_eq!(
        ready(&mut write).await.unwrap_err().code,
        "connection_closed"
    );
    let _ = write.shutdown().await;
}

#[test]
fn complete_message_validators_reject_malformed_fields() {
    use bytes::Bytes;
    use pgwire::messages::extendedquery::Bind;
    let mut bytes = BytesMut::new();
    Bind::new(
        None,
        None,
        vec![0],
        vec![Some(Bytes::from_static(b"x"))],
        vec![0],
    )
    .encode(&mut bytes)
    .unwrap();
    assert!(validate(&bytes, false).is_ok());
    let mut f = Fields(&[0, 65]);
    assert!(f.count().is_err());
    let mut f = Fields(&[0, 1, 0, 2]);
    assert!(f.formats().is_err());
    assert!(validate(&[0, 0, 0, 9, 0, 2, 0, 0, 0], true).is_err());
    let mut startup = vec![0, 0, 0, 0, 0, 3, 0, 0];
    for _ in 0..17 {
        startup.extend_from_slice(b"k\0v\0");
    }
    startup.push(0);
    assert!(validate(&startup, true).is_err());
    for bytes in [
        b"D\0\0\0\x06X\0".as_slice(),
        b"C\0\0\0\x06S\0",
        b"D\0\0\0\x06P\0",
        b"E\0\0\0\x09\0\xff\xff\xff\xff",
        b"?\0\0\0\x04",
    ] {
        let outcome = validate(bytes, false);
        assert_eq!(
            outcome.is_ok(),
            bytes[0] == b'C' || bytes[0] == b'D' && bytes[5] == b'P'
        );
    }
}

#[tokio::test(start_paused = true)]
async fn idle_read_write_timeouts_and_encoding_failure() {
    let (mut writer, mut reader) = tokio::io::duplex(1);
    assert_eq!(frame(&mut reader, false).await.unwrap_err().code, "timeout");
    assert_eq!(
        ready(&mut writer).await.unwrap_err().code,
        "connection_closed"
    );
    let mut output = Vec::new();
    struct BrokenCodec;
    impl Message for BrokenCodec {
        fn message_length(&self) -> usize {
            4
        }
        fn encode_body(&self, _: &mut BytesMut) -> pgwire::error::PgWireResult<()> {
            Err(pgwire::error::PgWireError::InvalidMessageType(0))
        }
        fn decode_body(
            _: &mut BytesMut,
            _: usize,
            _: &pgwire::messages::DecodeContext,
        ) -> pgwire::error::PgWireResult<Self> {
            Err(pgwire::error::PgWireError::InvalidMessageType(0))
        }
    }
    let result = send(&mut output, BrokenCodec).await;
    assert_eq!(result.unwrap_err().code, "execution_failed");
}
