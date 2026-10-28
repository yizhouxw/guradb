use std::collections::BTreeSet;

use crate::{prepare_exact, ExactConfig, InputScope, Key, ScoreError, VectorRow, VectorValue};

fn key(id: &str) -> Key<'_> {
    Key { record_id: id, record_version: "v2" }
}

fn scope<'a>(keys: &'a [Key<'a>]) -> InputScope<'a> {
    InputScope {
        expected_source_set: "fixed-source-a+fixed-source-b",
        actual_source_set: "fixed-source-a+fixed-source-b",
        expected_keys: keys,
    }
}

#[test]
fn integer_distance_and_explicit_null_mask_preserve_full_source_coverage() {
    let keys = [key("z"), key("a"), key("null"), key("zero")];
    let rows = [
        VectorRow { key: keys[0], value: VectorValue::Present(&[1.0, 2.0, 2.0]) },
        VectorRow { key: keys[1], value: VectorValue::Present(&[-1.0, -2.0, -2.0]) },
        VectorRow { key: keys[2], value: VectorValue::Null { reason: "missing-modality" } },
        VectorRow { key: keys[3], value: VectorValue::Present(&[0.0, 0.0, 0.0]) },
    ];
    let prepared = prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap();
    assert_eq!((prepared.source_count(), prepared.vector_count()), (4, 3));
    let scores = prepared.score_candidate(&[0.0; 3], None, &mut || Ok(())).unwrap();
    assert_eq!(scores.iter().map(|hit| hit.key()).collect::<Vec<_>>(), [keys[3], keys[1], keys[0]]);
    assert_eq!(scores.iter().map(|hit| hit.score()).collect::<Vec<_>>(), [0.0, 9.0, 9.0]);
    let allowed = BTreeSet::from(["z", "null", "not-present"]);
    let filtered = prepared.score_candidate(&[0.0; 3], Some(&allowed), &mut || Ok(())).unwrap();
    assert_eq!(filtered, [scores[2]]);
    assert!(prepared.score_candidate(&[0.0; 3], Some(&BTreeSet::new()), &mut || Ok(())).unwrap().is_empty());
    // NULL must not disappear from the complete source identity input.
    assert_eq!(prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows[..2], &mut || Ok(())).unwrap_err(),
               ScoreError::IdentityMismatch);
}

#[test]
fn retained_low_terms_and_near_ties_have_literal_binary64_expectations() {
    let keys = [key("a"), key("z"), key("sum-a"), key("sum-b"), key("sum-c")];
    let rows = [
        // 2^-26 squared is exactly one ULP at 1.0: no epsilon tie collapse.
        VectorRow { key: keys[0], value: VectorValue::Present(&[1.0, 1.0 / 67108864.0, 0.0]) },
        VectorRow { key: keys[1], value: VectorValue::Present(&[1.0, 0.0, 0.0]) },
        VectorRow { key: keys[2], value: VectorValue::Present(&[1e8, 1.0, 1.0]) },
        VectorRow { key: keys[3], value: VectorValue::Present(&[1.0, 1e8, 1.0]) },
        VectorRow { key: keys[4], value: VectorValue::Present(&[1.0, 1.0, 1e8]) },
    ];
    let prepared = prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap();
    let hits = prepared.score_candidate(&[0.0; 3], None, &mut || Ok(())).unwrap();
    assert_eq!(hits.iter().map(|hit| hit.key()).collect::<Vec<_>>(),
               [keys[1], keys[0], keys[2], keys[3], keys[4]]);
    assert_eq!(hits[0].score().to_bits(), 1.0_f64.to_bits());
    assert_eq!(hits[1].score().to_bits(), 1.0_f64.to_bits() + 1);
    for hit in &hits[2..] {
        assert_eq!(hit.score().to_bits(), 10000000000000002.0_f64.to_bits());
    }
    // These hand-derived cases do not certify the entire Python fsum domain.
}

