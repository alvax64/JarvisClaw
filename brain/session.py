"""Jarvis voice session — wires PipeWire I/O to LiveKit AgentSession.

Reads stdin for "TIMESTAMP CLAP" triggers from jarvis-listen.
On trigger: activates the voice pipeline (VAD → STT → LLM → TTS).
"""

import asyncio
import logging
import sys

from livekit.agents import AgentSession, function_tool, RunContext
from livekit.plugins import openai, silero

from brain.pipewire_io import PipeWireInput, PipeWireOutput

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Jarvis, a personal voice assistant running on Linux. "
    "You are efficient, direct, and occasionally dry-witted. "
    "Respond in Spanish unless the user speaks English. "
    "Keep responses concise — this is voice, not text. "
    "You have access to tools for system information."
)


async def create_session(
    *,
    device_in: str | None = None,
    device_out: str | None = None,
    llm_model: str = "gpt-4o-mini",
    stt_model: str = "gpt-4o-mini-transcribe",
    tts_model: str = "tts-1",
    tts_voice: str = "onyx",
) -> AgentSession:
    """Create a configured AgentSession with PipeWire I/O."""

    from brain.tools import get_tools

    stt = openai.STT(model=stt_model, language="es")
    llm = openai.LLM(model=llm_model)
    tts = openai.TTS(model=tts_model, voice=tts_voice)
    vad = silero.VAD.load()

    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=vad,
        turn_detection="vad",
        allow_interruptions=True,
        min_interruption_duration=0.5,
    )

    # Wire PipeWire audio
    session.input.audio = PipeWireInput(device=device_in)
    session.output.audio = PipeWireOutput(device=device_out)

    # Register tools
    for tool in get_tools():
        session.register_tool(tool)

    # Set instructions
    session.update_instructions(SYSTEM_PROMPT)

    return session


async def run_triggered(
    *,
    device_in: str | None = None,
    device_out: str | None = None,
    **kwargs,
) -> None:
    """Main loop: read CLAP triggers from stdin, activate voice pipeline."""

    log.info("Jarvis brain waiting for triggers on stdin...")

    session: AgentSession | None = None

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break  # stdin closed

        text = line.decode().strip()
        if "CLAP" not in text:
            continue

        log.info("Trigger received: %s", text)

        if session is None:
            session = await create_session(
                device_in=device_in,
                device_out=device_out,
                **kwargs,
            )
            await session.start()
            log.info("Session started")
        else:
            log.info("Session already active")
