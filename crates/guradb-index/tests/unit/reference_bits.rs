//! Finite source-bound diagnostics, not full-domain N1/N2 certification.
use std::collections::{BTreeMap, BTreeSet};

use crate::{prepare_bm25, prepare_exact, Bm25Config, ExactConfig, InputScope, Key, TextRow};
use crate::{VectorRow, VectorValue};

const INPUT: &str = include_str!("../fixtures/diagnostic_cases.tsv");
const BINDINGS: &str = include_str!("../fixtures/source_bindings.tsv");
const UNCOMPUTED: &str = include_str!("../fixtures/reference_gold.tsv");
const ORACLE_SHA: &str = include_str!("../fixtures/reference_oracle.sha256");
type Hit = (String, String, u64);

struct Row {
    key: Key<'static>,
    state: &'static str,
    payload: &'static str,
}

struct Case {
    id: &'static str,
    kind: &'static str,
    query: &'static str,
    allowed: Option<BTreeSet<&'static str>>,
    rows: Vec<Row>,
}

fn cases() -> Vec<Case> {
    let mut lines = INPUT.lines();
    assert_eq!(lines.next(), Some("fixed-bit-cases/1"));
    let mut result = Vec::new();
    let mut current: Option<Case> = None;
    for line in lines {
        let fields: Vec<_> = line.split('|').collect();
        match fields.as_slice() {
            ["case", id, kind, query, allowed] => {
                assert!(current.is_none(), "unclosed fixture case");
                assert!(matches!(*kind, "exact" | "bm25"));
                current = Some(Case {
                    id,
                    kind,
                    query,
                    allowed: if *allowed == "*" {
                        None
                    } else {
                        Some(allowed.split(',').filter(|id| !id.is_empty()).collect())
                    },
                    rows: Vec::new(),
                });
            }
            ["row", id, version, state, payload] => {
                current.as_mut().expect("row outside case").rows.push(Row {
                    key: Key { record_id: id, record_version: version },
                    state,
                    payload,
                });
            }
            ["end"] => {
                let case = current.take().expect("end outside case");
                assert!(case.rows.len() <= 100);
                let ids: BTreeSet<_> = case.rows.iter().map(|row| row.key.record_id).collect();
                assert_eq!(ids.len(), case.rows.len(), "duplicate fixture ID");
                result.push(case);
            }
            _ => panic!("unknown diagnostic fixture line: {line}"),
        }
    }
    assert!(current.is_none());
    let expected: Vec<_> = (1..=12).map(|i| format!("x{i:02}"))
        .chain((1..=12).map(|i| format!("b{i:02}"))).collect();
    assert_eq!(result.iter().map(|case| case.id).collect::<Vec<_>>(), expected);
    result
}

fn bytes(value: &str) -> Vec<u8> {
    assert_eq!(value.len() % 2, 0);
    assert!(value.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)));
    (0..value.len()).step_by(2)
        .map(|offset| u8::from_str_radix(&value[offset..offset + 2], 16).unwrap()).collect()
}

fn vector(value: &str) -> Vec<f64> {
    let values: Vec<_> = value.split(',').map(|bits| {
        assert_eq!(bits.len(), 16, "input requires fixed f64 bits");
        f64::from_bits(u64::from_str_radix(bits, 16).unwrap())
    }).collect();
    assert_eq!(values.len(), 3);
    values
}

