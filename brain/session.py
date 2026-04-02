"""Jarvis voice session — state machine + error recovery.

States:
    IDLE    → mic gated (silence), waiting for CLAP
    ACTIVE  → mic open, VAD listening, processing speech
    IDLE    ← timeout after last speech activity

Error recovery:
    - pw-cat dies → restart on next activation
    - paplay dies → restart on next TTS frame
    - API error  → log, deactivate, wait for next CLAP
    - Session crash → rebuild session, log error
"""

import asyncio
import logging
import sys
import time

from livekit.agents import AgentSession
from livekit.plugins import openai, silero

from brain.config import Config, load_config
from brain.pipewire_io import PipeWireInput, PipeWireOutput

log = logging.getLogger(__name__)


class JarvisSession:
    """IDLE/ACTIVE state machine with error recovery."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._pw_in = PipeWireInput(device=cfg.audio.device_in)
        self._pw_out = PipeWireOutput(device=cfg.audio.device_out)
        self._session: AgentSession | None = None
        self._active = False
        self._last_activity: float = 0.0
        self._timer_task: asyncio.Task | None = None
        self._error_count: int = 0

    def _build_session(self) -> AgentSession:
        from brain.tools import get_tools

        stt = openai.STT(model=self._cfg.stt.model, language=self._cfg.stt.language)
        llm = openai.LLM(model=self._cfg.llm.model)
        tts = openai.TTS(model=self._cfg.tts.model, voice=self._cfg.tts.voice)
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

        session.input.audio = self._pw_in
        session.output.audio = self._pw_out

        for tool in get_tools():
            session.register_tool(tool)

        # Build tool list for system prompt
        tool_names = [t.__name__ for t in get_tools()]
        prompt = self._cfg.session.system_prompt
        prompt += f"\n\nAvailable tools: {', '.join(tool_names)}."

        session.update_instructions(prompt)

        session.on("user_input_transcribed", self._on_activity)
        session.on("conversation_item_added", self._on_activity)

        return session

    async def start(self) -> None:
        """Build and start the session."""
        try:
            self._session = self._build_session()
            await self._session.start()
            self._error_count = 0
            log.info("Session started (IDLE)")
        except Exception as e:
            log.error("Failed to start session: %s", e)
            raise

    async def _ensure_session(self) -> None:
        """Rebuild session if it crashed."""
        if self._session is not None:
            return
        log.warning("Rebuilding session after error...")
        await self.start()

    def activate(self) -> None:
        """CLAP → open audio gate."""
        if self._active:
            self._last_activity = time.monotonic()
            return

        self._active = True
        self._last_activity = time.monotonic()
        self._pw_in.open_gate()

        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = asyncio.get_event_loop().create_task(
            self._inactivity_loop()
        )

        log.info("ACTIVATED")

    def deactivate(self) -> None:
        """Close audio gate → IDLE."""
        if not self._active:
            return

        self._active = False
        self._pw_in.close_gate()

        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

        log.info("DEACTIVATED")

    @property
    def is_active(self) -> bool:
        return self._active

    def _on_activity(self, *args, **kwargs) -> None:
        self._last_activity = time.monotonic()
        self._error_count = 0  # successful activity resets error count

    async def _inactivity_loop(self) -> None:
        timeout = self._cfg.session.inactivity_timeout
        try:
            while self._active:
                await asyncio.sleep(1.0)
                if time.monotonic() - self._last_activity >= timeout:
                    log.info("Inactivity timeout (%.0fs)", timeout)
                    self.deactivate()
                    return
        except asyncio.CancelledError:
            pass

    async def handle_error(self, error: Exception) -> None:
        """Handle errors with backoff. Deactivate, rebuild if needed."""
        self._error_count += 1
        log.error("Error #%d: %s", self._error_count, error)

        self.deactivate()

        if self._error_count >= 3:
            log.warning("Too many errors, rebuilding session")
            self._session = None
            await asyncio.sleep(2)
            try:
                await self.start()
                self._error_count = 0
            except Exception as e:
                log.error("Rebuild failed: %s", e)


async def run_triggered(cfg: Config) -> None:
    """Main loop: read CLAP triggers from stdin, toggle activation."""

    jarvis = JarvisSession(cfg)
    await jarvis.start()

    log.info("Waiting for triggers on stdin...")

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break

            text = line.decode().strip()
            if "CLAP" not in text:
                continue

            log.info("Trigger: %s", text)

            await jarvis._ensure_session()

            if jarvis.is_active:
                jarvis.deactivate()
            else:
                jarvis.activate()

        except Exception as e:
            await jarvis.handle_error(e)
