"""Jarvis voice session — state machine + providers + memory.

States:
    IDLE    → mic gated (silence), waiting for CLAP
    ACTIVE  → mic open, VAD listening, processing speech
    IDLE    ← timeout after last speech activity

Providers selected via config: openai (cloud) or local (whisper/piper).
Memory persists conversation turns to SQLite for cross-session context.
"""

import asyncio
import logging
import sys
import time

from livekit.agents import AgentSession
from livekit.plugins import silero

from brain.config import Config
from brain.memory import Memory
from brain.pipewire_io import PipeWireInput, PipeWireOutput
from brain.providers import build_stt, build_llm, build_tts

log = logging.getLogger(__name__)


class JarvisSession:
    """IDLE/ACTIVE state machine with provider selection and memory."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._pw_in = PipeWireInput(device=cfg.audio.device_in)
        self._pw_out = PipeWireOutput(device=cfg.audio.device_out)
        self._memory = Memory(max_context_turns=cfg.memory.max_context_turns)
        self._session: AgentSession | None = None
        self._active = False
        self._last_activity: float = 0.0
        self._timer_task: asyncio.Task | None = None
        self._error_count: int = 0
        self._last_user_text: str = ""
        self._last_assistant_text: str = ""

        # Wake word detection while idle
        if cfg.wakeword.enabled:
            from brain.wakeword import WakeWordDetector
            self._wakeword = WakeWordDetector(
                threshold=cfg.wakeword.threshold,
                on_detected=self.activate,
            )
            self._pw_in.set_wakeword(self._wakeword)
        else:
            self._wakeword = None

    def _build_session(self) -> AgentSession:
        from brain.tools import get_tools

        stt = build_stt(self._cfg)
        llm = build_llm(self._cfg)
        tts = build_tts(self._cfg)
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

        # Build system prompt with memory context
        tool_names = [t.__name__ for t in get_tools()]
        prompt = self._cfg.session.system_prompt
        prompt += f"\n\nAvailable tools: {', '.join(tool_names)}."

        if self._cfg.memory.enabled:
            context = self._memory.build_context()
            if context:
                prompt += f"\n\n{context}"

        session.update_instructions(prompt)

        # Track activity + capture turns for memory
        session.on("user_input_transcribed", self._on_user_input)
        session.on("conversation_item_added", self._on_assistant_response)

        return session

    async def start(self) -> None:
        try:
            self._session = self._build_session()
            await self._session.start()
            self._error_count = 0
            log.info(
                "Session started (stt=%s, llm=%s, tts=%s, memory=%s)",
                self._cfg.stt.provider, self._cfg.llm.provider,
                self._cfg.tts.provider, self._cfg.memory.enabled,
            )
        except Exception as e:
            log.error("Failed to start session: %s", e)
            raise

    async def _ensure_session(self) -> None:
        if self._session is not None:
            return
        log.warning("Rebuilding session...")
        await self.start()

    def activate(self) -> None:
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
        if not self._active:
            return

        self._active = False
        self._pw_in.close_gate()

        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

        # Save last turn to memory
        if self._cfg.memory.enabled and self._last_user_text:
            self._memory.save_turn(self._last_user_text, self._last_assistant_text)
            self._last_user_text = ""
            self._last_assistant_text = ""

        log.info("DEACTIVATED")

    @property
    def is_active(self) -> bool:
        return self._active

    def _on_user_input(self, ev, *args, **kwargs) -> None:
        self._last_activity = time.monotonic()
        self._error_count = 0
        # Capture for memory
        text = getattr(ev, "transcript", "") or getattr(ev, "text", "") or str(ev)
        if text:
            self._last_user_text = text
            log.info("User: %s", text[:80])

    def _on_assistant_response(self, ev, *args, **kwargs) -> None:
        self._last_activity = time.monotonic()
        # Capture for memory
        item = getattr(ev, "item", None)
        text = getattr(item, "text", "") if item else str(ev)
        if text:
            self._last_assistant_text = text
            log.info("Jarvis: %s", text[:80])

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

    def shutdown(self) -> None:
        self.deactivate()
        self._memory.close()


async def run_triggered(cfg: Config) -> None:
    """Main loop: read CLAP triggers from stdin, toggle activation."""

    jarvis = JarvisSession(cfg)
    await jarvis.start()

    log.info("Waiting for triggers on stdin...")

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    try:
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
    finally:
        jarvis.shutdown()
