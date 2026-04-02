"""PipeWire audio I/O adapters for LiveKit Agents SDK.

Bridges pw-cat/pw-play subprocess I/O to the SDK's AudioInput/AudioOutput
interfaces. No WebRTC, no network — just local audio pipes.
"""

import asyncio
import logging
import time

from livekit import rtc
from livekit.agents.voice.io import AudioInput, AudioOutput, AudioOutputCapabilities

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit signed LE
FRAME_MS = 50  # 50ms frames — matches SDK default
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 800
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH * CHANNELS  # 1600


class PipeWireInput(AudioInput):
    """Read audio from PipeWire via pw-cat subprocess."""

    def __init__(self, *, device: str | None = None) -> None:
        super().__init__(label="pipewire_input")
        self._device = device
        self._proc: asyncio.subprocess.Process | None = None
        self._running = False

    async def _ensure_started(self) -> None:
        if self._proc is not None:
            return

        cmd = [
            "pw-cat", "--record",
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "-",
        ]
        if self._device and self._device != "default":
            cmd.insert(2, f"--target={self._device}")

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._running = True
        log.info("PipeWire input started (rate=%d, frame=%dms)", SAMPLE_RATE, FRAME_MS)

    def __aiter__(self):
        return self

    async def __anext__(self) -> rtc.AudioFrame:
        await self._ensure_started()
        assert self._proc and self._proc.stdout

        try:
            data = await self._proc.stdout.readexactly(FRAME_BYTES)
        except (asyncio.IncompleteReadError, ConnectionError):
            raise StopAsyncIteration

        return rtc.AudioFrame(
            data=data,
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
            samples_per_channel=FRAME_SAMPLES,
        )

    def on_detached(self) -> None:
        self._running = False
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            self._proc = None
        log.info("PipeWire input stopped")


class PipeWireOutput(AudioOutput):
    """Write audio to PipeWire via pw-play subprocess."""

    def __init__(self, *, device: str | None = None) -> None:
        super().__init__(
            label="pipewire_output",
            capabilities=AudioOutputCapabilities(pause=False),
            sample_rate=SAMPLE_RATE,
        )
        self._device = device
        self._proc: asyncio.subprocess.Process | None = None
        self._capturing = False
        self._playback_start: float = 0.0
        self._samples_written: int = 0

    async def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return

        cmd = [
            "pw-play",
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "-",
        ]
        if self._device and self._device != "default":
            cmd.insert(1, f"--target={self._device}")

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        log.info("PipeWire output started")

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)
        await self._ensure_started()
        assert self._proc and self._proc.stdin

        if not self._capturing:
            self._capturing = True
            self._playback_start = time.time()
            self._samples_written = 0
            self.on_playback_started(created_at=self._playback_start)

        self._proc.stdin.write(frame.data)
        await self._proc.stdin.drain()
        self._samples_written += frame.samples_per_channel

    def flush(self) -> None:
        super().flush()
        if not self._capturing:
            return
        self._capturing = False
        position = self._samples_written / SAMPLE_RATE
        self.on_playback_finished(
            playback_position=position,
            interrupted=False,
        )

    def clear_buffer(self) -> None:
        """Stop playback immediately by killing pw-play."""
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            self._proc = None

        if self._capturing:
            self._capturing = False
            position = self._samples_written / SAMPLE_RATE
            self.on_playback_finished(
                playback_position=position,
                interrupted=True,
            )

    def on_detached(self) -> None:
        self.clear_buffer()
        log.info("PipeWire output stopped")
