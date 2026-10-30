use super::*;

fn fixture(phase: &str) -> Catalog {
    let columns = vec![managed_input::Column {
        name: "doc_id".into(),
        kind: "Utf8".into(),
        nullable: false,
    }];
    let mut schema = b"guradb-schema-v1\n".to_vec();
    schema.extend(serde_json::to_vec(&columns).unwrap());
    let schema_id = hash(&schema);
    let dataset_id = "b".repeat(64);
    let id = "a".repeat(64);
    let record = Record {
        source_sha256: None,
        features: None,
        id: id.clone(),
        request_id: "op-A".into(),
        published: false,
    };
    let input = hash(format!("guradb-import-v1\ndemo\n{id}\nnone\n").as_bytes());
    let revision =
        hash(format!("guradb-revision-v1\n{dataset_id}\n{schema_id}\n1\n{id}\n").as_bytes());
    let operation = Operation {
        id: "op-A".into(),
        input_sha256: input,
        phase: phase.into(),
        parent: None,
        generation: 1,
        revision_id: revision.clone(),
        record: record.clone(),
        rows: 1,
        assets: 1,
    };
    let mut managed = Managed {
        name: "demo".into(),
        dataset_id,
        schema_id,
        columns,
        mode: 1,
        revisions: vec![],
        operations: vec![operation],
    };
    let mut views = vec![];
    let mut current = None;
    if phase == "ready" {
        views.push(record.clone());
    }
    if phase == "committed" {
        let mut published = record;
        published.published = true;
        views.push(published);
        current = Some(id.clone());
        managed.revisions.push(Revision {
            id: revision,
            generation: 1,
            view_id: id,
            operation_id: "op-A".into(),
        });
    }
    Catalog {
        format_version: 3,
        current,
        views,
        managed: Some(managed),
    }
}
#[test]
fn durable_model_rejects_rebound_identity_parent_and_ready_record() {
    for phase in ["capturing", "ready", "committed", "failed"] {
        let c = fixture(phase);
        assert!(c.managed.as_ref().unwrap().valid(&c));
    }
    let mut c = fixture("capturing");
    c.managed.as_mut().unwrap().operations[0].input_sha256 = "c".repeat(64);
    assert!(!c.managed.as_ref().unwrap().valid(&c));
    let mut c = fixture("capturing");
    c.managed.as_mut().unwrap().operations[0].parent = Some("a".repeat(64));
    assert!(!c.managed.as_ref().unwrap().valid(&c));
    let mut c = fixture("ready");
    c.views[0].request_id = "other".into();
    assert!(!c.managed.as_ref().unwrap().valid(&c));
    let mut c = fixture("committed");
    c.managed.as_mut().unwrap().revisions[0].generation = 2;
    assert!(!c.managed.as_ref().unwrap().valid(&c));
}
#[test]
fn eight_terminal_operations_fit_but_ninth_is_not_admitted_model() {
    let mut c = fixture("committed");
    for i in 0..7 {
        let d = c.managed.as_mut().unwrap();
        let mut op = d.operations[0].clone();
        op.id = format!("failed-{i}");
        op.record.request_id = op.id.clone();
        op.phase = "failed".into();
        d.operations.push(op);
    }
    assert!(c.managed.as_ref().unwrap().valid(&c));
    let d = c.managed.as_mut().unwrap();
    let mut ninth = d.operations[7].clone();
    ninth.id = "ninth".into();
    ninth.record.request_id = ninth.id.clone();
    d.operations.push(ninth);
    assert!(!c.managed.as_ref().unwrap().valid(&c));
}

#[test]
fn final_description_is_reserved_before_admitting_an_input() {
    let mut found = false;
    for width in 1..=32 {
        let mut c = fixture("capturing");
        let d = c.managed.as_mut().unwrap();
        d.mode = 2;
        d.columns = (0..width)
            .map(|i| managed_input::Column {
                name: format!("{}{:02}", "x".repeat(254), i),
                kind: "Utf8".into(),
                nullable: true,
            })
            .collect();
        let mut schema = b"guradb-schema-v1\n".to_vec();
        schema.extend(serde_json::to_vec(&d.columns).unwrap());
        d.schema_id = hash(&schema);
        let space:crate::features::Space=serde_json::from_value(json!({"id":"space","dimensions":1,"dtype":"f64","metric":"cosine","normalization":"l2-scaled-f64-v1","origin":"external-declared","model_id":"m".repeat(256),"model_revision":"r".repeat(256),"preprocessing_id":"p".repeat(256),"license":"l".repeat(256)})).unwrap();
        let record = &mut d.operations[0].record;
        record.source_sha256 = Some("a".repeat(64));
        record.features = Some(state::BoundFeatures {
            sha256: "c".repeat(64),
            space,
        });
        record.id = state::identity(&"a".repeat(64), &"c".repeat(64));
        d.operations[0].input_sha256 = hash(
            format!(
                "guradb-import-v1\ndemo\n{}\n{}\n",
                "a".repeat(64),
                "c".repeat(64)
            )
            .as_bytes(),
        );
        d.operations[0].revision_id = hash(
            format!(
                "guradb-revision-v1\n{}\n{}\n1\n{}\n",
                d.dataset_id, d.schema_id, d.operations[0].record.id
            )
            .as_bytes(),
        );
        for i in 0..5 {
            let mut op = d.operations[0].clone();
            op.id = format!("failed-{i}");
            op.record.request_id = op.id.clone();
            op.phase = "failed".into();
            d.operations.insert(0, op);
        }
        if serde_json::to_vec(&c).unwrap().len() <= 16384 && reserve(&c).is_err() {
            assert!(c.managed.as_ref().unwrap().valid(&c));
            found = true;
            break;
        }
    }
    assert!(
        found,
        "a legal capturing catalog fits while its complete publication does not"
    );
}

#[test]
fn record_space_is_immutable_but_publication_flag_may_change() {
    let a:Record=serde_json::from_value(json!({"source_sha256":"a".repeat(64),"features":{"sha256":"c".repeat(64),"space":{"id":"space","dimensions":1,"dtype":"f64","metric":"cosine","normalization":"l2-scaled-f64-v1","origin":"external-declared","model_id":"model","model_revision":"revision","preprocessing_id":"preprocess","license":"original"}},"id":state::identity(&"a".repeat(64),&"c".repeat(64)),"request_id":"op-A","published":false})).unwrap();
    let mut published = a.clone();
    published.published = true;
    assert!(same_record(&a, &published));
    let mut changed = serde_json::to_value(&a).unwrap();
    changed["features"]["space"]["license"] = json!("changed");
    let changed: Record = serde_json::from_value(changed).unwrap();
    assert!(!same_record(&changed, &published));
}
