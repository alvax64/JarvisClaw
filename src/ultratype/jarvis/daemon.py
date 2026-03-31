"""Jarvis voice assistant daemon — the main orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

from ultratype.config import Config, load_config
from ultratype.jarvis.brain import BrainEvent, ClaudeBrain
from ultratype.jarvis.greeting import generate_greeting
from ultratype.jarvis.listener import WakeWordListener
from ultratype.jarvis.sounds import (
    SOUND_AWAITING, SOUND_DONE, SOUND_ERROR,
    SOUND_LISTEN_START, SOUND_LISTEN_STOP, play_sound,
)
from ultratype.jarvis.tts import ElevenLabsTTS
from ultratype.notify import notify, notify_state_change
from ultratype.recorder import Recorder
from ultratype.state import State, StateManager
from ultratype.transcriber import Transcriber

log = logging.getLogger(__name__)

# Force debug logging for jarvis modules
logging.getLogger("ultratype.jarvis").setLevel(logging.DEBUG)

QUESTION_MARKER = "[QUESTION]"


def _keybind_to_hyprland(key_str: str) -> str:
    """Convert human-readable keybind to Hyprland format."""
    parts = [p.strip().upper() for p in key_str.split("+")]
    if len(parts) < 2:
        return key_str
    mods = parts[:-1]
    key = parts[-1]
    mod_map = {
        "SUPER": "SUPER", "CTRL": "CTRL", "CONTROL": "CTRL",
        "ALT": "ALT", "SHIFT": "SHIFT", "FN": "FN",
    }
    hypr_mods = " ".join(mod_map.get(m, m) for m in mods)
    return f"{hypr_mods},{key}"


class JarvisDaemon:
    """Voice assistant daemon that orchestrates recording, Claude, and TTS.

    Flow:
    1. SUPER+C → start listening
    2. SUPER+C again (or stop command) → stop recording, transcribe
    3. Send to Claude → Claude executes autonomously
    4. If Claude asks [QUESTION] → auto-listen for response
    5. Claude narrates progress via TTS during long tasks
    6. User can interrupt anytime to ask status or give new commands
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._state = StateManager()
        self._recorder = Recorder(config.recording)
        self._transcriber = Transcriber(config.whisper)
        self._brain = ClaudeBrain(config.jarvis, llm_config=config.llm)
        self._tts = ElevenLabsTTS(config.jarvis)
        self._socket_path = Path(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp")
        ) / "ultratype-jarvis.sock"
        self._server: asyncio.Server | None = None
        self._registered_binds: list[str] = []
        self._active_task: asyncio.Task | None = None
        self._retry_count: int = 0
        self._last_user_text: str = ""
        self._listener: WakeWordListener | None = None
        self._listener_task: asyncio.Task | None = None

    async def run(self) -> None:
        """Start the Jarvis daemon."""
        if self._config.general.notification:
            self._state.on_change(
                lambda s, m: asyncio.get_event_loop().create_task(
                    notify_state_change(s, m)
                )
            )

        if not self._transcriber.check_model():
            model = self._config.whisper.model_path
            print(f"Error: Whisper model not found at {model}", file=sys.stderr)
            sys.exit(1)

        if not self._config.jarvis.elevenlabs_api_key:
            print("Warning: No ElevenLabs API key. TTS disabled.", file=sys.stderr)
            print("Set ULTRATYPE_ELEVENLABS_KEY or jarvis.elevenlabs_api_key", file=sys.stderr)

        await self._tts.start()

        self._socket_path.unlink(missing_ok=True)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.ensure_future(self.shutdown())
            )

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._socket_path)
        )
        os.chmod(self._socket_path, 0o600)

        self._state.set(State.IDLE, "Jarvis ready")
        print(f"Jarvis daemon listening on {self._socket_path}")

        # Startup greeting
        asyncio.get_event_loop().create_task(self._startup_greeting())

        # Always-on wake word listener
        if self._config.jarvis.listen_mode:
            self._listener = WakeWordListener(
                jarvis_config=self._config.jarvis,
                recording_config=self._config.recording,
                whisper_config=self._config.whisper,
                llm_config=self._config.llm,
                on_command=self._handle_voice_command,
            )
            self._listener_task = asyncio.get_event_loop().create_task(
                self._listener.start()
            )
            log.info("Wake-word listener enabled")

        async with self._server:
            await self._server.serve_forever()

    # ── Startup greeting ───────────────────────────────────────────

    async def _startup_greeting(self) -> None:
        """Generate and speak a greeting when Jarvis starts."""
        try:
            greeting = await generate_greeting(self._config.jarvis)
            if greeting:
                if self._listener:
                    self._listener.suppress()
                self._state.set(State.SPEAKING, "Greeting...")
                await self._tts.speak(greeting)
                self._state.set(State.IDLE, "Jarvis ready")
                if self._listener:
                    self._listener.unsuppress()
        except Exception as e:
            log.warning("Greeting failed: %s", e)
            if self._listener:
                self._listener.unsuppress()

    # ── Wake-word voice command ────────────────────────────────────────

    async def _handle_voice_command(self, command: str) -> None:
        """Called by the listener when a wake-word command is detected."""
        current = self._state.state

        # Don't interrupt if already processing a command
        if current in (State.THINKING, State.TRANSCRIBING):
            log.info("Ignoring wake-word command, busy: %s", current.value)
            return

        # If speaking, stop TTS first
        if current == State.SPEAKING:
            await self._tts.stop()

        # If recording via keybind, ignore
        if current in (State.LISTENING, State.RECORDING):
            log.info("Ignoring wake-word, keybind recording active")
            return

        log.info("Wake-word command: %s", command)

        # Suppress listener during our response
        if self._listener:
            self._listener.suppress()

        try:
            await play_sound(SOUND_LISTEN_STOP)
            self._last_user_text = command
            self._retry_count = 0
            await self._conversation_turn(command)
        except Exception as e:
            log.exception("Voice command failed")
            await self._handle_pipeline_error(e)
        finally:
            if self._listener:
                self._listener.unsuppress()

    # ── IPC ──────────────────────────────────────────────────────────

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            command = data.decode().strip()
            response = await self._dispatch(command)
            writer.write(json.dumps(response).encode())
            await writer.drain()
        except Exception as e:
            log.exception("IPC error")
            try:
                writer.write(json.dumps({"error": str(e)}).encode())
                await writer.drain()
            except OSError:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass

    async def _dispatch(self, command: str) -> dict:
        match command:
            case "activate":
                return await self._handle_activate()
            case "stop":
                return await self._handle_stop()
            case "show":
                await self._brain.show_console()
                return {"ok": True, "message": "Console opened", "session": self._brain.session_id}
            case "screenshot":
                return await self._handle_screenshot()
            case "status":
                return {
                    "ok": True,
                    "state": self._state.state.value,
                    "message": self._state.message,
                    "activity": self._brain.current_activity,
                    "busy": self._brain.is_busy,
                    "session": self._brain.session_id,
                }
            case "reset":
                self._brain.reset_session()
                self._retry_count = 0
                return {"ok": True, "message": "Session reset"}
            case "listen-on":
                return await self._enable_listener()
            case "listen-off":
                return self._disable_listener()
            case "listen-status":
                active = self._listener is not None and self._listener.is_running
                return {"ok": True, "listening": active}
            case "shutdown":
                asyncio.get_running_loop().call_soon(
                    lambda: asyncio.ensure_future(self.shutdown())
                )
                return {"ok": True, "message": "Shutting down"}
            case _:
                return {"error": f"Unknown command: {command}"}

    # ── Screenshot ────────────────────────────────────────────────────

    async def _handle_screenshot(self) -> dict:
        """Take a screenshot and return the path."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "grim", "/tmp/jarvis-screen.png",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                return {"ok": True, "path": "/tmp/jarvis-screen.png"}
            return {"ok": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Activation (SUPER+C toggle) ──────────────────────────────────

    def _brain_is_busy(self) -> bool:
        """Check if there's an active pipeline (brain + TTS) running."""
        return self._active_task is not None and not self._active_task.done()

    async def _handle_activate(self) -> dict:
        """Toggle listen/process. Only one pipeline at a time."""
        current = self._state.state

        # If speaking, pause TTS to listen (work continues in background)
        if current == State.SPEAKING:
            await self._tts.stop()
            return await self._start_listening()

        # If already listening, stop recording and process
        if current in (State.LISTENING, State.RECORDING):
            if self._brain_is_busy():
                asyncio.get_event_loop().create_task(
                    self._process_voice_quick_status()
                )
            else:
                self._active_task = asyncio.get_event_loop().create_task(
                    self._process_voice()
                )
            return {"ok": True, "state": "processing"}

        # If thinking (Claude working), still let user talk
        if current == State.THINKING:
            return await self._start_listening()

        # Idle, awaiting, error — just start listening
        return await self._start_listening()

    async def _start_listening(self) -> dict:
        try:
            await play_sound(SOUND_LISTEN_START)
            await self._recorder.start()
            self._state.set(State.LISTENING, "Listening...")
            return {"ok": True, "state": "listening"}
        except Exception as e:
            self._state.set(State.ERROR, str(e))
            await play_sound(SOUND_ERROR)
            return {"ok": False, "error": str(e)}

    async def _handle_stop(self) -> dict:
        """Stop everything."""
        await self._tts.stop()
        await self._brain.cancel()
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
        if self._recorder.is_recording:
            wav_path = await self._recorder.stop()
            Recorder.cleanup(wav_path)
        self._retry_count = 0
        self._state.set(State.IDLE, "Stopped")
        return {"ok": True, "state": "idle"}

    # ── Voice processing pipeline ────────────────────────────────────

    async def _process_voice_quick_status(self) -> None:
        """Transcribe user speech and answer with current activity — no new Claude."""
        await play_sound(SOUND_LISTEN_STOP)
        wav_path = await self._recorder.stop()

        try:
            text = await self._transcriber.transcribe(wav_path)
            log.info("User asked during work: %s", text)

            activity = self._brain.current_activity or "trabajando"
            if self._listener:
                self._listener.suppress()
            self._state.set(State.SPEAKING, "Status update...")
            await self._tts.speak(f"Estoy {activity.lower()}. Espérame un momento.")

            # Restore thinking state — the brain task is still running
            if self._brain_is_busy():
                self._state.set(State.THINKING, activity)
            else:
                self._state.set(State.IDLE, "Done")
        except Exception as e:
            log.warning("Quick status failed: %s", e)
        finally:
            Recorder.cleanup(wav_path)
            if self._listener:
                self._listener.unsuppress()

    async def _process_voice(self) -> None:
        """Stop recording → transcribe → send to Claude → TTS response.

        Includes automatic retry on failure.
        """
        await play_sound(SOUND_LISTEN_STOP)
        wav_path = await self._recorder.stop()
        self._state.set(State.TRANSCRIBING, "Transcribing...")

        try:
            text = await self._transcriber.transcribe(wav_path)

            if not text or text.strip("[] ").upper() in (
                "BLANK_AUDIO", "BLANK AUDIO", ""
            ):
                self._state.set(State.IDLE, "No speech detected")
                return

            log.info("User said: %s", text)

            # If Claude is already working, add context about current activity
            activity = self._brain.current_activity
            if activity and activity != "Idle":
                text = f"[Currently working on: {activity}] User says: {text}"
                log.info("Added activity context: %s", activity)

            self._last_user_text = text
            self._retry_count = 0
            await self._conversation_turn(text)

        except asyncio.CancelledError:
            self._state.set(State.IDLE, "Cancelled")
        except Exception as e:
            log.exception("Processing failed")
            await self._handle_pipeline_error(e)
        finally:
            Recorder.cleanup(wav_path)

    async def _conversation_turn(self, user_text: str) -> None:
        """Send text to Claude, stream TTS, handle confirmations and retries."""
        if self._retry_count > 0:
            self._state.set(State.SPEAKING, "Retrying...")
            await self._tts.speak("Reintentando.")

        self._state.set(State.THINKING, "Thinking...")
        log.info("Sending to Claude (attempt %d): %s", self._retry_count + 1, user_text[:120])

        full_response = ""
        has_question = False
        spoke_text = False
        tool_count = 0
        had_error = False
        error_msg = ""

        async def text_stream():
            nonlocal full_response, has_question, spoke_text, tool_count, had_error, error_msg
            async for event in self._brain.think(user_text):
                log.debug("Brain event: type=%s content=%s", event.type, event.content[:80] if event.content else "")
                if event.type == "text":
                    clean = event.content.replace(QUESTION_MARKER, "")
                    full_response += event.content
                    if clean.strip():
                        spoke_text = True
                        yield clean
                elif event.type == "tool_use":
                    tool_count += 1
                    log.info("Claude tool #%d: %s", tool_count, event.content)
                    self._state.set(State.THINKING, event.content)
                elif event.type == "narration":
                    # Autonomous narration during long silences
                    log.info("Narration: %s", event.content)
                    yield f" {event.content} "
                elif event.type == "error":
                    log.error("Claude error: %s", event.content)
                    had_error = True
                    error_msg = event.content
                    yield f" Hubo un problema. "
                elif event.type == "done":
                    log.info("Claude done. Cost: $%.4f", event.cost_usd)

            if QUESTION_MARKER in full_response:
                has_question = True
            log.info(
                "Full response (%d chars, errors=%s): %s",
                len(full_response), had_error, full_response[:120],
            )

        # Suppress listener during TTS to avoid echo
        if self._listener:
            self._listener.suppress()

        self._state.set(State.SPEAKING, "Speaking...")
        await self._tts.speak_stream(text_stream())
        log.info(
            "TTS finished. question=%s spoke=%s tools=%d error=%s",
            has_question, spoke_text, tool_count, had_error,
        )

        # ── Handle errors with retry ──
        if had_error and not spoke_text:
            max_retries = self._config.jarvis.max_retries
            if self._retry_count < max_retries:
                self._retry_count += 1
                log.info("Retrying (attempt %d/%d)...", self._retry_count + 1, max_retries + 1)
                # Add error context for the retry
                retry_text = (
                    f"[PREVIOUS ATTEMPT FAILED: {error_msg[:200]}] "
                    f"Try a different approach. Original request: {self._last_user_text}"
                )
                await asyncio.sleep(1)
                await self._conversation_turn(retry_text)
                return
            else:
                log.warning("Max retries reached. Giving up.")
                await self._tts.speak("No pude completar la tarea después de varios intentos. Dime si quieres que lo intente de otra forma.")
                await play_sound(SOUND_ERROR)
                self._state.set(State.IDLE, "Failed after retries")
                self._retry_count = 0
                return

        # ── Handle question from Claude ──
        if has_question:
            self._state.set(State.AWAITING, "Waiting for your response...")
            await asyncio.sleep(0.3)
            try:
                await play_sound(SOUND_AWAITING)
                await self._recorder.start()
                self._state.set(State.LISTENING, "Listening for response...")
            except Exception as e:
                log.warning("Auto-listen failed: %s", e)
                self._state.set(State.IDLE)
        else:
            # Announce completion if Claude didn't already say something at the end
            if not spoke_text:
                await self._tts.speak("Listo.")
            # await play_sound(SOUND_DONE)  # disabled by user request
            # Only go IDLE if nothing else is running
            if self._brain.current_activity == "Idle":
                self._state.set(State.IDLE, "Done")
            else:
                self._state.set(State.THINKING, self._brain.current_activity)

        self._retry_count = 0

        # Re-enable listener after response
        if self._listener:
            self._listener.unsuppress()

    async def _handle_pipeline_error(self, error: Exception) -> None:
        """Handle errors in the voice pipeline with potential retry."""
        error_str = str(error)
        log.error("Pipeline error: %s", error_str)

        max_retries = self._config.jarvis.max_retries
        if self._retry_count < max_retries and self._last_user_text:
            self._retry_count += 1
            log.info(
                "Auto-retrying pipeline (attempt %d/%d)...",
                self._retry_count + 1, max_retries + 1,
            )
            self._state.set(State.SPEAKING, "Recovering...")
            await self._tts.speak("Hubo un problema, reintentando.")
            await asyncio.sleep(1)

            retry_text = (
                f"[PREVIOUS ATTEMPT FAILED: {error_str[:200]}] "
                f"Try a different approach. Original request: {self._last_user_text}"
            )
            try:
                await self._conversation_turn(retry_text)
                return
            except Exception as e2:
                log.exception("Retry also failed")

        # Give up
        self._state.set(State.ERROR, error_str[:100])
        try:
            await self._tts.speak("Hubo un error y no pude recuperarme. Intenta de nuevo.")
        except Exception:
            pass
        await play_sound(SOUND_ERROR)
        await asyncio.sleep(2)
        self._state.set(State.IDLE)
        self._retry_count = 0

    # ── Listener on/off at runtime ─────────────────────────────────────

    async def _enable_listener(self) -> dict:
        if self._listener and self._listener.is_running:
            return {"ok": True, "message": "Already listening"}
        self._listener = WakeWordListener(
            jarvis_config=self._config.jarvis,
            recording_config=self._config.recording,
            whisper_config=self._config.whisper,
            llm_config=self._config.llm,
            on_command=self._handle_voice_command,
        )
        self._listener_task = asyncio.get_event_loop().create_task(
            self._listener.start()
        )
        log.info("Wake-word listener enabled at runtime")
        return {"ok": True, "message": "Listener enabled"}

    def _disable_listener(self) -> dict:
        if self._listener:
            self._listener.stop()
            self._listener = None
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            self._listener_task = None
        log.info("Wake-word listener disabled")
        return {"ok": True, "message": "Listener disabled"}

    # ── Keybinds ─────────────────────────────────────────────────────

    async def _register_keybinds(self) -> None:
        key_str = self._config.jarvis.keybind
        if not key_str:
            return

        if "," not in key_str:
            bind_spec = f",{key_str}"
        else:
            bind_spec = key_str
        cmd = f"hyprctl keyword bind {bind_spec},exec,ultratype jarvis-activate"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("Keybind register failed %s: %s", key_str, stderr.decode().strip())
        else:
            self._registered_binds.append(key_str)
            log.info("Registered Jarvis keybind: %s", key_str)

    async def _unregister_keybinds(self) -> None:
        for bind_str in self._registered_binds:
            cmd = f"hyprctl keyword unbind {bind_str}"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        self._registered_binds.clear()

    # ── Shutdown ─────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        log.info("Jarvis shutting down...")
        # Stop listener first to release the mic
        if self._listener:
            self._listener.stop()
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
        await self._tts.stop()
        await self._tts.close()
        await self._brain.cancel()
        await self._brain.close_console()
        if self._recorder.is_recording:
            wav_path = await self._recorder.stop()
            Recorder.cleanup(wav_path)
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
        await self._unregister_keybinds()
        self._state.cleanup()
        self._socket_path.unlink(missing_ok=True)
        if self._server:
            self._server.close()


async def run_jarvis_daemon() -> None:
    """Entry point for 'ultratype jarvis'."""
    config = load_config()
    daemon = JarvisDaemon(config)
    await daemon.run()


async def send_jarvis_command(command: str) -> dict:
    """Send a command to the running Jarvis daemon via Unix socket."""
    socket_path = Path(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    ) / "ultratype-jarvis.sock"

    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        writer.write(command.encode())
        await writer.drain()

        data = await asyncio.wait_for(reader.read(4096), timeout=10.0)
        response = json.loads(data.decode())

        writer.close()
        await writer.wait_closed()
        return response
    except (ConnectionRefusedError, FileNotFoundError):
        return {"error": "Jarvis not running. Start with: ultratype jarvis"}
