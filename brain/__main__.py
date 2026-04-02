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


def main() -> None:
    p = argparse.ArgumentParser(
        prog="jarvis-brain",
        description="Voice pipeline — reads CLAP triggers from stdin",
    )
    p.add_argument("--init", action="store_true", help="Create default config and exit")
    p.add_argument("-v", "--verbose", action="store_true")

    args = p.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )

    if args.init:
        path = ensure_config_dir()
        print(f"Config created at {path}/config.toml")
        return

    cfg = load_config()
    asyncio.run(run_triggered(cfg))


if __name__ == "__main__":
    main()
