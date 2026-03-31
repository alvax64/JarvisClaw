"""Startup greeting — Jarvis says hello when he wakes up."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime

from ultratype.config import JarvisConfig

log = logging.getLogger(__name__)

GREETING_PROMPT = (
    "You are Jarvis waking up. Generate ONE short greeting in Spanish "
    "(max 15 words). Be witty/unpredictable. Context: {time} {day_of_week}, "
    "{weather}, {location}. Output ONLY the greeting, nothing else."
)


async def _get_weather() -> tuple[str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "wttr.in/?format=%C+%t+%h+%w",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        weather = stdout.decode().strip()

        proc2 = await asyncio.create_subprocess_exec(
            "curl", "-s", "wttr.in/?format=%l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=5)
        location = stdout2.decode().strip()

        return weather or "unknown", location or "unknown"
    except Exception:
        return "unknown", "unknown"


async def generate_greeting(config: JarvisConfig) -> str | None:
    """Ask Claude to generate a startup greeting."""
    now = datetime.now()
    weather, location = await _get_weather()

    prompt = GREETING_PROMPT.format(
        time=now.strftime("%H:%M"),
        day_of_week=now.strftime("%A"),
        weather=weather,
        location=location,
    )

    cmd = [
        config.claude_binary,
        "-p", prompt,
        "--output-format", "json",
    ]

    if config.claude_model:
        cmd.extend(["--model", config.claude_model])

    env = os.environ.copy()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            log.warning("Greeting claude failed: %s", stderr.decode()[:200])
            return None

        result = json.loads(stdout.decode())
        greeting = result.get("result", "").strip()
        if greeting:
            log.info("Greeting: %s", greeting)
            return greeting
    except asyncio.TimeoutError:
        log.warning("Greeting timed out")
    except Exception as e:
        log.warning("Failed to generate greeting: %s", e)

    return None
