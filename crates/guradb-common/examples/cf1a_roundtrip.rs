//! Decode one CF1-A document from stdin and emit its validated canonical bytes.
use std::io::{Read, Write};
fn main() {
    let mut input = Vec::new();
    std::io::stdin()
        .take((1 << 20) + 1)
        .read_to_end(&mut input)
        .unwrap();
    match guradb_common::cf1a::decode(&input) {
        Ok(value) => std::io::stdout().write_all(value.encoded()).unwrap(),
        Err(error) => {
            eprintln!("{}: {}", error.code, error.message);
            std::process::exit(1);
        }
    }
}
