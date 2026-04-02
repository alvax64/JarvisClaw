# Multi-stage: build static Rust binary, run on Alpine with pw-cat.
# Image final: ~15MB.

# ── Build ────────────────────────────────────────────────────────
FROM rust:1-alpine AS build
RUN apk add --no-cache musl-dev
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src/ src/
RUN cargo build --release --target x86_64-unknown-linux-musl

# ── Runtime ──────────────────────────────────────────────────────
FROM alpine:3.21
RUN apk add --no-cache pipewire-tools
COPY --from=build /src/target/x86_64-unknown-linux-musl/release/jarvis-listen /usr/local/bin/jarvis-listen

ENTRYPOINT ["jarvis-listen"]
