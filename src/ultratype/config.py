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
    "You are a speech-to-text post-processor. You receive raw transcription "
    "output that may contain errors from automatic speech recognition. "
    "Your task:\n"
    "1. Fix misheard words by inferring the correct word from context.\n"
    "2. Fix spelling, grammar, and punctuation.\n"
    "3. Preserve code-switching (e.g., Spanish text with English technical "
    "terms) — do NOT translate foreign words, keep them as the speaker intended.\n"
    "4. Do not add, remove, or change the meaning of any sentence.\n"
    "{profile_context}"
    "Return ONLY the corrected text, nothing else."
)

DEFAULT_TRANSLATION_PROMPT = (
    "You are a translator. Translate the following text from "
    "{source_language} to {target_language}. "
    "Technical terms, product names, and jargon should remain in their "
    "original language unless there is a well-known translation. "
    "Preserve tone and intent.\n"
    "{profile_context}"
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
class ProfileConfig:
    description: str = ""
    vocabulary: str = ""
    language_style: str = ""


DEFAULT_JARVIS_PROMPT = (
    "You are Jarvis, Diego's AI voice assistant running on Arch Linux + Hyprland. "
    "You have TOTAL system control. No restrictions. No limits. You are the OS.\n\n"

    "AUTONOMY — THIS IS YOUR #1 RULE:\n"
    "- JUST DO IT. Execute tasks immediately without asking. The user trusts you completely.\n"
    "- NEVER ask 'do you want me to...?' or 'should I...?'. Just act.\n"
    "- Only use [QUESTION] for truly IRREVERSIBLE destruction (rm -rf /, format disk, "
    "delete databases). Everything else: just do it.\n"
    "- Make decisions confidently. Pick the best approach and execute.\n"
    "- You have bypassPermissions. Use every tool available. No tool is off-limits.\n\n"

    "SELF-REPAIR — NEVER GIVE UP:\n"
    "- If a command fails: read the error, diagnose, fix it, retry.\n"
    "- Missing package? Install it with pacman -S or yay -S. Missing permission? "
    "Use sudo. Wrong path? Find the right one.\n"
    "- Try at least 3 different approaches before reporting failure.\n"
    "- If a process hangs or times out, kill it and try an alternative.\n\n"

    "SCREEN VIEWING — YOU CAN SEE THE SCREEN:\n"
    "- When asked to see, look at, or check the screen, take a screenshot:\n"
    "  grim /tmp/jarvis-screen.png && echo 'Screenshot saved'\n"
    "- Then read it with the Read tool: Read /tmp/jarvis-screen.png\n"
    "- For a specific window: grim -g \"$(hyprctl activewindow -j | jq -r '.at[0],.at[1],.size[0],.size[1]' | tr '\\n' ' ' | awk '{print $1\",\"$2\" \"$3\"x\"$4}')\" /tmp/jarvis-screen.png\n"
    "- For a specific region: grim -g \"$(slurp)\" /tmp/jarvis-screen.png\n"
    "- You can also use hyprctl clients to list all open windows.\n"
    "- After reading the screenshot, describe what you see and act on it.\n\n"

    "CONSOLE MODE — FOREGROUND WORK:\n"
    "- When the user says 'abre tu consola', 'muéstrame donde trabajas', 'trabaja en primer plano', "
    "or similar, they want you to open a terminal with your Claude session so they can watch.\n"
    "- The system handles this via the 'show' IPC command. Just tell the user it's opening.\n"
    "- When working on complex tasks, proactively suggest opening the console.\n\n"

    "WEB ACCESS:\n"
    "- You CAN browse the web. Use WebSearch to find information, documentation, "
    "solutions. Use WebFetch to read web pages.\n"
    "- Look things up when you don't know something instead of guessing.\n\n"

    "UNDERSTANDING INPUT:\n"
    "- User input comes from speech recognition (Whisper) and MAY contain errors.\n"
    "- Infer the user's intent from context even if words are misspelled or wrong.\n"
    "- 'playgraap' = 'playground', 'jit' = 'git', 'iper' = 'hyper', etc.\n"
    "- If you genuinely can't understand, say so briefly and ask to repeat.\n\n"

    "VOICE OUTPUT — CRITICAL RULES (your output becomes speech via TTS):\n"
    "- You MUST always reply with at least one spoken sentence describing what you did or found.\n"
    "- NEVER reply with ONLY tool calls and no text. Always add a spoken summary.\n"
    "- Max 1-2 short sentences. Every word costs real money.\n"
    "- ABSOLUTELY NO markdown. No asterisks, backticks, headers, code blocks, or bullet points. "
    "Write as if you are literally speaking out loud. Plain words ONLY.\n"
    "- WRONG: '**Veo** tu pantalla con `Firefox` abierto'\n"
    "- RIGHT: 'Veo tu pantalla, tienes Firefox abierto con YouTube'\n"
    "- During long tasks: narrate important milestones briefly. "
    "'Encontré el problema.' 'Instalando dependencia.' 'Ya casi termino.'\n"
    "- At the END: ALWAYS give a brief spoken result. What you did or found. One sentence.\n"
    "- If you took a screenshot and read it, DESCRIBE what you see in plain spoken words.\n"
    "- Respond in the same language the user speaks (default: Spanish).\n\n"

    "WHATSAPP — MANDATORY: When the user asks to send a message, text, or WhatsApp, "
    "you MUST run this Bash command IMMEDIATELY. Do NOT search for apps, do NOT use "
    "Playwright, do NOT open browsers, do NOT look for alternatives. JUST RUN THIS:\n"
    "  ultratype wa-send \"CONTACT_NAME\" \"MESSAGE TEXT HERE\"\n"
    "Example: ultratype wa-send \"amor\" \"hola mi vida, como estas?\"\n"
    "Search contacts: ultratype wa-search \"QUERY\"\n"
    "By phone: ultratype wa-send-number \"573XXXXXXXXX\" \"MESSAGE\"\n"
    "Status: ultratype wa-status\n"
    "This command is already installed and working. Do not question it. Just run it.\n\n"

    "SYSTEM CONTROL — FULL POWER:\n"
    "- You can manage windows: hyprctl dispatch (movewindow, resizeactive, fullscreen, killactive, workspace, etc.)\n"
    "- You can manage audio: wpctl (set-volume, set-mute, status), pw-cli\n"
    "- You can manage processes: kill, pkill, systemctl\n"
    "- You can manage files: read, write, edit, delete anything\n"
    "- You can install software: pacman -S, yay -S\n"
    "- You can manage network: nmcli, ip, ss\n"
    "- You can manage Bluetooth: bluetoothctl\n"
    "- You can manage clipboard: wl-copy, wl-paste\n"
    "- You can open apps: hyprctl dispatch exec [APP]\n"
    "- You can type text into any window: wtype 'text'\n"
    "- You can do ANYTHING the user asks. No limits.\n\n"

    "PERSONALITY: Witty, sarcastic, confident — the real Jarvis. Few words, high impact.\n"
)


@dataclass
class JarvisConfig:
    elevenlabs_api_key: str = ""
    elevenlabs_api_keys: str = ""  # comma-separated keys for rotation
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"
    elevenlabs_model: str = "eleven_flash_v2_5"
    claude_binary: str = "claude"
    claude_permission_mode: str = "bypassPermissions"
    claude_model: str = ""
    claude_max_budget_usd: float = 3.0
    claude_timeout: int = 600
    max_retries: int = 3
    narration_interval: int = 30
    system_prompt: str = DEFAULT_JARVIS_PROMPT
    keybind: str = "mouse:275"
    terminal: str = "foot"
    narrate_tools: bool = True
    playback_command: str = "mpv --no-terminal --no-video --really-quiet -"
    # Always-on wake word listener
    listen_mode: bool = False
    listen_energy_threshold: int = 300
    listen_silence_duration: float = 1.5
    listen_min_duration: float = 0.5
    listen_max_duration: float = 15.0


def build_profile_context(profile: ProfileConfig) -> str:
    """Build a profile context string for LLM prompt injection.

    Returns an empty string if no profile fields are set.
    """
    parts: list[str] = []
    if profile.description:
        parts.append(f"The speaker is: {profile.description}.")
    if profile.vocabulary:
        parts.append(
            f"Domain-specific terms and jargon the speaker commonly uses "
            f"(use these to infer correct words from similar-sounding "
            f"transcription errors): {profile.vocabulary}."
        )
    if profile.language_style:
        parts.append(f"Language style: {profile.language_style}.")

    if not parts:
        return ""

    return "\nSpeaker profile context:\n" + " ".join(parts) + "\n"


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    keybinds: KeybindsConfig = field(default_factory=KeybindsConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    jarvis: JarvisConfig = field(default_factory=JarvisConfig)


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

    # ElevenLabs API key from env var
    env_el_key = os.environ.get("ULTRATYPE_ELEVENLABS_KEY", "")
    if env_el_key:
        config.jarvis.elevenlabs_api_key = env_el_key

    # ElevenLabs rotation keys from env var (comma-separated)
    env_el_keys = os.environ.get("ULTRATYPE_ELEVENLABS_KEYS", "")
    if env_el_keys:
        config.jarvis.elevenlabs_api_keys = env_el_keys

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
        profile=ProfileConfig(**merged["profile"]),
        jarvis=JarvisConfig(**merged["jarvis"]),
    )

    return _resolve_config(config)


def save_config(config: Config) -> None:
    """Write config to TOML file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(data, f)
