"""jarvis-brain — voice pipeline that reads CLAP triggers from stdin.

Usage:
    jarvis-listen | jarvis-brain
    jarvis-listen | python -m brain
    jarvis-brain --init          # create default config file
"""

import argparse
import asyncio
import logging
import os
import sys
import warnings

from brain.config import load_config, ensure_config_dir
from brain.session import run_triggered

# Suppress ONNX CUDA warning before any import touches onnxruntime
os.environ.setdefault("ONNXRUNTIME_DISABLE_CUDA_PROVIDER", "1")
warnings.filterwarnings("ignore", message=".*CUDAExecutionProvider.*")

_NOISY_LOGGERS = [
    "openai",
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "onnxruntime",
    "livekit",
]


def main() -> None:
    p = argparse.ArgumentParser(
        prog="jarvis-brain",
        description="Voice pipeline — reads CLAP triggers from stdin",
    )
    p.add_argument("--init", action="store_true", help="Create default config and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-vv", "--debug", action="store_true", help="Full debug (includes HTTP)")

    args = p.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO

    logging.basicConfig(
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )

    if not args.debug:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("brain").setLevel(level)

    if args.init:
        path = ensure_config_dir()
        print(f"Config created at {path}/config.toml")
        return

    cfg = load_config()

    try:
        asyncio.run(run_triggered(cfg))
    except KeyboardInterrupt:
        logging.getLogger("brain").info("Shutdown.")


if __name__ == "__main__":
    main()
