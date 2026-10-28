use std::collections::BTreeSet;

use crate::{prepare_bm25, tokenize, Bm25Config, InputScope, Key, ScoreError, TextRow};

fn key(id: &str) -> Key<'_> {
    Key { record_id: id, record_version: "v1" }
}

fn scope<'a>(keys: &'a [Key<'a>]) -> InputScope<'a> {
    InputScope {
        expected_source_set: "fixed-source-a+fixed-source-b",
        actual_source_set: "fixed-source-a+fixed-source-b",
        expected_keys: keys,
    }
}

#[test]
fn literal_fixed_separators_preserve_case_punctuation_and_duplicates() {
    let separators = [
        '\u{9}', '\u{a}', '\u{b}', '\u{c}', '\u{d}', ' ', '\u{85}', '\u{a0}',
        '\u{1680}', '\u{2000}', '\u{2001}', '\u{2002}', '\u{2003}', '\u{2004}',
        '\u{2005}', '\u{2006}', '\u{2007}', '\u{2008}', '\u{2009}', '\u{200a}',
        '\u{2028}', '\u{2029}', '\u{202f}', '\u{205f}', '\u{3000}',
    ];
    for separator in separators {
        let text = format!("{separator}权限{separator}缓存{separator}权限{separator}");
        assert_eq!(tokenize(&text).unwrap(), ["权限", "缓存", "权限"]);
    }
    assert_eq!(tokenize("A a a,b x\u{200b}y x\u{1c}y").unwrap(),
               ["A", "a", "a,b", "x\u{200b}y", "x\u{1c}y"]);
    assert_eq!(tokenize("\t \u{3000}").unwrap(), Vec::<&str>::new());
    assert_eq!(tokenize(&"词".repeat(129)), Err(ScoreError::InvalidTokens));
    assert_eq!(tokenize(&"a ".repeat(1025)), Err(ScoreError::InvalidTokens));
    assert_eq!(tokenize(&" ".repeat(4097)), Err(ScoreError::InvalidTokens));
}

#[test]
fn literal_statistics_include_null_and_count_document_frequency_once() {
    let keys = [key("a"), key("b"), key("null")];
    let rows = [
        TextRow { key: keys[0], tokens: Some(&["权限", "权限", "缓存"]) },
        TextRow { key: keys[1], tokens: Some(&["缓存"]) },
        TextRow { key: keys[2], tokens: None },
    ];
    let prepared = prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap();
    assert_eq!(prepared.document_count(), 3);
    assert_eq!(prepared.total_tokens(), 4);
    assert_eq!(prepared.document_frequency("权限"), 1);
    assert_eq!(prepared.document_frequency("缓存"), 2);
    assert_eq!(prepared.document_frequency("missing"), 0);
}

#[test]
fn full_eleven_rows_from_two_partitions_share_global_statistics_before_filter() {
    // Independent literal source membership: a0..a4 and b0..b5. No Parquet/provider claim.
    let ids = ["a0", "a1", "a2", "a3", "a4", "b0", "b1", "b2", "b3", "b4", "b5"];
    let keys: Vec<_> = ids.iter().map(|id| key(id)).collect();
    let rows: Vec<_> = keys.iter().enumerate().map(|(i, &key)| TextRow {
        key, tokens: Some(if i < 5 { &["权限"] } else { &["缓存"] }),
    }).collect();
    let prepared = prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap();
    assert_eq!((prepared.document_count(), prepared.total_tokens()), (11, 11));
    assert_eq!(prepared.document_frequency("权限"), 5);
    assert_eq!(prepared.document_frequency("缓存"), 6);
    let all = prepared.score_candidate("权限 缓存", None, &mut || Ok(())).unwrap();
    assert_eq!(all.iter().map(|hit| hit.key().record_id).collect::<Vec<_>>(), ids);
    let allowed = BTreeSet::from(["a3", "b4", "not-present"]);
    let filtered = prepared.score_candidate("权限 缓存", Some(&allowed), &mut || Ok(())).unwrap();
    assert_eq!(filtered.iter().map(|hit| hit.key()).collect::<Vec<_>>(), [keys[3], keys[9]]);
    for hit in filtered {
        let full = all.iter().find(|row| row.key() == hit.key()).unwrap();
        assert_eq!(hit.score().to_bits(), full.score().to_bits());
    }
}

#[test]
fn duplicate_query_terms_and_stable_ties_do_not_lose_identity_or_version() {
    let keys = [key("z"), key("a")];
    let rows = [TextRow { key: keys[0], tokens: Some(&["权限"]) },
                TextRow { key: keys[1], tokens: Some(&["权限"]) }];
    let prepared = prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap();
    let one = prepared.score_candidate("权限", None, &mut || Ok(())).unwrap();
    let twice = prepared.score_candidate("权限 权限", None, &mut || Ok(())).unwrap();
    assert_eq!(one.iter().map(|hit| hit.key()).collect::<Vec<_>>(), [keys[1], keys[0]]);
    for (single, repeated) in one.iter().zip(twice) {
        assert_eq!(repeated.score().to_bits(), (single.score() + single.score()).to_bits());
        assert_eq!(single.key(), repeated.key());
    }
    assert!(prepared.score_candidate("无匹配", None, &mut || Ok(())).unwrap().is_empty());
    assert!(prepared.score_candidate("权限", Some(&BTreeSet::new()), &mut || Ok(())).unwrap().is_empty());
}

#[test]
fn empty_corpus_and_all_null_keep_valid_empty_semantics() {
    let empty = prepare_bm25(&scope(&[]), &Bm25Config::fixed(6), &[], &mut || Ok(())).unwrap();
    assert!(empty.score_candidate("权限", None, &mut || Ok(())).unwrap().is_empty());
    assert_eq!(empty.score_candidate(" \t", None, &mut || Ok(())).unwrap_err(), ScoreError::InvalidTokens);
    let keys = [key("null"), key("empty")];
    let rows = [TextRow { key: keys[0], tokens: None }, TextRow { key: keys[1], tokens: Some(&[]) }];
    let all_empty = prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap();
    assert_eq!((all_empty.document_count(), all_empty.total_tokens()), (2, 0));
    assert!(all_empty.score_candidate("权限", None, &mut || Ok(())).unwrap().is_empty());
}

#[test]
fn complete_identity_set_rejects_missing_extra_wrong_version_and_duplicates() {
    let keys = [key("a"), key("b")];
    for actual in [vec![keys[0]], vec![keys[0], key("c")],
                   vec![keys[0], Key { record_id: "b", record_version: "wrong" }]] {
        let rows: Vec<_> = actual.iter().map(|&key| TextRow { key, tokens: None }).collect();
        assert_eq!(prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap_err(),
                   ScoreError::IdentityMismatch);
    }
    for duplicate in [keys[0], Key { record_id: "a", record_version: "other" }] {
        let rows = [TextRow { key: keys[0], tokens: None }, TextRow { key: duplicate, tokens: None }];
        assert_eq!(prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap_err(),
                   ScoreError::DuplicateIdentity);
    }
    let rows = [TextRow { key: keys[0], tokens: None }, TextRow { key: keys[1], tokens: None }];
    let mut wrong = scope(&keys);
    wrong.actual_source_set = "different";
    assert_eq!(prepare_bm25(&wrong, &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap_err(), ScoreError::ScopeMismatch);
    let duplicate_expected = [keys[0], keys[0]];
    assert_eq!(prepare_bm25(&scope(&duplicate_expected), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap_err(),
               ScoreError::DuplicateIdentity);
    let blank = [key("")];
    let rows = [TextRow { key: blank[0], tokens: None }];
    assert_eq!(prepare_bm25(&scope(&blank), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap_err(),
               ScoreError::IdentityMismatch);
}

#[test]
fn rejects_old_models_invalid_tokens_and_over_one_hundred_rows() {
    let mut config = Bm25Config::fixed(6);
    config.model_id = "bm25-global-v2";
    assert_eq!(prepare_bm25(&scope(&[]), &config, &[], &mut || Ok(())).unwrap_err(), ScoreError::InvalidConfiguration);
    config = Bm25Config::fixed(0);
    assert_eq!(prepare_bm25(&scope(&[]), &config, &[], &mut || Ok(())).unwrap_err(), ScoreError::InvalidConfiguration);
    config = Bm25Config::fixed(6);
    config.k1 = f64::NAN;
    assert_eq!(prepare_bm25(&scope(&[]), &config, &[], &mut || Ok(())).unwrap_err(), ScoreError::InvalidConfiguration);
    let keys = [key("a")];
    for tokens in [&[""][..], &["two words"][..]] {
        let rows = [TextRow { key: keys[0], tokens: Some(tokens) }];
        assert_eq!(prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap_err(), ScoreError::InvalidTokens);
    }
    let ids: Vec<_> = (0..101).map(|i| format!("r{i}")).collect();
    let keys: Vec<_> = ids.iter().map(|id| key(id)).collect();
    let rows: Vec<_> = keys.iter().map(|&key| TextRow { key, tokens: None }).collect();
    assert_eq!(prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap_err(), ScoreError::RowLimit);
    let hundred = prepare_bm25(&scope(&keys[..100]), &Bm25Config::fixed(6), &rows[..100], &mut || Ok(())).unwrap();
    assert_eq!(hundred.document_count(), 100);
}

#[test]
fn interruption_never_returns_a_partial_prepared_or_scored_result() {
    let keys = [key("a"), key("b")];
    let rows = [TextRow { key: keys[0], tokens: Some(&["权限"]) },
                TextRow { key: keys[1], tokens: Some(&["权限"]) }];
    let mut calls = 0;
    let failed = prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || {
        calls += 1;
        if calls == 3 { Err(ScoreError::Interrupted) } else { Ok(()) }
    });
    assert_eq!(failed.unwrap_err(), ScoreError::Interrupted);
    let prepared = prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(())).unwrap();
    let mut calls = 0;
    let failed = prepared.score_candidate("权限", None, &mut || {
        calls += 1;
        if calls == 4 { Err(ScoreError::Interrupted) } else { Ok(()) }
    });
    assert_eq!(failed.unwrap_err(), ScoreError::Interrupted);
}

#[test]
fn global_vocabulary_limit_cannot_be_evaded_by_splitting_documents() {
    let storage: Vec<Vec<String>> = (0..5).map(|row| {
        (0..1024).map(|term| format!("word-{row}-{term}")).collect()
    }).collect();
    let tokens: Vec<Vec<&str>> = storage.iter().map(|words| words.iter().map(String::as_str).collect()).collect();
    let keys = [key("a"), key("b"), key("c"), key("d"), key("e")];
    let rows: Vec<_> = keys.iter().zip(&tokens).map(|(&key, words)| TextRow {
        key, tokens: Some(words),
    }).collect();
    let full = prepare_bm25(&scope(&keys), &Bm25Config::fixed(6), &rows, &mut || Ok(()));
    assert_eq!(full.unwrap_err(), ScoreError::InvalidTokens);
    let boundary = prepare_bm25(&scope(&keys[..4]), &Bm25Config::fixed(6), &rows[..4], &mut || Ok(())).unwrap();
    assert_eq!(boundary.total_tokens(), 4096);
}
