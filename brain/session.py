"""Jarvis voice session — state machine + LiveKit AgentSession.

States:
    IDLE    → mic gated (silence), waiting for CLAP
    ACTIVE  → mic open, VAD listening, processing speech
    IDLE    ← timeout after last speech activity

The AgentSession stays alive across activations (preserves
conversation history). Only the audio gate toggles.
"""

import asyncio
import logging
import sys
import time

from livekit.agents import AgentSession
from livekit.plugins import openai, silero

from brain.pipewire_io import PipeWireInput, PipeWireOutput

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Jarvis, a personal voice assistant running on Linux. "
    "You are efficient, direct, and occasionally dry-witted. "
    "Respond in Spanish unless the user speaks English. "
    "Keep responses concise — this is voice, not text. "
    "You have access to tools for datetime, weather, running shell "
    "commands, and taking screenshots."
)

# Seconds of silence after last speech before going back to IDLE
INACTIVITY_TIMEOUT = 8.0


class JarvisSession:
    """Manages the IDLE/ACTIVE state machine around an AgentSession."""

    def __init__(
        self,
        *,
        device_in: str | None = None,
        device_out: str | None = None,
        llm_model: str = "gpt-4o-mini",
        stt_model: str = "gpt-4o-mini-transcribe",
        tts_model: str = "tts-1",
        tts_voice: str = "onyx",
        inactivity_timeout: float = INACTIVITY_TIMEOUT,
    ) -> None:
        self._pw_in = PipeWireInput(device=device_in)
        self._pw_out = PipeWireOutput(device=device_out)
        self._timeout = inactivity_timeout
        self._last_activity: float = 0.0
        self._active = False
        self._timer_task: asyncio.Task | None = None

        from brain.tools import get_tools

        stt = openai.STT(model=stt_model, language="es")
        llm = openai.LLM(model=llm_model)
        tts = openai.TTS(model=tts_model, voice=tts_voice)
        vad = silero.VAD.load()

        self._session = AgentSession(
            stt=stt,
            llm=llm,
            tts=tts,
            vad=vad,
            turn_detection="vad",
            allow_interruptions=True,
            min_interruption_duration=0.5,
        )

        self._session.input.audio = self._pw_in
        self._session.output.audio = self._pw_out

        for tool in get_tools():
            self._session.register_tool(tool)

        self._session.update_instructions(SYSTEM_PROMPT)

        # Track activity from session events
        self._session.on("user_input_transcribed", self._on_activity)
        self._session.on("conversation_item_added", self._on_activity)

    async def start(self) -> None:
        """Start the AgentSession (gate stays closed until CLAP)."""
        await self._session.start()
        log.info("Session started (IDLE, gate closed)")

    def activate(self) -> None:
        """CLAP received — open the audio gate."""
        if self._active:
            # Already active — reset the timer
            self._last_activity = time.monotonic()
            log.debug("Already active, timer reset")
            return

        self._active = True
        self._last_activity = time.monotonic()
        self._pw_in.open_gate()

        # Start inactivity timer
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = asyncio.get_event_loop().create_task(self._inactivity_loop())

        log.info("ACTIVATED — listening")

    def deactivate(self) -> None:
        """Go back to IDLE — close the audio gate."""
        if not self._active:
            return

        self._active = False
        self._pw_in.close_gate()

        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

        log.info("DEACTIVATED — idle")

    @property
    def is_active(self) -> bool:
        return self._active

    def _on_activity(self, *args, **kwargs) -> None:
        """Called on any speech/response event — resets inactivity timer."""
        self._last_activity = time.monotonic()

    async def _inactivity_loop(self) -> None:
        """Check for inactivity, deactivate when timeout is reached."""
        try:
            while self._active:
                await asyncio.sleep(1.0)
                elapsed = time.monotonic() - self._last_activity
                if elapsed >= self._timeout:
                    log.info("Inactivity timeout (%.0fs), deactivating", elapsed)
                    self.deactivate()
                    return
        except asyncio.CancelledError:
            pass


async def run_triggered(
    *,
    device_in: str | None = None,
    device_out: str | None = None,
    **kwargs,
) -> None:
    """Main loop: read CLAP triggers from stdin, toggle activation."""

    jarvis = JarvisSession(
        device_in=device_in,
        device_out=device_out,
        **kwargs,
    )
    await jarvis.start()

    log.info("Waiting for CLAP triggers on stdin...")

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break

        text = line.decode().strip()
        if "CLAP" not in text:
            continue

        log.info("Trigger: %s", text)

        if jarvis.is_active:
            # Double-clap while active = deactivate (toggle)
            jarvis.deactivate()
        else:
            jarvis.activate()
