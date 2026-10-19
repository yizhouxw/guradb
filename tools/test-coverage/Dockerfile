FROM rust:1.90.0-bookworm@sha256:3914072ca0c3b8aad871db9169a651ccfce30cf58303e5d6f2db16d1d8a7e58f
RUN rustup component add clippy rustfmt llvm-tools-preview
RUN cargo install cargo-llvm-cov --version 0.6.21 --locked
ENV CARGO_BUILD_JOBS=2
WORKDIR /workspace
