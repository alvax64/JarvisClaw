"""Tools: Linux desktop control — clipboard, volume, brightness, notifications."""

import asyncio

from livekit.agents import function_tool, RunContext


async def _run(cmd: str, timeout: int = 5) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = stdout.decode().strip()
        err = stderr.decode().strip()
        if proc.returncode != 0:
            return f"Failed: {err or out}"
        return out or "OK"
    except asyncio.TimeoutError:
        return "Timed out."
    except Exception as e:
        return str(e)


@function_tool(
    name="clipboard_read",
    description="Read the current clipboard contents.",
)
async def clipboard_read(context: RunContext) -> str:
    """Read clipboard text using wl-paste (Wayland)."""
    return await _run("wl-paste --no-newline 2>/dev/null || xclip -selection clipboard -o 2>/dev/null")


@function_tool(
    name="clipboard_write",
    description="Write text to the clipboard.",
)
async def clipboard_write(context: RunContext, text: str) -> str:
    """Write text to clipboard.

    Args:
        text: The text to copy to clipboard.
    """
    # Use printf to handle special chars safely
    return await _run(f"printf '%s' {_shell_quote(text)} | wl-copy 2>/dev/null || printf '%s' {_shell_quote(text)} | xclip -selection clipboard")


@function_tool(
    name="set_volume",
    description="Set the system audio volume (0-100) or mute/unmute.",
)
async def set_volume(context: RunContext, level: str) -> str:
    """Set volume level.

    Args:
        level: Volume level (0-100), 'mute', or 'unmute'.
    """
    match level.lower():
        case "mute":
            return await _run("wpctl set-mute @DEFAULT_AUDIO_SINK@ 1")
        case "unmute":
            return await _run("wpctl set-mute @DEFAULT_AUDIO_SINK@ 0")
        case _:
            pct = level.rstrip("%")
            return await _run(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {pct}%")


@function_tool(
    name="get_volume",
    description="Get the current system audio volume.",
)
async def get_volume(context: RunContext) -> str:
    """Get current volume level."""
    return await _run("wpctl get-volume @DEFAULT_AUDIO_SINK@")


@function_tool(
    name="set_brightness",
    description="Set screen brightness (0-100).",
)
async def set_brightness(context: RunContext, level: int) -> str:
    """Set screen brightness.

    Args:
        level: Brightness percentage (0-100).
    """
    return await _run(f"brightnessctl set {level}%")


@function_tool(
    name="send_notification",
    description="Send a desktop notification.",
)
async def send_notification(context: RunContext, title: str, body: str = "") -> str:
    """Send a desktop notification via notify-send.

    Args:
        title: Notification title.
        body: Notification body text.
    """
    cmd = f"notify-send {_shell_quote(title)}"
    if body:
        cmd += f" {_shell_quote(body)}"
    return await _run(cmd)


@function_tool(
    name="media_control",
    description="Control media playback: play, pause, next, previous.",
)
async def media_control(context: RunContext, action: str) -> str:
    """Control media player via playerctl.

    Args:
        action: One of 'play', 'pause', 'toggle', 'next', 'previous', 'status'.
    """
    valid = {"play", "pause", "play-pause", "toggle", "next", "previous", "status"}
    act = action.lower().replace(" ", "-")
    if act == "toggle":
        act = "play-pause"
    if act not in valid:
        return f"Unknown action. Use: {', '.join(sorted(valid))}"
    return await _run(f"playerctl {act}")


@function_tool(
    name="open_app",
    description="Open an application by name.",
)
async def open_app(context: RunContext, app: str) -> str:
    """Launch an application.

    Args:
        app: Application name or command, e.g. 'firefox', 'nautilus', 'code'.
    """
    # Detach so it doesn't block
    return await _run(f"setsid {app} >/dev/null 2>&1 &", timeout=3)


def _shell_quote(s: str) -> str:
    """Quote a string for safe shell interpolation."""
    return "'" + s.replace("'", "'\\''") + "'"
