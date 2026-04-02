"""jarvis-brain — voice pipeline that reads CLAP triggers from stdin.

Usage:
    jarvis-listen | jarvis-brain
    jarvis-listen | python -m brain
"""

import argparse
import asyncio
import logging
import sys

from brain.session import run_triggered


def main() -> None:
    p = argparse.ArgumentParser(
        prog="jarvis-brain",
        description="Voice pipeline — reads CLAP triggers from stdin",
    )
    p.add_argument("--device-in", type=str, default=None, help="PipeWire input source")
    p.add_argument("--device-out", type=str, default=None, help="PipeWire output sink")
    p.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    p.add_argument("--stt-model", type=str, default="gpt-4o-mini-transcribe")
    p.add_argument("--tts-model", type=str, default="tts-1")
    p.add_argument("--tts-voice", type=str, default="onyx")
    p.add_argument("-v", "--verbose", action="store_true")

    args = p.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )

    asyncio.run(run_triggered(
        device_in=args.device_in,
        device_out=args.device_out,
        llm_model=args.llm_model,
        stt_model=args.stt_model,
        tts_model=args.tts_model,
        tts_voice=args.tts_voice,
    ))


if __name__ == "__main__":
    main()