#[test]
fn finite_component_bound_is_inclusive_and_invalid_values_fail_before_filtering() {
    let keys = [key("a")];
    let rows = [VectorRow { key: keys[0], value: VectorValue::Present(&[1e150, -1e150, 0.0]) }];
    let prepared = prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap();
    let scores = prepared.score_candidate(&[-1e150, 1e150, 0.0], None, &mut || Ok(())).unwrap();
    assert!(scores[0].score().is_finite() && scores[0].score() > 0.0);
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, 1.1e150, -1.1e150] {
        let vector = [bad, 0.0, 0.0];
        let invalid = [VectorRow { key: keys[0], value: VectorValue::Present(&vector) }];
        assert_eq!(prepare_exact(&scope(&keys), &ExactConfig::fixed(), &invalid, &mut || Ok(())).unwrap_err(),
                   ScoreError::InvalidVector);
        assert_eq!(prepared.score_candidate(&vector, Some(&BTreeSet::new()), &mut || Ok(())).unwrap_err(),
                   ScoreError::InvalidVector);
    }
    for vector in [&[][..], &[1.0, 2.0][..], &[1.0, 2.0, 3.0, 4.0][..]] {
        let invalid = [VectorRow { key: keys[0], value: VectorValue::Present(vector) }];
        assert_eq!(prepare_exact(&scope(&keys), &ExactConfig::fixed(), &invalid, &mut || Ok(())).unwrap_err(),
                   ScoreError::InvalidVector);
        assert_eq!(prepared.score_candidate(vector, None, &mut || Ok(())).unwrap_err(), ScoreError::InvalidVector);
    }
}

#[test]
fn null_reason_and_model_configuration_are_not_silently_ignored() {
    let keys = [key("null")];
    let long = "x".repeat(129);
    for reason in ["", long.as_str()] {
        let rows = [VectorRow { key: keys[0], value: VectorValue::Null { reason } }];
        assert_eq!(prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap_err(),
                   ScoreError::InvalidVector);
    }
    let mut config = ExactConfig::fixed();
    config.normalization = "unit";
    assert_eq!(prepare_exact(&scope(&[]), &config, &[], &mut || Ok(())).unwrap_err(), ScoreError::InvalidConfiguration);
    config = ExactConfig::fixed();
    config.distance_sum = "left-fold";
    assert_eq!(prepare_exact(&scope(&[]), &config, &[], &mut || Ok(())).unwrap_err(), ScoreError::InvalidConfiguration);
    config = ExactConfig::fixed();
    config.model_version = "2";
    assert_eq!(prepare_exact(&scope(&[]), &config, &[], &mut || Ok(())).unwrap_err(), ScoreError::InvalidConfiguration);
}

#[test]
fn zero_signed_zero_and_underflow_are_numeric_ties_not_nulls() {
    let keys = [key("z"), key("b"), key("a")];
    let rows = [
        VectorRow { key: keys[0], value: VectorValue::Present(&[-0.0, 0.0, -0.0]) },
        VectorRow { key: keys[1], value: VectorValue::Present(&[1e-200, 0.0, 0.0]) },
        VectorRow { key: keys[2], value: VectorValue::Present(&[0.0, 0.0, 0.0]) },
    ];
    let prepared = prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap();
    let scores = prepared.score_candidate(&[0.0; 3], None, &mut || Ok(())).unwrap();
    assert_eq!(scores.iter().map(|hit| hit.key()).collect::<Vec<_>>(), [keys[2], keys[1], keys[0]]);
    assert!(scores.iter().all(|hit| hit.score() == 0.0));
}

