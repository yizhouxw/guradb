use super::*;

#[test]
fn local_relocation_uses_components_and_never_basename() {
    let logical = path::logical_root("file:///home/writer/table").unwrap();
    assert_eq!(
        path::relocate(&logical, "file:///home/writer/table/data/x.parquet").unwrap(),
        "data/x.parquet"
    );
    assert_eq!(
        path::relocate(&logical, "/home/writer/table/metadata/x.avro").unwrap(),
        "metadata/x.avro"
    );
    for reference in [
        "file:///home/writer/table2/data/x.parquet",
        "file:///elsewhere/x.parquet",
        "s3://bucket/table/x",
        "file://localhost/home/writer/table/x",
        "file:///home/writer/table/a/../x",
        "file:///home/writer/table//x",
        "file:///home/writer/table/%2e%2e/x",
        "file:///home/writer/table/x?y",
        "file:///home/writer/table/x#y",
        "data/x.parquet",
    ] {
        assert!(
            path::relocate(&logical, reference).is_err(),
            "accepted {reference}"
        );
    }
    for relative in [
        "/x", "../x", "a/./x", "a//x", "a/", "", "a\nb", "a\\b", "a:b",
    ] {
        assert!(path::relative(relative).is_err(), "accepted {relative}");
    }
    assert!(path::relative(&["x"; 17].join("/")).is_err());
    assert!(path::relative(&"x".repeat(256)).is_err());
}

#[test]
fn metadata_is_one_fixed_schema_spec_and_exact_snapshot() {
    let mut value = json!({
        "format-version":2,"table-uuid":"12345678-1234-1234-1234-123456789abc",
        "location":"file:///table","current-schema-id":0,
        "schemas":[{"type":"struct","schema-id":0,"fields":[
            {"id":1,"name":"n","required":false,"type":"long"},
            {"id":2,"name":"t","required":true,"type":"string"},
            {"id":3,"name":"b","required":false,"type":"boolean"}
        ]}],"partition-specs":[{"spec-id":0,"fields":[]}],"default-spec-id":0,
        "sort-orders":[{"order-id":0,"fields":[]}],"default-sort-order-id":0,
        "current-snapshot-id":22,"snapshots":[
            {"snapshot-id":11,"schema-id":0,"manifest-list":"file:///table/metadata/a.avro"},
            {"snapshot-id":22,"schema-id":0,"manifest-list":"file:///table/metadata/b.avro"}
        ]
    });
    let parse = |value: &Value| metadata::parse(&serde_json::to_vec(value).unwrap(), 11);
    let selected = parse(&value).unwrap();
    assert_eq!(selected.manifest_list, "metadata/a.avro");
    assert_eq!(selected.fields.len(), 3);
    value["current-schema-id"] = json!(1);
    assert!(parse(&value).is_err());
    value["current-schema-id"] = json!(0);
    value["schemas"][0]["fields"][1]["id"] = json!(1);
    assert!(parse(&value).is_err());
    value["schemas"][0]["fields"][1]["id"] = json!(2);
    value["schemas"][0]["fields"][0]["type"] = json!("int");
    assert!(parse(&value).is_err());
    value["schemas"][0]["fields"][0]["type"] = json!("long");
    value["partition-specs"][0]["fields"] = json!([{}]);
    assert!(parse(&value).is_err());
    value["partition-specs"][0]["fields"] = json!([]);
    let second = value["schemas"][0].clone();
    value["schemas"].as_array_mut().unwrap().push(second);
    assert!(parse(&value).is_err());
}

#[test]
fn readset_digest_is_root_independent_and_binds_every_relative_file() {
    let meta = metadata::Metadata {
        uuid: "12345678-1234-1234-1234-123456789abc".into(),
        schema_id: 0,
        fields: Vec::new(),
        logical_root: "/ignored".into(),
        manifest_list: "m.avro".into(),
        snapshot: 11,
    };
    let set = Readset {
        root: path::Root::open(std::path::Path::new("/usr")).unwrap(),
        files: BTreeMap::from([
            (
                "b".into(),
                Captured {
                    sha: "bb".into(),
                    limit: 1,
                },
            ),
            (
                "a".into(),
                Captured {
                    sha: "aa".into(),
                    limit: 2,
                },
            ),
        ]),
        chain_bytes: 0,
    };
    let bytes =
        b"guradb-iceberg-readset-v1\n12345678-1234-1234-1234-123456789abc\n11\n0\na\0aa\nb\0bb\n";
    assert_eq!(set.pin(&meta), hash(bytes));
}

#[test]
fn two_data_source_identity_is_ordered_domain_separated_and_single_unchanged() {
    let files = vec![
        SourceFile {
            path: "data/a.parquet".into(),
            sha256: "a".repeat(64),
            size_bytes: 5,
            record_count: 2,
        },
        SourceFile {
            path: "data/b.parquet".into(),
            sha256: "b".repeat(64),
            size_bytes: 7,
            record_count: 3,
        },
    ];
    let preimage = format!(
        "guradb-iceberg-data-files-v1\ntable-uuid\ndata/a.parquet\0{}\ndata/b.parquet\0{}\n",
        "a".repeat(64),
        "b".repeat(64)
    );
    assert_eq!(
        source_identity("table-uuid", &files).unwrap(),
        hash(preimage.as_bytes())
    );
    assert_eq!(
        source_identity("table-uuid", &files[..1]).unwrap(),
        "a".repeat(64)
    );
    assert!(source_identity("table-uuid", &[]).is_err());
    let reversed = vec![
        SourceFile {
            path: "b".into(),
            sha256: "b".repeat(64),
            size_bytes: 1,
            record_count: 1,
        },
        SourceFile {
            path: "a".into(),
            sha256: "a".repeat(64),
            size_bytes: 1,
            record_count: 1,
        },
    ];
    assert!(source_identity("table-uuid", &reversed).is_err());
}
