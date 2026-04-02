"""Local STT via faster-whisper — offline speech-to-text.

Install: pip install faster-whisper

Models download automatically on first use:
    "tiny"    — 39M,  fastest, lowest quality
    "base"    — 74M,  good for short commands
    "small"   — 244M, good balance
    "medium"  — 769M, high quality
    "large-v3"— 1.5G, best quality

Usage in config.toml:
    [stt]
    provider = "whisper"
    model = "base"        # or "small", "medium", etc.
    language = "es"
"""

import asyncio
import io
import logging
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor

from livekit import rtc

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)


class WhisperSTT:
    """Wraps faster-whisper as a drop-in for the voice pipeline.

    Not a full LiveKit STT plugin — just enough to work with our
    session. The AgentSession collects audio via VAD, then calls
    recognize() with the complete utterance.
    """

    def __init__(self, model: str = "base", language: str = "es") -> None:
        self._model_name = model
        self._language = language
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper not installed. Run: pip install faster-whisper\n"
                "Or switch to cloud STT: [stt] provider = 'openai'"
            )
        log.info("Loading whisper model '%s' (first load downloads it)...", self._model_name)
        self._model = WhisperModel(self._model_name, compute_type="int8")
        log.info("Whisper model loaded")

    def _transcribe_sync(self, audio_bytes: bytes, sample_rate: int) -> str:
        """Run transcription in a thread (CPU-bound)."""
        self._ensure_model()

        # Write to temp WAV — faster-whisper needs a file path
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
            with wave.open(f.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_bytes)

            segments, info = self._model.transcribe(
                f.name,
                language=self._language,
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments)

        return text.strip()

    async def recognize(self, audio_frames: list[rtc.AudioFrame]) -> str:
        """Transcribe a list of audio frames. Returns text."""
        if not audio_frames:
            return ""

        # Concatenate all frames into one buffer
        sample_rate = audio_frames[0].sample_rate
        audio_bytes = b"".join(bytes(f.data) for f in audio_frames)

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            _executor, self._transcribe_sync, audio_bytes, sample_rate,
        )

        log.debug("Whisper transcribed: %s", text[:100])
        return text
