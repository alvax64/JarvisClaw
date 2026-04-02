"""Provider factories — build STT/LLM/TTS from config.

Supports:
    STT: "openai" (cloud), "whisper" (local via faster-whisper)
    LLM: "openai" (cloud) — local LLM is future work
    TTS: "openai" (cloud), "piper" (local)

Local providers are optional deps — import errors are caught and
reported clearly so the user knows what to install.
"""

import logging

from brain.config import Config

log = logging.getLogger(__name__)


def build_stt(cfg: Config):
    """Build STT instance from config."""
    match cfg.stt.provider:
        case "openai":
            from livekit.plugins import openai
            return openai.STT(model=cfg.stt.model, language=cfg.stt.language)

        case "whisper":
            from brain.local_stt import WhisperSTT
            return WhisperSTT(model=cfg.stt.model, language=cfg.stt.language)

        case other:
            raise ValueError(f"Unknown STT provider: {other}. Use 'openai' or 'whisper'.")


def build_llm(cfg: Config):
    """Build LLM instance from config."""
    match cfg.llm.provider:
        case "openai":
            from livekit.plugins import openai
            return openai.LLM(model=cfg.llm.model)

        case other:
            raise ValueError(f"Unknown LLM provider: {other}. Use 'openai'.")


def build_tts(cfg: Config):
    """Build TTS instance from config."""
    match cfg.tts.provider:
        case "openai":
            from livekit.plugins import openai
            return openai.TTS(model=cfg.tts.model, voice=cfg.tts.voice)

        case "piper":
            from brain.local_tts import PiperTTS
            return PiperTTS(model=cfg.tts.model, voice=cfg.tts.voice)

        case other:
            raise ValueError(f"Unknown TTS provider: {other}. Use 'openai' or 'piper'.")
