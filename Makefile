# Jarvis voice assistant

.PHONY: run watch init install build test clean

# Run the full pipeline
run:
	daemon/target/release/jarvis-listen --threshold 2500 | .venv/bin/jarvis-brain

# Run with verbose logs
run-v:
	daemon/target/release/jarvis-listen --threshold 2500 -v | .venv/bin/jarvis-brain -v

# Calibrate microphone
watch:
	daemon/target/release/jarvis-listen --watch

# Create default config
init:
	.venv/bin/jarvis-brain --init

# Install everything
install:
	python -m venv .venv
	.venv/bin/pip install -e ".[all]"
	cd daemon && cargo build --release

# Build Rust daemon only
build:
	cd daemon && cargo build --release

# Run Rust tests
test:
	cd daemon && cargo test

clean:
	cd daemon && cargo clean
	rm -rf .venv __pycache__ brain/__pycache__ brain/tools/__pycache__
