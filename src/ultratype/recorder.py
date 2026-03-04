"""PipeWire audio recorder wrapper."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from ultratype.config import RecordingConfig


class Recorder:
    """Record audio via pw-record."""

    def __init__(self, config: RecordingConfig) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._output_path: Path | None = None

    async def start(self) -> Path:
        """Start pw-record, return the path to the output WAV file."""
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="ultratype_")
        os.close(fd)
        self._output_path = Path(path)

        cmd = [
            "pw-record",
            "--rate", str(self._config.sample_rate),
            "--channels", str(self._config.channels),
            "--format", self._config.format,
        ]
        if self._config.device and self._config.device != "default":
            cmd.extend(["--target", self._config.device])
        cmd.append(str(self._output_path))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        return self._output_path

    async def stop(self) -> Path:
        """Send SIGINT to pw-record, wait for WAV header finalization."""
        if self._process is None:
            raise RuntimeError("Recorder not started")

        self._process.send_signal(2)  # SIGINT for clean WAV header write
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self._process.kill()
            await self._process.wait()

        path = self._output_path
        self._process = None
        self._output_path = None
        return path  # type: ignore[return-value]

    @property
    def is_recording(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @staticmethod
    def cleanup(wav_path: Path) -> None:
        """Remove temporary WAV file after processing."""
        wav_path.unlink(missing_ok=True)
