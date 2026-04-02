"""Local TTS via Piper — offline text-to-speech.

Install: yay -S piper-tts
Models: https://github.com/rhasspy/piper/blob/master/VOICES.md

Download a voice model (.onnx + .json):
    mkdir -p ~/.local/share/piper
    cd ~/.local/share/piper
    wget https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_MX/claude/high/es_MX-claude-high.onnx
    wget https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_MX/claude/high/es_MX-claude-high.onnx.json

Usage in config.toml:
    [tts]
    provider = "piper"
    model = "~/.local/share/piper/es_MX-claude-high.onnx"
    voice = ""   # unused for piper
"""

import asyncio
import logging
import shutil
import struct
import subprocess
from pathlib import Path

from livekit import rtc
from livekit.agents.voice.io import AudioOutput

log = logging.getLogger(__name__)

PIPER_SAMPLE_RATE = 22050  # Piper outputs 22050 Hz by default
PIPER_CHANNELS = 1


class PiperTTS:
    """Wraps piper CLI for local TTS.

    Piper reads text from stdin, writes raw PCM (s16le) to stdout.
    We stream those frames to the AudioOutput.
    """

    def __init__(self, model: str = "", voice: str = "") -> None:
        self._model = str(Path(model).expanduser()) if model else ""
        self._piper_bin = shutil.which("piper") or shutil.which("piper-tts")

        if not self._piper_bin:
            raise RuntimeError(
                "piper not found. Install: yay -S piper-tts\n"
                "Or switch to cloud TTS: [tts] provider = 'openai'"
            )

        if self._model and not Path(self._model).exists():
            raise FileNotFoundError(
                f"Piper model not found: {self._model}\n"
                f"Download from: https://github.com/rhasspy/piper/blob/master/VOICES.md"
            )

    async def synthesize(self, text: str) -> list[rtc.AudioFrame]:
        """Synthesize text to audio frames."""
        if not text.strip():
            return []

        cmd = [self._piper_bin, "--output_raw"]
        if self._model:
            cmd.extend(["--model", self._model])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        stdout, _ = await asyncio.wait_for(
            proc.communicate(input=text.encode()),
            timeout=30,
        )

        if not stdout:
            log.warning("Piper produced no audio for: %s", text[:50])
            return []

        # Split raw PCM into frames (50ms each)
        frame_samples = PIPER_SAMPLE_RATE * 50 // 1000  # 1102
        frame_bytes = frame_samples * 2  # 16-bit
        frames = []

        for i in range(0, len(stdout), frame_bytes):
            chunk = stdout[i:i + frame_bytes]
            if len(chunk) < frame_bytes:
                # Pad last frame with silence
                chunk += b"\x00" * (frame_bytes - len(chunk))
            frames.append(rtc.AudioFrame(
                data=chunk,
                sample_rate=PIPER_SAMPLE_RATE,
                num_channels=PIPER_CHANNELS,
                samples_per_channel=frame_samples,
            ))

        log.debug("Piper synthesized %d frames for: %s", len(frames), text[:50])
        return frames
