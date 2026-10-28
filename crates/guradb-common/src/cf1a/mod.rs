//! CF1-A module-only common contracts; no runtime clients or state machines.
mod binding;
pub mod controlled_ports;
mod json;
pub mod ports;
pub mod publication;
pub mod read;
pub mod read_control;
pub mod types;
mod wire;

pub use types::*;
pub use wire::{canonical, digest, Contract, ContractFailure};

pub const VERSION: &str = "cf1a/1.0";
pub const CAPABILITIES: [&str; 4] = [
    "fixed_read",
    "typed_json_v1",
    "strong_integrity",
    "catalog_cas",
];

#[cfg(test)]
#[path = "../../tests/unit/cf1a.rs"]
mod tests;

#[cfg(test)]
#[path = "../../tests/unit/read_control.rs"]
mod read_control_tests;
#[cfg(test)]
#[path = "../../tests/unit/controlled_ports.rs"]
mod controlled_ports_tests;

/// Strict common wire decoding entry point; no version or capability fallback.
pub fn decode(raw: &[u8]) -> std::result::Result<Contract, ContractFailure> {
    wire::decode_document(raw)
}