#[test]
fn empty_and_all_null_inputs_still_validate_query_and_checkpoint() {
    let empty = prepare_exact(&scope(&[]), &ExactConfig::fixed(), &[], &mut || Ok(())).unwrap();
    assert!(empty.score_candidate(&[0.0; 3], None, &mut || Ok(())).unwrap().is_empty());
    assert_eq!(empty.score_candidate(&[f64::NAN; 3], None, &mut || Ok(())).unwrap_err(), ScoreError::InvalidVector);
    let keys = [key("null")];
    let rows = [VectorRow { key: keys[0], value: VectorValue::Null { reason: "not-provided" } }];
    let prepared = prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap();
    assert_eq!((prepared.source_count(), prepared.vector_count()), (1, 0));
    assert!(prepared.score_candidate(&[0.0; 3], None, &mut || Ok(())).unwrap().is_empty());
    assert_eq!(prepared.score_candidate(&[0.0; 3], None, &mut || Err(ScoreError::Interrupted)).unwrap_err(),
               ScoreError::Interrupted);
}

#[test]
fn duplicate_ids_wrong_versions_and_wrong_source_set_reject_even_for_nulls() {
    let keys = [key("a"), key("b")];
    let rows = [
        VectorRow { key: keys[0], value: VectorValue::Null { reason: "absent" } },
        VectorRow { key: Key { record_id: "a", record_version: "other" },
                    value: VectorValue::Null { reason: "absent" } },
    ];
    assert_eq!(prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap_err(),
               ScoreError::DuplicateIdentity);
    let rows = [VectorRow { key: Key { record_id: "a", record_version: "wrong" },
                           value: VectorValue::Null { reason: "absent" } }];
    assert_eq!(prepare_exact(&scope(&keys[..1]), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap_err(),
               ScoreError::IdentityMismatch);
    let mut wrong = scope(&[]);
    wrong.actual_source_set = "different";
    assert_eq!(prepare_exact(&wrong, &ExactConfig::fixed(), &[], &mut || Ok(())).unwrap_err(), ScoreError::ScopeMismatch);
}

#[test]
fn interruption_before_final_output_drops_all_partial_scores() {
    let keys = [key("a"), key("b")];
    let rows = [VectorRow { key: keys[0], value: VectorValue::Present(&[0.0; 3]) },
                VectorRow { key: keys[1], value: VectorValue::Present(&[1.0; 3]) }];
    let prepared = prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(())).unwrap();
    let mut calls = 0;
    let failed = prepared.score_candidate(&[0.0; 3], None, &mut || {
        calls += 1;
        if calls == 4 { Err(ScoreError::Interrupted) } else { Ok(()) }
    });
    assert_eq!(failed.unwrap_err(), ScoreError::Interrupted);
    let mut calls = 0;
    assert_eq!(prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || {
        calls += 1;
        if calls == 3 { Err(ScoreError::Interrupted) } else { Ok(()) }
    }).unwrap_err(), ScoreError::Interrupted);
}

#[test]
fn scored_value_guard_rejects_nonfinite_or_negative_and_keeps_numeric_zero_ties() {
    use crate::score::{order, ScoredId};
    for invalid in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -1.0] {
        assert_eq!(ScoredId::checked(key("a"), invalid), Err(ScoreError::InvalidScore));
    }
    let mut scores = [ScoredId::checked(key("z"), -0.0).unwrap(),
                      ScoredId::checked(key("a"), 0.0).unwrap()];
    order(&mut scores, true);
    assert_eq!(scores[0].key().record_id, "a");
}

#[test]
fn null_rows_count_toward_the_full_one_hundred_row_limit() {
    let ids: Vec<_> = (0..101).map(|i| format!("r{i}")).collect();
    let keys: Vec<_> = ids.iter().map(|id| key(id)).collect();
    let rows: Vec<_> = keys.iter().map(|&key| VectorRow {
        key, value: VectorValue::Null { reason: "not-provided" },
    }).collect();
    let full = prepare_exact(&scope(&keys), &ExactConfig::fixed(), &rows, &mut || Ok(()));
    assert_eq!(full.unwrap_err(), ScoreError::RowLimit);
    let boundary = prepare_exact(&scope(&keys[..100]), &ExactConfig::fixed(), &rows[..100], &mut || Ok(())).unwrap();
    assert_eq!((boundary.source_count(), boundary.vector_count()), (100, 0));
}
