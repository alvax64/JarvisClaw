# UltraType

System-wide push-to-talk dictation for Wayland/Hyprland on Arch Linux.

Speak → transcribe locally via whisper.cpp → clean up with an LLM → type into any focused app.

```
Mic → pw-record → WAV → whisper-cli → raw text → LLM API → clean text → wtype
```

---

## Features

- **Push-to-talk or toggle recording** — hold a key or set-and-forget
- **Local transcription** — whisper.cpp runs entirely on-device, no audio leaves your machine
- **LLM post-processing** — fixes spelling, grammar, and punctuation via a cheap API call (default: `gemini-2.0-flash-lite`)
- **On-demand translation** — stop-and-translate in one keystroke (default: Spanish → English)
- **Wayland-native** — PipeWire for audio, `wtype` for text injection, no X11 dependency
- **Waybar integration** — live status widget with click actions
- **Zero background resource use** — daemon is IO-bound and idles at ~0% CPU
- **Multi-provider LLM** — Gemini, OpenAI, Anthropic, Ollama, or any OpenAI-compatible endpoint

---

## Requirements

### System packages

```bash
# Arch Linux
sudo pacman -S python pipewire wtype libnotify

# whisper-cli (whisper.cpp) from AUR
yay -S whisper.cpp
```

Verify the binaries are on your PATH:

```bash
which pw-record whisper-cli wtype notify-send
```

### Python

Requires Python ≥ 3.12. The package uses only two third-party libraries: `httpx` (async HTTP) and `tomli-w` (TOML writing). The optional GTK4 settings GUI requires `PyGObject` from the system.

---

## Installation

```bash
# Clone
git clone https://github.com/youruser/ultratype.git
cd ultratype

# Install with uv (recommended — uses system Python for PyGObject access)
uv tool install -e . --force --python /usr/bin/python

# Allow access to system site-packages (needed for PyGObject GUI)
sed -i 's/include-system-site-packages = false/include-system-site-packages = true/' \
  ~/.local/share/uv/tools/ultratype/pyvenv.cfg
```

Verify:

```bash
ultratype --version
```

---

## First-time setup

### 1. Download a Whisper model

```bash
# List available models
ultratype model list

# Download the base model (~148 MB, good balance of speed/accuracy)
ultratype model download base

# For Spanish or multilingual use, avoid .en variants
# Recommended: base (fast) or small (better accuracy)
ultratype model download small
```

Models are stored in `~/.local/share/ultratype/models/`.

### 2. Configure your LLM API key

```bash
# Via config file (persists across sessions)
ultratype config set llm.api_key YOUR_GEMINI_API_KEY

# Or via environment variable (takes precedence)
export ULTRATYPE_API_KEY=YOUR_GEMINI_API_KEY
```

