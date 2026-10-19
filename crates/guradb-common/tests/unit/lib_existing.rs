use super::*;
#[test]
fn key_vectors_are_typed_and_unambiguous() {
    assert_eq!(
        hex::encode(encode_key(&[("text", b"ab")]).unwrap()),
        "010000000101000000026162"
    );
    assert_ne!(
        encode_key(&[("text", b"a|b"), ("text", b"c")]).unwrap(),
        encode_key(&[("text", b"a"), ("text", b"b|c")]).unwrap()
    );
    assert_ne!(
        encode_key(&[("text", b"1")]).unwrap(),
        encode_key(&[("int8", &1_i64.to_be_bytes())]).unwrap()
    );
    assert!(encode_key(&[("int8", b"1")]).is_err());
}
