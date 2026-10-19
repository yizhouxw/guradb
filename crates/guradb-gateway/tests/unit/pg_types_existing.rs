use super::*;
#[test]
fn integers_keep_full_width_and_check_lengths() {
    assert_eq!(
        parameter(Some(&i64::MIN.to_be_bytes()), 20, true).unwrap(),
        json!({"type":"int8", "value":"-9223372036854775808"})
    );
    assert!(parameter(Some(&[0; 7]), 20, true).is_err());
    assert!(parameter(Some(b"32768"), 21, false).is_err());
    assert!(parameter(Some(&[2]), 16, true).is_err());
    assert!(parameter(Some(b"x\0y"), 25, true).is_err());
    assert_eq!(parameter(None, 20, true).unwrap(), Value::Null);
}

#[test]
fn oids_formats_text_binary_and_row_metadata() {
    for (id, expected) in [
        (0, None),
        (20, Some("int8")),
        (21, Some("int8")),
        (23, Some("int8")),
        (25, Some("text")),
        (1043, Some("text")),
        (16, Some("bool")),
    ] {
        assert_eq!(kind(id).unwrap().as_deref(), expected);
    }
    assert!(kind(999).is_err());
    assert_eq!(formats(&[], 3).unwrap(), [0, 0, 0]);
    assert_eq!(formats(&[1], 3).unwrap(), [1, 1, 1]);
    assert_eq!(formats(&[0, 1], 2).unwrap(), [0, 1]);
    assert!(formats(&[0, 0], 3).is_err());
    for (raw, id, binary, expected) in [
        (vec![0, 2], 21, true, json!({"type":"int8","value":"2"})),
        (
            2_i32.to_be_bytes().to_vec(),
            23,
            true,
            json!({"type":"int8","value":"2"}),
        ),
        (
            b" 2 ".to_vec(),
            20,
            false,
            json!({"type":"int8","value":"2"}),
        ),
        (b"true".to_vec(), 16, false, json!(true)),
        (b"false".to_vec(), 16, false, json!(false)),
        (vec![1], 16, true, json!(true)),
        (vec![0], 16, true, json!(false)),
        ("数据库".as_bytes().to_vec(), 25, true, json!("数据库")),
    ] {
        assert_eq!(parameter(Some(&raw), id, binary).unwrap(), expected);
    }
    for (raw, id, binary) in [
        (vec![255], 25, false),
        (vec![255], 20, false),
        (b"not-int".to_vec(), 20, false),
        (b"2147483648".to_vec(), 23, false),
        (b"invalid".to_vec(), 16, false),
        (vec![255], 16, false),
    ] {
        assert!(parameter(Some(&raw), id, binary).is_err());
    }
    let columns = vec![
        Column {
            name: "id".into(),
            r#type: "int8".into(),
        },
        Column {
            name: "title".into(),
            r#type: "text".into(),
        },
        Column {
            name: "active".into(),
            r#type: "bool".into(),
        },
    ];
    let described = description(&columns, &[0, 1, 0]);
    assert_eq!(described.fields.len(), 3);
    for formats in [vec![0, 0, 0], vec![1, 1, 1]] {
        assert!(row(
            &columns,
            &[json!("9223372036854775807"), json!("数据库"), json!(true)],
            &formats
        )
        .is_ok());
        assert!(row(
            &columns,
            &[Value::Null, Value::Null, json!(false)],
            &formats
        )
        .is_ok());
    }
    for values in [
        [json!("invalid"), Value::Null, Value::Null],
        [json!(false), Value::Null, Value::Null],
        [Value::Null, json!("nul\0byte"), Value::Null],
        [Value::Null, Value::Null, json!("true")],
    ] {
        assert!(row(&columns, &values, &[1, 0, 0]).is_err());
    }
}
