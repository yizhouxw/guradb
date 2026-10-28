use std::collections::{BTreeMap, BTreeSet};

use crate::score::{order, validate_scope, MAX_ROWS};
use crate::{InputScope, Key, ScoreError, ScoredId};

/// All fields of the fixed model, with no configurable scoring algorithm.
#[derive(Clone, Debug)]
pub struct Bm25Config<'a> {
    pub model_id: &'a str,
    pub model_version: &'a str,
    pub dimension: u32,
    pub metric: &'a str,
    pub analyzer: &'a str,
    pub processing_version: &'a str,
    pub text_field_id: u64,
    pub k1: f64,
    pub b: f64,
    pub statistics: &'a str,
    pub null_policy: &'a str,
    pub query_terms: &'a str,
    pub normalization: &'a str,
}

impl Bm25Config<'static> {
    pub fn fixed(text_field_id: u64) -> Self {
        Self {
            model_id: "bm25-fixed-tokens",
            model_version: "1",
            dimension: 1,
            metric: "bm25",
            analyzer: "fixed-whitespace-v1",
            processing_version: "zh-CN-hand-segmented-v1",
            text_field_id,
            k1: 1.2,
            b: 0.75,
            statistics: "all-source-rows-before-filter",
            null_policy: "count-empty",
            query_terms: "preserve-duplicates",
            normalization: "none",
        }
    }
}

fn validate_configuration(value: &Bm25Config<'_>) -> Result<(), ScoreError> {
    if value.model_id != "bm25-fixed-tokens"
        || value.model_version != "1"
        || value.dimension != 1
        || value.metric != "bm25"
        || value.analyzer != "fixed-whitespace-v1"
        || value.processing_version != "zh-CN-hand-segmented-v1"
        || value.text_field_id == 0
        || value.text_field_id > (1_u64 << 53) - 1
        || value.k1.to_bits() != 1.2_f64.to_bits()
        || value.b.to_bits() != 0.75_f64.to_bits()
        || value.statistics != "all-source-rows-before-filter"
        || value.null_policy != "count-empty"
        || value.query_terms != "preserve-duplicates"
        || value.normalization != "none"
    {
        return Err(ScoreError::InvalidConfiguration);
    }
    Ok(())
}

fn separator(value: char) -> bool {
    matches!(value as u32, 9..=13 | 32 | 133 | 160 | 5760 | 8192..=8202
        | 8232 | 8233 | 8239 | 8287 | 12288)
}

fn validate_tokens(values: &[&str]) -> Result<(), ScoreError> {
    if values.len() > 1024
        || values.iter().any(|term| {
            term.is_empty() || term.chars().count() > 128 || term.chars().any(separator)
        })
    {
        return Err(ScoreError::InvalidTokens);
    }
    Ok(())
}

/// Exact fixed separators: preserves case, punctuation and duplicate terms.
pub fn tokenize(text: &str) -> Result<Vec<&str>, ScoreError> {
    if text.chars().count() > 4096 {
        return Err(ScoreError::InvalidTokens);
    }
    let words: Vec<_> = text.split(separator).filter(|word| !word.is_empty()).collect();
    validate_tokens(&words)?;
    Ok(words)
}

pub struct TextRow<'a> {
    pub key: Key<'a>,
    /// None is explicit NULL; Some(empty) is present empty text.
    pub tokens: Option<&'a [&'a str]>,
}

#[derive(Debug)]
struct Document<'a> {
    key: Key<'a>,
    length: usize,
    frequencies: BTreeMap<&'a str, usize>,
}

/// Statistics cannot be supplied separately from the complete validated corpus.
#[derive(Debug)]
pub struct PreparedBm25<'a> {
    documents: Vec<Document<'a>>,
    total_tokens: usize,
    document_frequencies: BTreeMap<&'a str, usize>,
}

pub fn prepare_bm25<'a>(
    scope: &InputScope<'_>,
    config: &Bm25Config<'_>,
    rows: &[TextRow<'a>],
    checkpoint: &mut impl FnMut() -> Result<(), ScoreError>,
) -> Result<PreparedBm25<'a>, ScoreError> {
    checkpoint()?;
    validate_configuration(config)?;
    if rows.len() > MAX_ROWS {
        return Err(ScoreError::RowLimit);
    }
    validate_scope(scope, &rows.iter().map(|row| row.key).collect::<Vec<_>>())?;
    let mut prepared = PreparedBm25 {
        documents: Vec::with_capacity(rows.len()),
        total_tokens: 0,
        document_frequencies: BTreeMap::new(),
    };
    for row in rows {
        checkpoint()?;
        let tokens = row.tokens.unwrap_or(&[]);
        validate_tokens(tokens)?;
        let mut frequencies = BTreeMap::new();
        for &token in tokens {
            *frequencies.entry(token).or_insert(0) += 1;
        }
        for &token in frequencies.keys() {
            *prepared.document_frequencies.entry(token).or_insert(0) += 1;
        }
        if prepared.document_frequencies.len() > 4096 {
            return Err(ScoreError::InvalidTokens);
        }
        // Scope bounds 100 rows and each row <=1024 terms; no unbounded counters.
        prepared.total_tokens += tokens.len();
        prepared.documents.push(Document { key: row.key, length: tokens.len(), frequencies });
    }
    checkpoint()?;
    Ok(prepared)
}

impl<'a> PreparedBm25<'a> {
    pub fn document_count(&self) -> usize {
        self.documents.len()
    }

    pub fn total_tokens(&self) -> usize {
        self.total_tokens
    }

    pub fn document_frequency(&self, term: &str) -> usize {
        self.document_frequencies.get(term).copied().unwrap_or(0)
    }

    /// HOLD-N1: ln_1p compatibility with Python math.log1p is not certified.
    /// No global top-k: Q owns selection/fusion after this private candidate.
    pub fn score_candidate(
        &self,
        query: &str,
        allowed: Option<&BTreeSet<&str>>,
        checkpoint: &mut impl FnMut() -> Result<(), ScoreError>,
    ) -> Result<Vec<ScoredId<'a>>, ScoreError> {
        checkpoint()?;
        let terms = tokenize(query)?;
        if terms.is_empty() {
            return Err(ScoreError::InvalidTokens);
        }
        let mut scores = Vec::new();
        if self.total_tokens != 0 {
            let n = self.documents.len() as f64;
            let average = self.total_tokens as f64 / n;
            for row in &self.documents {
                checkpoint()?;
                let mut value = 0.0;
                for term in &terms {
                    let frequency = row.frequencies.get(term).copied().unwrap_or(0) as f64;
                    if frequency > 0.0 {
                        let df = self.document_frequency(term) as f64;
                        let inverse = ((n - df + 0.5) / (df + 0.5)).ln_1p();
                        let denominator = frequency + 1.2 * (0.25 + 0.75 * row.length as f64 / average);
                        value += inverse * frequency * 2.2 / denominator;
                    }
                }
                let scored = ScoredId::checked(row.key, value)?;
                if value > 0.0 && allowed.is_none_or(|ids| ids.contains(row.key.record_id)) {
                    scores.push(scored);
                }
            }
        }
        order(&mut scores, true);
        checkpoint()?;
        Ok(scores)
    }
}
