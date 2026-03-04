"""Whisper.cpp transcription wrapper."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from ultratype.config import WhisperConfig


class Transcriber:
    """Transcribe audio using whisper-cli."""

    def __init__(self, config: WhisperConfig) -> None:
        self._config = config

    async def transcribe(self, wav_path: Path) -> str:
        """Run whisper-cli on a WAV file, return transcribed text."""
        cmd = [
            "whisper-cli",
            "-m", self._config.model_path,
            "-f", str(wav_path),
            "-l", self._config.language,
            "--no-timestamps",
            "-nt",
        ]

        if self._config.extra_args:
            cmd.extend(shlex.split(self._config.extra_args))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"whisper-cli failed (exit {process.returncode}): "
                f"{stderr.decode().strip()}"
            )

        text = stdout.decode().strip()
        # Join multi-line output into single string
        text = " ".join(line.strip() for line in text.splitlines() if line.strip())
        return text

    def check_model(self) -> bool:
        """Verify the model file exists."""
        return Path(self._config.model_path).is_file()
