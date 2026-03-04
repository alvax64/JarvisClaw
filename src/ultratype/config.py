"""Configuration management for UltraType."""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w

CONFIG_DIR = Path.home() / ".config" / "ultratype"
CONFIG_PATH = CONFIG_DIR / "config.toml"
DATA_DIR = Path.home() / ".local" / "share" / "ultratype"
MODELS_DIR = DATA_DIR / "models"

DEFAULT_CORRECTION_PROMPT = (
    "You are a text corrector. You receive raw speech-to-text output. "
    "Fix all spelling, grammar, and punctuation errors. Improve clarity "
    "and readability while preserving the original meaning and intent. "
    "Do not add, remove, or change the meaning of any sentence. "
    "Return ONLY the corrected text, nothing else."
)

DEFAULT_TRANSLATION_PROMPT = (
    "You are a translator. Translate the following text from "
    "{source_language} to {target_language}. Preserve tone and intent. "
    "Return ONLY the translated text, nothing else."
)


@dataclass
class GeneralConfig:
    notification: bool = True


@dataclass
class RecordingConfig:
    sample_rate: int = 16000
    channels: int = 1
    format: str = "s16"
    device: str = "default"


@dataclass
class WhisperConfig:
    model_path: str = ""
    model_name: str = "ggml-base.bin"
    language: str = "es"
    extra_args: str = ""


@dataclass
class LLMConfig:
    provider: str = "gemini"
    api_key: str = ""
    model: str = "gemini-2.0-flash-lite"
    endpoint: str = ""
    timeout: int = 10
    correction_prompt: str = DEFAULT_CORRECTION_PROMPT
    translation_prompt: str = DEFAULT_TRANSLATION_PROMPT


@dataclass
class TranslationConfig:
    source_language: str = "Spanish"
    target_language: str = "English"


@dataclass
class KeybindsConfig:
    push_to_talk: str = "SUPER, D"
    dictate: str = "SUPER SHIFT, D"
    stop: str = "SUPER SHIFT, F"
    translate: str = "SUPER SHIFT, E"
    backend: str = "static"  # static | hyprland


@dataclass
class InjectionConfig:
    method: str = "wtype"


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    keybinds: KeybindsConfig = field(default_factory=KeybindsConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)


def _merge_dict(defaults: dict, overrides: dict) -> dict:
    """Recursively merge overrides into defaults."""
    result = defaults.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_config(config: Config) -> Config:
    """Resolve dynamic defaults (paths, env vars)."""
    # Model path
    if not config.whisper.model_path:
        config.whisper.model_path = str(MODELS_DIR / config.whisper.model_name)

    # API key from env var takes precedence
    env_key = os.environ.get("ULTRATYPE_API_KEY", "")
    if env_key:
        config.llm.api_key = env_key

    return config


def load_config() -> Config:
    """Load config from disk, creating defaults if missing."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    defaults = asdict(Config())

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            user_data = tomllib.load(f)
        merged = _merge_dict(defaults, user_data)
    else:
        merged = defaults
        # Write defaults on first run
        save_config(Config())

    config = Config(
        general=GeneralConfig(**merged["general"]),
        recording=RecordingConfig(**merged["recording"]),
        whisper=WhisperConfig(**merged["whisper"]),
        llm=LLMConfig(**merged["llm"]),
        translation=TranslationConfig(**merged["translation"]),
        keybinds=KeybindsConfig(**merged["keybinds"]),
        injection=InjectionConfig(**merged["injection"]),
    )

    return _resolve_config(config)


def save_config(config: Config) -> None:
    """Write config to TOML file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(data, f)