Get a free Gemini API key at [aistudio.google.com](https://aistudio.google.com). The default model (`gemini-2.0-flash-lite`) is the cheapest available and more than capable for text correction.

LLM post-processing is **optional** — if no API key is set, the raw whisper transcription is injected directly.

### 3. Set the Whisper language

```bash
# Default is Spanish. Change to your language code:
ultratype config set whisper.language en   # English
ultratype config set whisper.language fr   # French
```

### 4. Start the daemon

```bash
ultratype daemon
```

The daemon must be running for keybind commands to work. For autostart on login, see [Hyprland autostart](#hyprland-integration) below.

---

## Usage

### CLI commands

```
ultratype daemon         Start the background daemon
ultratype dictate        Start recording (toggle mode)
ultratype stop           Stop recording → transcribe → inject
ultratype translate      Stop recording → transcribe → translate → inject
ultratype status         Show current state (human-readable)
ultratype status --waybar --watch   Waybar JSON output, streaming
```

### Config management

```bash
ultratype config show              Print current config (TOML)
ultratype config set KEY VALUE     Set a config value
ultratype config edit              Open config in $EDITOR
```

### Model management

```bash
ultratype model list               List models and download status
ultratype model download NAME      Download a model (e.g., base, small, large-v3)
```

### Settings GUI

```bash
ultratype settings                 Open GTK4 settings window
```

---

## Keybinds

Default keybinds for Hyprland (add to `~/.config/hypr/conf/custom.conf` or equivalent):

```ini
# Push-to-talk: record while key is held
bind   = SUPER, D, exec, ultratype dictate
bindr  = SUPER, D, exec, ultratype stop

# Toggle dictate: start recording, keep going until stopped
bind   = SUPER SHIFT, D, exec, ultratype dictate

# Stop and inject
bind   = SUPER SHIFT, F, exec, ultratype stop

# Stop, translate (ES→EN), and inject
bind   = SUPER SHIFT, E, exec, ultratype translate
```

| Keybind | Action |
|---|---|
| `SUPER + D` (hold) | Push-to-talk |
| `SUPER + SHIFT + D` | Toggle dictation |
| `SUPER + SHIFT + F` | Stop → inject |
| `SUPER + SHIFT + E` | Stop → translate → inject |

---

## Configuration

Config file: `~/.config/ultratype/config.toml`

Generated automatically on first run. Edit directly or use `ultratype config set KEY VALUE`.

```toml
[general]
notification = true          # Desktop notifications on state changes

[recording]
sample_rate = 16000          # Hz (whisper requires 16 kHz)
channels = 1                 # Mono
format = "s16"               # 16-bit signed PCM
device = "default"           # PipeWire device name

[whisper]
model_name = "ggml-base.bin"
model_path = ""              # Auto-resolved from model_name if empty
language = "es"              # BCP-47 language code for transcription
extra_args = ""              # Extra flags passed to whisper-cli

[llm]
provider = "gemini"          # gemini | openai | anthropic | ollama | custom
api_key = ""                 # Or set ULTRATYPE_API_KEY env var
model = "gemini-2.0-flash-lite"
endpoint = ""                # Override default API endpoint
timeout = 10                 # Seconds
correction_prompt = "..."    # System prompt for grammar/spelling correction
translation_prompt = "..."   # System prompt template for translation

[translation]
source_language = "Spanish"
target_language = "English"

[keybinds]
backend = "static"           # static (manual hyprland.conf) | hyprland (runtime hyprctl)
push_to_talk = "SUPER, D"
dictate = "SUPER SHIFT, D"
stop = "SUPER SHIFT, F"
translate = "SUPER SHIFT, E"

[injection]
method = "wtype"             # Currently only wtype is supported
```

### LLM providers

| Provider | `provider` value | Notes |
|---|---|---|
| Google Gemini | `gemini` | Default. Free tier available. |
| OpenAI | `openai` | GPT-4o-mini is cheap and capable. |
| Anthropic | `anthropic` | Claude Haiku is fast and affordable. |
| Ollama | `ollama` | Fully local. Set `model` to your Ollama model name. |
| Custom OpenAI-compat | `custom` | Set `endpoint` to your API URL. |

Example: switch to Ollama with `llama3.2`:

```bash
ultratype config set llm.provider ollama
ultratype config set llm.model llama3.2
# No API key needed for Ollama
```

---

## Waybar integration

Copy the sample config and merge it into your Waybar modules:

```bash
cat waybar/ultratype.sample.json
```

```json
{
    "custom/ultratype": {
        "exec": "ultratype status --waybar --watch",
        "return-type": "json",
        "on-click": "ultratype dictate",
        "on-click-middle": "ultratype stop",
        "on-click-right": "ultratype translate",
        "format": "{}",
        "tooltip": true
    }
}
```

Add `"custom/ultratype"` to your bar's `modules-left`, `modules-center`, or `modules-right`.

State classes for CSS theming: `idle`, `recording`, `processing`, `error`.

---

## Hyprland integration

### Autostart

```ini
# ~/.config/hypr/conf/custom.conf
exec-once = ultratype daemon
```

> Make sure you have downloaded a model (`ultratype model download base`) before enabling autostart.

### Dynamic keybind registration

Set `keybinds.backend = "hyprland"` to let the daemon register/unregister keybinds via `hyprctl` at runtime instead of relying on static config entries. Useful if you want keybinds to only exist while the daemon is running.

```bash
ultratype config set keybinds.backend hyprland
```

---

## Architecture

```
ultratype daemon  ←──────────────────────────────┐
      │                                           │
      │  Unix socket ($XDG_RUNTIME_DIR/ultratype.sock)
      │                                           │
      ▼                                    ultratype dictate
  Daemon                                   ultratype stop
  ├── StateManager  ──► /tmp/ultratype_state.json  ultratype translate
  ├── Recorder      ──► pw-record → /tmp/*.wav
  ├── Transcriber   ──► whisper-cli
  ├── LLMClient     ──► HTTP API (Gemini/OpenAI/…)
  └── Injector      ──► wtype

ultratype status --waybar --watch
  └── polls /tmp/ultratype_state.json → JSON to stdout → Waybar
```

The daemon is the only long-running process. All CLI commands (`dictate`, `stop`, `translate`) are thin clients that send a single command over the Unix socket and print the JSON response. Processing runs in a background asyncio task so IPC responses are instant — the keybind feels immediate.

---

## Troubleshooting

**Daemon not running error**

```
Error: Daemon not running. Start with: ultratype daemon
```

Start the daemon in a terminal first, or add it to Hyprland autostart.

**Model not found**

```
Error: Model not found at ~/.local/share/ultratype/models/ggml-base.bin
Run: ultratype model download base
```

**No text injected after recording**

- Check `ultratype status` — if state is `error`, check the daemon terminal for the traceback.
- Ensure `wtype` is installed and the focused window accepts keyboard input.
- Try `ultratype config set whisper.language en` if you are speaking English but the model is set to `es`.

**LLM post-processing skipped**

If no API key is configured, raw transcription is injected silently. Set `llm.api_key` or `ULTRATYPE_API_KEY`.

**GTK4 settings window fails to open**

Ensure `PyGObject` is available in the UltraType virtualenv:

```bash
grep include-system-site-packages ~/.local/share/uv/tools/ultratype/pyvenv.cfg
# Should be: include-system-site-packages = true
```

---

## License

MIT
