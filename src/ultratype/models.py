"""Whisper model download helper."""

from __future__ import annotations

import sys

import httpx

from ultratype.config import MODELS_DIR

_HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

AVAILABLE_MODELS: dict[str, tuple[str, int]] = {
    "tiny": ("ggml-tiny.bin", 75_000_000),
    "tiny.en": ("ggml-tiny.en.bin", 75_000_000),
    "base": ("ggml-base.bin", 148_000_000),
    "base.en": ("ggml-base.en.bin", 148_000_000),
    "small": ("ggml-small.bin", 488_000_000),
    "small.en": ("ggml-small.en.bin", 488_000_000),
    "medium": ("ggml-medium.bin", 1_500_000_000),
    "medium.en": ("ggml-medium.en.bin", 1_500_000_000),
    "large-v3": ("ggml-large-v3.bin", 3_100_000_000),
}


async def list_models() -> None:
    """List available models and their download status."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Model directory: {MODELS_DIR}\n")
    print(f"{'Name':<14} {'File':<28} {'Size':>10}  Status")
    print("-" * 70)
    for name, (filename, size) in AVAILABLE_MODELS.items():
        path = MODELS_DIR / filename
        status = "downloaded" if path.exists() else "not downloaded"
        size_mb = f"{size / 1_000_000:.0f} MB"
        print(f"{name:<14} {filename:<28} {size_mb:>10}  {status}")


async def download_model(model_name: str) -> None:
    """Download a whisper.cpp model from Hugging Face."""
    if model_name not in AVAILABLE_MODELS:
        print(f"Unknown model: {model_name}")
        print(f"Available: {', '.join(AVAILABLE_MODELS.keys())}")
        sys.exit(1)

    filename, expected_size = AVAILABLE_MODELS[model_name]
    url = f"{_HF_BASE}/{filename}"
    dest = MODELS_DIR / filename

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        print(f"Model already exists: {dest}")
        return

    print(f"Downloading {model_name} ({expected_size / 1_000_000:.0f} MB)...")
    print(f"  From: {url}")
    print(f"  To:   {dest}")

    async with httpx.AsyncClient(follow_redirects=True, timeout=300.0) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", expected_size))
            downloaded = 0

            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    pct = min(downloaded * 100 // total, 100)
                    bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
                    print(
                        f"\r  [{bar}] {pct}% "
                        f"({downloaded // 1_000_000}/{total // 1_000_000} MB)",
                        end="",
                        flush=True,
                    )
            print()

    print(f"Done: {dest}")
