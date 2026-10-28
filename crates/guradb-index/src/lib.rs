//! Internal fixed scoring candidates; numerical compatibility remains HOLD-N1/N2.
//! No CF1-A wire, locator, source reader, parent control or production route.
mod bm25;
mod exact;
mod score;

pub use bm25::{prepare_bm25, tokenize, Bm25Config, PreparedBm25, TextRow};
pub use exact::{prepare_exact, ExactConfig, PreparedExact, VectorRow, VectorValue};
pub use score::{InputScope, Key, ScoreError, ScoredId};

#[cfg(test)]
#[path = "../tests/unit/bm25.rs"]
mod bm25_tests;
#[cfg(test)]
#[path = "../tests/unit/exact.rs"]
mod exact_tests;

#[cfg(test)]
#[path = "../tests/unit/reference_bits.rs"]
mod reference_bits;
