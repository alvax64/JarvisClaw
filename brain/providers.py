"""Provider factories — build STT/LLM/TTS from config with fallback chains.

Provider field is comma-separated: first that succeeds wins.
    provider = "elevenlabs,openai,piper"

On runtime failure (API down, rate limit), the session rebuilds
and the chain tries the next provider.

Supported:
    STT: openai, whisper
    LLM: openai
    TTS: elevenlabs, openai, piper
"""

import logging

from brain.config import Config

log = logging.getLogger(__name__)


def _parse_chain(provider_str: str) -> list[str]:
    """Parse "elevenlabs,openai,piper" into ["elevenlabs", "openai", "piper"]."""
    return [p.strip() for p in provider_str.split(",") if p.strip()]


def _build_one_stt(name: str, cfg: Config):
    match name:
        case "openai":
            from livekit.plugins import openai
            return openai.STT(model=cfg.stt.model, language=cfg.stt.language)
        case "whisper":
            from brain.local_stt import WhisperSTT
            return WhisperSTT(model=cfg.stt.model, language=cfg.stt.language)
        case _:
            raise ValueError(f"Unknown STT: {name}")


def _build_one_llm(name: str, cfg: Config):
    match name:
        case "openai":
            from livekit.plugins import openai
            return openai.LLM(model=cfg.llm.model)
        case _:
            raise ValueError(f"Unknown LLM: {name}")


def _build_one_tts(name: str, cfg: Config):
    match name:
        case "elevenlabs":
            from livekit.plugins import elevenlabs
            return elevenlabs.TTS(
                model=cfg.tts.model or "eleven_turbo_v2_5",
                voice_id=cfg.tts.voice or "l7kNoIfnJKPg7779LI2t",
            )
        case "openai":
            from livekit.plugins import openai
            return openai.TTS(model=cfg.tts.model or "tts-1", voice=cfg.tts.voice or "onyx")
        case "piper":
            from brain.local_tts import PiperTTS
            return PiperTTS(model=cfg.tts.model, voice=cfg.tts.voice)
        case _:
            raise ValueError(f"Unknown TTS: {name}")


def _build_with_fallback(chain: list[str], builder, cfg: Config, label: str):
    """Try each provider in the chain. First that instantiates wins."""
    errors = []
    for name in chain:
        try:
            instance = builder(name, cfg)
            if len(chain) > 1:
                log.info("%s provider: %s (fallbacks: %s)", label, name, chain[chain.index(name)+1:] or "none")
            else:
                log.info("%s provider: %s", label, name)
            return instance
        except Exception as e:
            log.warning("%s provider '%s' failed to init: %s", label, name, e)
            errors.append((name, e))

    msg = "; ".join(f"{n}: {e}" for n, e in errors)
    raise RuntimeError(f"All {label} providers failed: {msg}")


def build_stt(cfg: Config):
    chain = _parse_chain(cfg.stt.provider)
    return _build_with_fallback(chain, _build_one_stt, cfg, "STT")


def build_llm(cfg: Config):
    chain = _parse_chain(cfg.llm.provider)
    return _build_with_fallback(chain, _build_one_llm, cfg, "LLM")


def build_tts(cfg: Config):
    chain = _parse_chain(cfg.tts.provider)
    return _build_with_fallback(chain, _build_one_tts, cfg, "TTS")