fn tokens(value: &'static str) -> Vec<&'static str> {
    let mut result = Vec::new();
    if !value.is_empty() {
        for entry in value.split(',') {
            let (term, count) = entry.rsplit_once('=').expect("term=count fixture");
            let count: usize = count.parse().unwrap();
            assert!((1..=1024).contains(&count) && result.len() + count <= 1024);
            result.extend(std::iter::repeat_n(term, count));
        }
    }
    result
}

fn actual(case: &Case) -> Vec<Hit> {
    let keys: Vec<_> = case.rows.iter().map(|row| row.key).collect();
    let scope = InputScope {
        expected_source_set: case.id,
        actual_source_set: case.id,
        expected_keys: &keys,
    };
    if case.kind == "bm25" {
        let storage: Vec<_> = case.rows.iter().map(|row| {
            assert!(matches!(row.state, "T" | "N"));
            if row.state == "T" { tokens(row.payload) } else { Vec::new() }
        }).collect();
        let rows: Vec<_> = case.rows.iter().zip(&storage).map(|(row, words)| TextRow {
            key: row.key,
            tokens: if row.state == "N" { None } else { Some(words) },
        }).collect();
        let prepared = prepare_bm25(&scope, &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap();
        prepared.score_candidate(case.query, case.allowed.as_ref(), &mut || Ok(())).unwrap()
            .iter().map(|hit| (hit.key().record_id.to_owned(), hit.key().record_version.to_owned(), hit.score().to_bits()))
            .collect()
    } else {
        let storage: Vec<_> = case.rows.iter().map(|row| {
            assert!(matches!(row.state, "V" | "N"));
            if row.state == "V" { vector(row.payload) } else { Vec::new() }
        }).collect();
        let rows: Vec<_> = case.rows.iter().zip(&storage).map(|(row, values)| VectorRow {
            key: row.key,
            value: if row.state == "N" {
                VectorValue::Null { reason: row.payload }
            } else {
                VectorValue::Present(values)
            },
        }).collect();
        let prepared = prepare_exact(&scope, &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap();
        prepared.score_candidate(&vector(case.query), case.allowed.as_ref(), &mut || Ok(())).unwrap()
            .iter().map(|hit| (hit.key().record_id.to_owned(), hit.key().record_version.to_owned(), hit.score().to_bits()))
            .collect()
    }
}

fn gold(raw: &str) -> Vec<(String, Vec<Hit>)> {
    let mut lines = raw.lines();
    assert_eq!(lines.next(), Some("fixed-bit-gold/1"));
    assert_eq!(lines.next(), Some("status|COMPUTED"),
        "NOT_COMPUTED: obtain an authorized source-bound Python reference artifact; no skip/fallback");
    let mut metadata = BTreeMap::new();
    let mut runtime = BTreeMap::new();
    let mut result = Vec::new();
    let mut current: Option<(String, Vec<Hit>)> = None;
    let mut case_started = false;
    for line in lines {
        let fields: Vec<_> = line.split('|').collect();
        match fields.as_slice() {
            ["case", id] => {
                assert!(current.is_none());
                case_started = true;
                current = Some((id.to_string(), Vec::new()));
            }
            ["hit", id, version, bits] => {
                assert_eq!(bits.len(), 16);
                assert!(bits.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)));
                current.as_mut().expect("hit outside case").1.push((
                    id.to_string(), version.to_string(), u64::from_str_radix(bits, 16).unwrap()));
            }
            ["end"] => result.push(current.take().expect("end outside case")),
            ["runtime", name, value] => {
                let decoded = String::from_utf8(bytes(value)).expect("reference runtime UTF8");
                assert!(!case_started && !decoded.is_empty());
                assert!(runtime.insert(*name, *value).is_none());
            }
            [name, value] if matches!(*name, "source_bindings_hex" | "case_inputs_hex" | "oracle_sha256") => {
                assert!(!case_started && metadata.insert(*name, *value).is_none());
            }
            _ => panic!("invalid reference artifact line: {line}"),
        }
    }
    assert!(current.is_none());
    assert_eq!(metadata.len(), 3);
    assert_eq!(bytes(metadata["case_inputs_hex"]), INPUT.as_bytes());
    assert_eq!(bytes(metadata["source_bindings_hex"]), BINDINGS.as_bytes());
    assert_eq!(metadata["oracle_sha256"], ORACLE_SHA.trim());
    let required = BTreeSet::from([
        "implementation", "version", "cache_tag", "compiler", "system", "machine",
        "math_module", "mant_dig", "rounds",
    ]);
    assert_eq!(runtime.keys().copied().collect::<BTreeSet<_>>(), required,
        "reference must record its actual Python/runtime identity");
    result
}

#[test]
fn reference_bits_all_24_cases() {
    let artifact = match std::env::var("GURADB_INDEX_REFERENCE_GOLD") {
        Ok(path) => std::fs::read_to_string(path).expect("read explicit Python reference artifact"),
        Err(std::env::VarError::NotPresent) => UNCOMPUTED.to_owned(),
        Err(error) => panic!("invalid reference artifact environment: {error}"),
    };
    let cases = cases();
    let expected = gold(&artifact);
    assert_eq!(expected.len(), cases.len(), "missing/extra reference cases");
    for (case, (identity, expected_hits)) in cases.iter().zip(expected) {
        assert_eq!(case.id, identity, "reference case order/identity drift");
        let actual_hits = actual(case);
        assert_eq!(actual_hits.len(), expected_hits.len(), "{}: hit count drift", case.id);
        for (position, (actual, expected)) in actual_hits.iter().zip(&expected_hits).enumerate() {
            assert_eq!((&actual.0, &actual.1), (&expected.0, &expected.1),
                "{} row {}: ID/version full-order drift; actual={actual_hits:?}, expected={expected_hits:?}", case.id, position);
            assert_eq!(actual.2, expected.2,
                "{} row {} {}@{}: first bit difference actual={:016x} expected={:016x}",
                case.id, position, actual.0, actual.1, actual.2, expected.2);
        }
    }
}
