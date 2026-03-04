"""Desktop notification wrapper using notify-send."""

from __future__ import annotations

import asyncio

from ultratype.state import State

_notify_id: int | None = None


async def notify(
    summary: str, body: str = "", urgency: str = "normal"
) -> None:
    """Send a desktop notification, replacing the previous UltraType one."""
    global _notify_id

    cmd = [
        "notify-send",
        "--app-name", "UltraType",
        "--urgency", urgency,
        "--print-id",
    ]
    if _notify_id is not None:
        cmd.extend(["--replace-id", str(_notify_id)])

    cmd.extend(["--", summary])
    if body:
        cmd.append(body)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()

    output = stdout.decode().strip()
    if output.isdigit():
        _notify_id = int(output)


async def notify_state_change(state: State, message: str = "") -> None:
    """Send state-appropriate notification."""
    match state:
        case State.RECORDING:
            await notify("Recording...", "Speak now", urgency="low")
        case State.PROCESSING:
            await notify("Processing...", "Transcribing audio", urgency="low")
        case State.IDLE:
            if message:
                await notify("Done", message)
        case State.ERROR:
            await notify("Error", message or "Unknown error", urgency="critical")
