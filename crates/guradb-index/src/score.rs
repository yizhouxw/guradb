use std::cmp::Ordering;
use std::collections::BTreeMap;

pub(crate) const MAX_ROWS: usize = 100;

/// Borrowed fixed identity; never inferred from a physical row position.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Key<'a> {
    pub record_id: &'a str,
    pub record_version: &'a str,
}

/// Caller-owned context references, not a source-set or authorization issuer.
pub struct InputScope<'a> {
    pub expected_source_set: &'a str,
    pub actual_source_set: &'a str,
    pub expected_keys: &'a [Key<'a>],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScoreError {
    ScopeMismatch,
    IdentityMismatch,
    DuplicateIdentity,
    RowLimit,
    InvalidConfiguration,
    InvalidTokens,
    InvalidVector,
    InvalidScore,
    Interrupted,
}

/// Private library result model, not the public Candidate/locator contract.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ScoredId<'a> {
    key: Key<'a>,
    score: f64,
}

impl<'a> ScoredId<'a> {
    pub fn key(&self) -> Key<'a> {
        self.key
    }

    pub fn score(&self) -> f64 {
        self.score
    }

    pub(crate) fn checked(key: Key<'a>, score: f64) -> Result<Self, ScoreError> {
        if !score.is_finite() || score < 0.0 {
            return Err(ScoreError::InvalidScore);
        }
        Ok(Self { key, score })
    }
}

pub(crate) fn validate_scope(scope: &InputScope<'_>, keys: &[Key<'_>]) -> Result<(), ScoreError> {
    if scope.expected_source_set.is_empty()
        || scope.expected_source_set != scope.actual_source_set
    {
        return Err(ScoreError::ScopeMismatch);
    }
    if keys.len() > MAX_ROWS || scope.expected_keys.len() > MAX_ROWS {
        return Err(ScoreError::RowLimit);
    }
    let expected = identities(scope.expected_keys)?;
    let actual = identities(keys)?;
    if expected != actual {
        return Err(ScoreError::IdentityMismatch);
    }
    Ok(())
}

fn identities<'a>(keys: &[Key<'a>]) -> Result<BTreeMap<&'a str, &'a str>, ScoreError> {
    let mut result = BTreeMap::new();
    for key in keys {
        if key.record_id.is_empty() || key.record_version.is_empty() {
            return Err(ScoreError::IdentityMismatch);
        }
        if result.insert(key.record_id, key.record_version).is_some() {
            return Err(ScoreError::DuplicateIdentity);
        }
    }
    Ok(result)
}

pub(crate) fn order(scores: &mut [ScoredId<'_>], descending: bool) {
    scores.sort_by(|left, right| {
        // checked() rejects NaN. Numeric equality includes both signs of zero,
        // matching the fixed Python ordering; total_cmp would distinguish them.
        let numeric = if left.score < right.score {
            Ordering::Less
        } else if left.score > right.score {
            Ordering::Greater
        } else {
            Ordering::Equal
        };
        let numeric = if descending { numeric.reverse() } else { numeric };
        numeric.then_with(|| left.key.record_id.cmp(right.key.record_id))
    });
}
