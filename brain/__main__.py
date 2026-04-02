"""jarvis-brain — voice pipeline that reads CLAP triggers from stdin.

Usage:
    jarvis-listen | jarvis-brain
    jarvis-listen | python -m brain
    jarvis-brain --init          # create default config file
"""

import argparse
import asyncio
import logging
import sys

from brain.config import load_config, ensure_config_dir
from brain.session import run_triggered

# Libraries that spam DEBUG logs with raw bytes and HTTP internals
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

    if args.debug:
        level = logging.DEBUG
    elif args.verbose:
        level = logging.INFO
    else:
        level = logging.INFO

    logging.basicConfig(
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )

    # Silence noisy libraries unless -vv
    if not args.debug:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    # Always show our own logs
    logging.getLogger("brain").setLevel(level)

    if args.init:
        path = ensure_config_dir()
        print(f"Config created at {path}/config.toml")
        return

    cfg = load_config()
    asyncio.run(run_triggered(cfg))


if __name__ == "__main__":
    main()
