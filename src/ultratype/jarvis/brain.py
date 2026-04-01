"""Claude Code CLI interface — the brain of Jarvis."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Literal

from ultratype.config import CONFIG_DIR, JarvisConfig, LLMConfig
from ultratype.jarvis.memory import build_memory_prompt, extract_and_save

log = logging.getLogger(__name__)

SESSION_FILE = CONFIG_DIR / "jarvis_session.id"


@dataclass
class BrainEvent:
    type: Literal["text", "tool_use", "tool_result", "done", "error", "narration"]
    content: str = ""
    cost_usd: float = 0.0


class ClaudeBrain:
    """Interface to Claude Code CLI for voice-driven system control."""

    def __init__(self, config: JarvisConfig, llm_config: LLMConfig | None = None) -> None:
        self._config = config
        self._llm_config = llm_config
        self._session_id: str | None = self._load_session()
        self._current_activity: str = "Idle"
        self._process: asyncio.subprocess.Process | None = None
        self._console_process: asyncio.subprocess.Process | None = None
        self._last_event_time: float = 0.0
        self._error_count: int = 0
        log.info("Jarvis brain initialized. Session: %s", self._session_id or "NEW")

    @property
    def current_activity(self) -> str:
        return self._current_activity

    @property
    def session_id(self) -> str:
        return self._session_id or "none"

    @property
    def is_busy(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def think(self, user_text: str) -> AsyncIterator[BrainEvent]:
        """Send a prompt to Claude Code and yield streaming events."""
        self._current_activity = "Pensando en tu solicitud..."
        self._last_event_time = time.monotonic()
        start_time = time.monotonic()

        cmd = [
            self._config.claude_binary,
            "-p", user_text,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-mode", self._config.claude_permission_mode,
            "--system-prompt", build_memory_prompt(self._config.system_prompt),
        ]

        # Only resume if we have a known-good session
        if self._session_id:
            cmd.extend(["--resume", self._session_id])

        if self._config.claude_model:
            cmd.extend(["--model", self._config.claude_model])

        if self._config.claude_max_budget_usd > 0:
            cmd.extend(["--max-budget-usd", str(self._config.claude_max_budget_usd)])

        log.info("Spawning Claude (resume=%s): %s", bool(self._session_id), " ".join(cmd[:8]) + "...")

        env = os.environ.copy()

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(Path.home()),
            )
        except FileNotFoundError:
            self._current_activity = "Error: Claude no encontrado"
            yield BrainEvent(type="error", content=f"No encontré el binario de Claude: {self._config.claude_binary}")
            return

        assert self._process.stdout is not None

        seen_text = ""
        seen_tools: set[str] = set()
        timeout = self._config.claude_timeout
        narration_interval = self._config.narration_interval
        got_session = False

        try:
            while True:
                # Check overall timeout
                elapsed = time.monotonic() - start_time
                if elapsed > timeout:
                    log.warning("Claude process timed out after %ds", timeout)
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        self._process.kill()
                    yield BrainEvent(
                        type="error",
                        content=f"Se agotó el tiempo después de {timeout} segundos. Puede que la tarea sea muy pesada.",
                    )
                    break

                # Read with timeout for narration
                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=narration_interval,
                    )
                except asyncio.TimeoutError:
                    # No output for a while — narrate current activity
                    silence = time.monotonic() - self._last_event_time
                    if self._current_activity and self._current_activity != "Idle":
                        narration = self._silence_narration(silence)
                        yield BrainEvent(type="narration", content=narration)
                    continue

                if not line:
                    break  # Process ended (EOF)

                self._last_event_time = time.monotonic()
                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    event = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                # Capture session ID from init event
                if event_type == "system" and event.get("subtype") == "init":
                    new_session = event.get("session_id", "")
                    if new_session:
                        self._session_id = new_session
                        self._save_session()
                        got_session = True
                        log.info("Session established: %s", self._session_id)
                    continue

                if event_type == "assistant":
                    message = event.get("message", {})
                    content_blocks = message.get("content", [])

                    for block in content_blocks:
                        block_type = block.get("type", "")

                        if block_type == "text":
                            full_text = block.get("text", "")
                            if len(full_text) > len(seen_text):
                                delta = full_text[len(seen_text):]
                                seen_text = full_text
                                yield BrainEvent(type="text", content=delta)

                        elif block_type == "tool_use":
                            tool_id = block.get("id", "")
                            if tool_id and tool_id not in seen_tools:
                                seen_tools.add(tool_id)
                                tool_name = block.get("name", "unknown")
                                tool_input = block.get("input", {})
                                narration = self._narrate_tool(tool_name, tool_input)
                                self._current_activity = narration
                                yield BrainEvent(type="tool_use", content=narration)

                elif event_type == "result":
                    is_error = event.get("is_error", False)
                    error_list = event.get("errors", [])

                    # Check if resume failed (session not found)
                    if is_error and any("No conversation found" in e for e in error_list):
                        log.warning("Session expired or invalid, will start fresh next time")
                        self._session_id = None
                        self._clear_session_file()
                        yield BrainEvent(type="error", content="Sesión expirada, reiniciando.")
                        break

                    cost = event.get("total_cost_usd", 0.0)
                    # Capture session_id from result too
                    result_session = event.get("session_id", "")
                    if result_session and not got_session:
                        self._session_id = result_session
                        self._save_session()
                        log.info("Session from result: %s", self._session_id)

                    self._error_count = 0
                    yield BrainEvent(type="done", cost_usd=cost)

        except Exception as e:
            yield BrainEvent(type="error", content=str(e))

        await self._process.wait()

        if self._process.returncode and self._process.returncode != 0:
            stderr_bytes = await self._process.stderr.read() if self._process.stderr else b""
            stderr_text = stderr_bytes.decode().strip()
            if stderr_text:
                log.warning("Claude stderr: %s", stderr_text[:500])
                yield BrainEvent(type="error", content=stderr_text[:200])
            self._error_count += 1

        self._process = None
        self._current_activity = "Idle"

        # Extract and save memories in background
        if self._llm_config and seen_text:
            asyncio.get_event_loop().create_task(
                self._save_memories(user_text, seen_text)
            )

    async def _save_memories(self, user_text: str, assistant_text: str) -> None:
        """Extract and save memories from the conversation (background task)."""
        try:
            await extract_and_save(user_text, assistant_text, self._llm_config)
        except Exception as e:
            log.warning("Memory save failed (non-critical): %s", e)

    async def cancel(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
            self._current_activity = "Cancelado"

    async def show_console(self) -> None:
        """Open a terminal with the Claude session so the user can watch/interact."""
        if not self._session_id:
            log.warning("No session to show — need at least one interaction first")
            return
        terminal = self._config.terminal
        cmd = (
            f'{terminal} -e {self._config.claude_binary}'
            f' --resume {self._session_id}'
            f' --permission-mode {self._config.claude_permission_mode}'
        )
        log.info("Opening console: %s", cmd)
        self._console_process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )

    async def close_console(self) -> None:
        if self._console_process and self._console_process.returncode is None:
            self._console_process.terminate()
            self._console_process = None

    def _silence_narration(self, silence_seconds: float) -> str:
        """Generate a narration for long silences based on current activity."""
        activity = self._current_activity.lower()
        mins = int(silence_seconds // 60)

        if "ejecutando" in activity:
            if mins >= 2:
                return f"Sigo trabajando. Llevo {mins} minutos en esto."
            return "Sigo ejecutando, dame un momento."
        elif "leyendo" in activity or "buscando" in activity:
            return "Sigo investigando, un momento."
        elif "editando" in activity or "creando" in activity:
            return "Sigo haciendo cambios."
        else:
            if mins >= 2:
                return f"Sigo trabajando. Llevo {mins} minutos."
            return "Sigo en eso, espérame."

    def _narrate_tool(self, tool_name: str, tool_input: dict) -> str:
        match tool_name:
            case "Bash":
                cmd = tool_input.get("command", "")
                if len(cmd) > 60:
                    cmd = cmd[:57] + "..."
                return f"Ejecutando: {cmd}"
            case "Read":
                return f"Leyendo {Path(tool_input.get('file_path', '')).name}"
            case "Edit":
                return f"Editando {Path(tool_input.get('file_path', '')).name}"
            case "Write":
                return f"Creando {Path(tool_input.get('file_path', '')).name}"
            case "Glob":
                return "Buscando archivos"
            case "Grep":
                return "Buscando en código"
            case "WebSearch":
                query = tool_input.get("query", "")
                return f"Buscando en la web: {query[:50]}"
            case "WebFetch":
                return "Leyendo una página web"
            case "Agent":
                return "Delegando una subtarea"
            case "mcp__playwright__browser_take_screenshot":
                return "Capturando pantalla del navegador"
            case "mcp__playwright__browser_navigate":
                url = tool_input.get("url", "")
                return f"Navegando a {url[:50]}"
            case _:
                if tool_name.startswith("mcp__playwright"):
                    action = tool_name.replace("mcp__playwright__browser_", "")
                    return f"Navegador: {action}"
                return f"Usando {tool_name}"

    def reset_session(self) -> None:
        """Reset session — next call will create a fresh one."""
        self._session_id = None
        self._clear_session_file()
        self._current_activity = "Idle"
        self._error_count = 0
        log.info("Jarvis session reset")

    def _load_session(self) -> str | None:
        """Load session ID from disk, or None if no saved session."""
        if SESSION_FILE.exists():
            session_id = SESSION_FILE.read_text().strip()
            if session_id:
                log.info("Loaded saved session: %s", session_id)
                return session_id
        return None

    def _save_session(self, session_id: str | None = None) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        sid = session_id or self._session_id
        if sid:
            SESSION_FILE.write_text(sid)
            log.info("Session saved: %s", sid)

    def _clear_session_file(self) -> None:
        SESSION_FILE.unlink(missing_ok=True)
