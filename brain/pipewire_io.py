"""PipeWire audio I/O adapters for LiveKit Agents SDK.

Bridges pw-cat/pw-play subprocess I/O to the SDK's AudioInput/AudioOutput
interfaces. No WebRTC, no network — just local audio pipes.

PipeWireInput supports gating: when gated, it yields silence frames
instead of real audio. This lets the AgentSession stay alive while
Jarvis is dormant between activations.
"""

import asyncio
import logging
import subprocess
import time

from livekit import rtc
from livekit.agents.voice.io import AudioInput, AudioOutput, AudioOutputCapabilities

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit signed LE
FRAME_MS = 50
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 800
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH * CHANNELS  # 1600

# Pre-allocated silence frame — no alloc per iteration when gated
_SILENCE = b"\x00" * FRAME_BYTES


class PipeWireInput(AudioInput):
    """Read audio from PipeWire via pw-cat subprocess.

    Supports gating: when gated (default), yields silence so the
    AgentSession stays alive but VAD won't trigger. Call open_gate()
    to let real audio through, close_gate() to go silent.

    When gated, real audio is still read and fed to the wake word
    detector (if set). This enables "Hey Jarvis" detection while idle.
    """

    def __init__(self, *, device: str | None = None) -> None:
        super().__init__(label="pipewire_input")
        self._device = device
        self._proc: asyncio.subprocess.Process | None = None
        self._gate_open = False
        self._wakeword = None  # set via set_wakeword()

    @property
    def is_active(self) -> bool:
        return self._gate_open

    def open_gate(self) -> None:
        self._gate_open = True
        log.debug("Audio gate opened")

    def close_gate(self) -> None:
        self._gate_open = False
        if self._wakeword:
            self._wakeword.reset()
        log.debug("Audio gate closed")

    def set_wakeword(self, detector) -> None:
        """Attach a WakeWordDetector — fed while gate is closed."""
        self._wakeword = detector

    async def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
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
        log.info("pw-cat started (rate=%d, frame=%dms)", SAMPLE_RATE, FRAME_MS)

    def __aiter__(self):
        return self

    async def __anext__(self) -> rtc.AudioFrame:
        await self._ensure_started()
        assert self._proc and self._proc.stdout

        try:
            data = await self._proc.stdout.readexactly(FRAME_BYTES)
        except (asyncio.IncompleteReadError, ConnectionError):
            # pw-cat died — restart it, yield silence this frame
            log.warning("pw-cat died, restarting")
            self._proc = None
            await self._ensure_started()
            data = _SILENCE

        # Gate: if closed, feed wake word detector, yield silence to VAD
        if not self._gate_open:
            if self._wakeword:
                self._wakeword.feed(data)
            data = _SILENCE

        return rtc.AudioFrame(
            data=data,
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
            samples_per_channel=FRAME_SAMPLES,
        )

    def on_detached(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            self._proc = None
        log.info("PipeWire input stopped")


class PipeWireOutput(AudioOutput):
    """Write audio to PipeWire via paplay subprocess.

    Uses subprocess.Popen (not asyncio) to avoid Python 3.14 asyncio
    pipe bugs. Writes are small (1600 bytes/frame) and non-blocking
    in practice — paplay reads faster than we write.
    """

    def __init__(self, *, device: str | None = None) -> None:
        super().__init__(
            label="pipewire_output",
            capabilities=AudioOutputCapabilities(pause=False),
            sample_rate=SAMPLE_RATE,
        )
        self._device = device
        self._proc: subprocess.Popen | None = None
        self._capturing = False
        self._playback_start: float = 0.0
        self._samples_written: int = 0

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return

        cmd = [
            "paplay", "--raw",
            f"--rate={SAMPLE_RATE}",
            f"--channels={CHANNELS}",
            "--format=s16le",
        ]
        if self._device and self._device != "default":
            cmd.append(f"--device={self._device}")

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("paplay started")

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)
        self._ensure_started()
        assert self._proc and self._proc.stdin

        if not self._capturing:
            self._capturing = True
            self._playback_start = time.time()
            self._samples_written = 0
            self.on_playback_started(created_at=self._playback_start)

        try:
            self._proc.stdin.write(bytes(frame.data))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            log.warning("paplay died, restarting")
            self._proc = None
            self._ensure_started()
            self._proc.stdin.write(bytes(frame.data))
            self._proc.stdin.flush()
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
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=2)
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
