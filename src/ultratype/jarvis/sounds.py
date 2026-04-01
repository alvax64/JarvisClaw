"""Audio feedback sounds for Jarvis state transitions."""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

_SOUNDS_DIR = "/usr/share/sounds/freedesktop/stereo"

SOUND_LISTEN_START = f"{_SOUNDS_DIR}/device-added.oga"
SOUND_LISTEN_STOP = f"{_SOUNDS_DIR}/message.oga"
SOUND_ERROR = f"{_SOUNDS_DIR}/dialog-error.oga"
SOUND_AWAITING = f"{_SOUNDS_DIR}/message-new-instant.oga"
SOUND_DONE = f"{_SOUNDS_DIR}/complete.oga"


async def play_sound(path: str) -> None:
    """Play a sound file non-blocking via pw-play."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pw-play", path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception as e:
        log.debug("Sound playback failed: %s", e)
