"""Jarvis configuration — TOML file + env vars + CLI overrides.

Load order (last wins):
    1. Defaults (hardcoded below)
    2. ~/.config/jarvis/config.toml
    3. Environment variables (JARVIS_*)
    4. CLI arguments

TOML example (~/.config/jarvis/config.toml):

    [audio]
    device_in = "default"
    device_out = "default"
    clap_threshold = 3000

    [stt]
    provider = "openai"       # "openai" or "whisper"
    model = "gpt-4o-mini-transcribe"
    language = "es"

    [llm]
    provider = "openai"
    model = "gpt-4o-mini"

    [tts]
    provider = "openai"       # "openai" or "piper"
    model = "tts-1"
    voice = "onyx"

    [session]
    inactivity_timeout = 8.0
    system_prompt = "You are Jarvis..."

    [keys]
    openai = "sk-..."
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "jarvis"
_CONFIG_FILE = _CONFIG_DIR / "config.toml"


@dataclass
class AudioConfig:
    device_in: str | None = None
    device_out: str | None = None
    clap_threshold: int = 3000
    clap_cooldown: float = 1.5

@dataclass
class STTConfig:
    provider: str = "openai"
    model: str = "gpt-4o-mini-transcribe"
    language: str = "es"

@dataclass
class LLMConfig:
    provider: str = "openai"
    model: str = "gpt-4o-mini"

@dataclass
class TTSConfig:
    provider: str = "openai"
    model: str = "tts-1"
    voice: str = "onyx"

@dataclass
class SessionConfig:
    inactivity_timeout: float = 8.0
    system_prompt: str = (
        "You are Jarvis, a personal voice assistant running on Linux. "
        "You are efficient, direct, and occasionally dry-witted. "
        "Respond in Spanish unless the user speaks English. "
        "Keep responses concise — this is voice, not text."
    )

@dataclass
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    session: SessionConfig = field(default_factory=SessionConfig)


def load_config() -> Config:
    """Load config from TOML file, override with env vars."""
    cfg = Config()

    # Load TOML if exists
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
        _apply_toml(cfg, data)

    # Env var overrides (JARVIS_LLM_MODEL, JARVIS_STT_LANGUAGE, etc.)
    _apply_env(cfg)

    # Set API keys from config or env
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        # Try config file
        if _CONFIG_FILE.exists():
            with open(_CONFIG_FILE, "rb") as f:
                data = tomllib.load(f)
            key_from_toml = data.get("keys", {}).get("openai")
            if key_from_toml:
                os.environ["OPENAI_API_KEY"] = key_from_toml

    return cfg


def ensure_config_dir() -> Path:
    """Create config dir and write default config if missing."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not _CONFIG_FILE.exists():
        _CONFIG_FILE.write_text(_DEFAULT_TOML)
    return _CONFIG_DIR


def _apply_toml(cfg: Config, data: dict) -> None:
    for key, val in data.get("audio", {}).items():
        if hasattr(cfg.audio, key):
            setattr(cfg.audio, key, val)
    for key, val in data.get("stt", {}).items():
        if hasattr(cfg.stt, key):
            setattr(cfg.stt, key, val)
    for key, val in data.get("llm", {}).items():
        if hasattr(cfg.llm, key):
            setattr(cfg.llm, key, val)
    for key, val in data.get("tts", {}).items():
        if hasattr(cfg.tts, key):
            setattr(cfg.tts, key, val)
    for key, val in data.get("session", {}).items():
        if hasattr(cfg.session, key):
            setattr(cfg.session, key, val)


def _apply_env(cfg: Config) -> None:
    _env = os.environ.get
    if v := _env("JARVIS_DEVICE_IN"): cfg.audio.device_in = v
    if v := _env("JARVIS_DEVICE_OUT"): cfg.audio.device_out = v
    if v := _env("JARVIS_CLAP_THRESHOLD"): cfg.audio.clap_threshold = int(v)
    if v := _env("JARVIS_STT_MODEL"): cfg.stt.model = v
    if v := _env("JARVIS_STT_LANGUAGE"): cfg.stt.language = v
    if v := _env("JARVIS_LLM_MODEL"): cfg.llm.model = v
    if v := _env("JARVIS_TTS_MODEL"): cfg.tts.model = v
    if v := _env("JARVIS_TTS_VOICE"): cfg.tts.voice = v
    if v := _env("JARVIS_INACTIVITY_TIMEOUT"): cfg.session.inactivity_timeout = float(v)


_DEFAULT_TOML = """\
# Jarvis configuration
# See: https://github.com/alvax64/JarvisClaw

[audio]
# device_in = "default"
# device_out = "default"
clap_threshold = 3000
clap_cooldown = 1.5

[stt]
provider = "openai"
model = "gpt-4o-mini-transcribe"
language = "es"

[llm]
provider = "openai"
model = "gpt-4o-mini"

[tts]
provider = "openai"
model = "tts-1"
voice = "onyx"

[session]
inactivity_timeout = 8.0

[keys]
# openai = "sk-..."
"""
