"""Local STT via faster-whisper — LiveKit Agents STT plugin.

Install: pip install faster-whisper

Models download on first use (~150MB for base, ~500MB for small).
Runs on CPU with int8 quantization — ~200ms per short utterance.

Config:
    [stt]
    provider = "whisper"
    model = "base"       # tiny, base, small, medium, large-v3
    language = "es"
"""

import logging
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor

from livekit.agents import stt, utils

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)


class WhisperSTT(stt.STT):
    """faster-whisper as a LiveKit STT plugin."""

    def __init__(self, *, model: str = "base", language: str = "es") -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=False,
                interim_results=False,
            )
        )
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
                "Or switch to cloud: [stt] provider = 'openai'"
            )
        log.info("Loading whisper '%s' (downloads on first use)...", self._model_name)
        self._model = WhisperModel(self._model_name, compute_type="int8")
        log.info("Whisper model loaded")

    def _transcribe_sync(self, wav_path: str) -> str:
        self._ensure_model()
        segments, _ = self._model.transcribe(
            wav_path,
            language=self._language,
            beam_size=5,
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def _recognize_impl(
        self,
        buffer,
        *,
        language=None,
        conn_options=None,
    ) -> stt.SpeechEvent:
        """Transcribe an audio buffer. Called by AgentSession after VAD."""
        import asyncio

        # Merge audio frames into one WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
            with wave.open(f, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                if hasattr(buffer, '__iter__'):
                    for frame in buffer:
                        wf.writeframes(bytes(frame.data))
                else:
                    wf.writeframes(bytes(buffer.data))

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(_executor, self._transcribe_sync, wav_path)

        import os
        os.unlink(wav_path)

        lang = language or self._language
        log.info("Whisper: %s", text[:80] if text else "(silence)")

        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                stt.SpeechData(language=lang, text=text, confidence=1.0),
            ],
        )
