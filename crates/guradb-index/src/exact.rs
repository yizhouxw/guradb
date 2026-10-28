use std::collections::BTreeSet;

use crate::score::{order, validate_scope, MAX_ROWS};
use crate::{InputScope, Key, ScoreError, ScoredId};

#[derive(Clone, Debug)]
pub struct ExactConfig<'a> {
    pub model_id: &'a str,
    pub model_version: &'a str,
    pub dimension: u32,
    pub metric: &'a str,
    pub analyzer: &'a str,
    pub processing_version: &'a str,
    pub normalization: &'a str,
    pub null_policy: &'a str,
    pub component_bound: &'a str,
    pub distance_sum: &'a str,
}

impl ExactConfig<'static> {
    pub fn fixed() -> Self {
        Self {
            model_id: "outline-synthetic-zh-image3",
            model_version: "1",
            dimension: 3,
            metric: "squared_l2",
            analyzer: "none",
            processing_version: "zh-CN-hand-segmented-v1",
            normalization: "none",
            null_policy: "explicit-mask-exclude",
            component_bound: "1e150",
            distance_sum: "binary64-fsum-dimension-order",
        }
    }
}

fn validate_configuration(value: &ExactConfig<'_>) -> Result<(), ScoreError> {
    if value.model_id != "outline-synthetic-zh-image3"
        || value.model_version != "1"
        || value.dimension != 3
        || value.metric != "squared_l2"
        || value.analyzer != "none"
        || value.processing_version != "zh-CN-hand-segmented-v1"
        || value.normalization != "none"
        || value.null_policy != "explicit-mask-exclude"
        || value.component_bound != "1e150"
        || value.distance_sum != "binary64-fsum-dimension-order"
    {
        return Err(ScoreError::InvalidConfiguration);
    }
    Ok(())
}

pub enum VectorValue<'a> {
    Present(&'a [f64]),
    Null { reason: &'a str },
}

pub struct VectorRow<'a> {
    pub key: Key<'a>,
    pub value: VectorValue<'a>,
}

#[derive(Debug)]
pub struct PreparedExact<'a> {
    rows: Vec<(Key<'a>, Option<[f64; 3]>)>,
}

fn components(values: &[f64]) -> Result<[f64; 3], ScoreError> {
    if values.len() != 3 || values.iter().any(|v| !v.is_finite() || v.abs() > 1e150) {
        return Err(ScoreError::InvalidVector);
    }
    Ok([values[0], values[1], values[2]])
}

pub fn prepare_exact<'a>(
    scope: &InputScope<'_>,
    config: &ExactConfig<'_>,
    rows: &[VectorRow<'a>],
    checkpoint: &mut impl FnMut() -> Result<(), ScoreError>,
) -> Result<PreparedExact<'a>, ScoreError> {
    checkpoint()?;
    validate_configuration(config)?;
    if rows.len() > MAX_ROWS {
        return Err(ScoreError::RowLimit);
    }
    validate_scope(scope, &rows.iter().map(|row| row.key).collect::<Vec<_>>())?;
    let mut result = Vec::with_capacity(rows.len());
    for row in rows {
        checkpoint()?;
        let vector = match &row.value {
            VectorValue::Present(values) => Some(components(values)?),
            VectorValue::Null { reason } => {
                if reason.is_empty() || reason.chars().count() > 128 {
                    return Err(ScoreError::InvalidVector);
                }
                None
            }
        };
        result.push((row.key, vector));
    }
    checkpoint()?;
    Ok(PreparedExact { rows: result })
}

impl<'a> PreparedExact<'a> {
    pub fn source_count(&self) -> usize {
        self.rows.len()
    }

    pub fn vector_count(&self) -> usize {
        self.rows.iter().filter(|(_, vector)| vector.is_some()).count()
    }

    /// HOLD-N2: multiplication and expansion are candidates for Python **2/fsum,
    /// not a certified replacement. No FMA, epsilon ordering or normalization.
    pub fn score_candidate(
        &self,
        query: &[f64],
        allowed: Option<&BTreeSet<&str>>,
        checkpoint: &mut impl FnMut() -> Result<(), ScoreError>,
    ) -> Result<Vec<ScoredId<'a>>, ScoreError> {
        checkpoint()?;
        let query = components(query)?;
        let mut result = Vec::new();
        for (key, vector) in &self.rows {
            checkpoint()?;
            if let Some(vector) = vector {
                let mut squares = [0.0; 3];
                for dimension in 0..3 {
                    let difference = vector[dimension] - query[dimension];
                    squares[dimension] = difference * difference;
                }
                let hit = ScoredId::checked(*key, sum_candidate(squares))?;
                if allowed.is_none_or(|ids| ids.contains(key.record_id)) {
                    result.push(hit);
                }
            }
        }
        order(&mut result, false);
        checkpoint()?;
        Ok(result)
    }
}

/// Error-free expansion candidate in input dimension order. Inputs are three
/// finite nonnegative squares within the fixed component bound. Retain low
/// terms and apply a final same-sign rounding correction rather than fold(+).
/// Compatibility across the complete Python input domain remains HOLD-N2.
fn sum_candidate(terms: [f64; 3]) -> f64 {
    let mut partials: Vec<f64> = Vec::with_capacity(3);
    for mut x in terms {
        let mut kept = 0;
        for index in 0..partials.len() {
            let mut y = partials[index];
            if x.abs() < y.abs() {
                std::mem::swap(&mut x, &mut y);
            }
            let high = x + y;
            let low = y - (high - x);
            if low != 0.0 {
                partials[kept] = low;
                kept += 1;
            }
            x = high;
        }
        partials.truncate(kept);
        partials.push(x);
    }
    // Each input pushes one value, including zero: this index cannot be empty.
    let mut remaining = partials.len() - 1;
    let mut high = partials[remaining];
    let mut low = 0.0;
    while remaining > 0 {
        remaining -= 1;
        let x = high;
        let y = partials[remaining];
        high = x + y;
        low = y - (high - x);
        if low != 0.0 {
            break;
        }
    }
    if remaining > 0
        && ((low < 0.0 && partials[remaining - 1] < 0.0)
            || (low > 0.0 && partials[remaining - 1] > 0.0))
    {
        let twice = low * 2.0;
        let corrected = high + twice;
        if twice == corrected - high {
            high = corrected;
        }
    }
    high
}
