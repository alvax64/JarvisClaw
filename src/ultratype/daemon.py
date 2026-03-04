"""UltraType daemon — background service with IPC and keybind registration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

from ultratype.config import Config, load_config
from ultratype.injector import Injector
from ultratype.llm import LLMClient
from ultratype.notify import notify, notify_state_change
from ultratype.recorder import Recorder
from ultratype.state import State, StateManager
from ultratype.transcriber import Transcriber

log = logging.getLogger(__name__)


def _keybind_to_hyprland(key_str: str) -> str:
    """Convert human-readable keybind like 'Fn + D' to Hyprland format 'FN,D'."""
    parts = [p.strip().upper() for p in key_str.split("+")]
    if len(parts) < 2:
        return key_str
    mods = parts[:-1]
    key = parts[-1]
    mod_map = {
        "SUPER": "SUPER",
        "CTRL": "CTRL",
        "CONTROL": "CTRL",
        "ALT": "ALT",
        "SHIFT": "SHIFT",
        "FN": "FN",
    }
    hypr_mods = " ".join(mod_map.get(m, m) for m in mods)
    return f"{hypr_mods},{key}"


class Daemon:
    """Background daemon that manages the recording/processing pipeline."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._state = StateManager()
        self._recorder = Recorder(config.recording)
        self._transcriber = Transcriber(config.whisper)
        self._injector = Injector()
        self._socket_path = Path(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp")
        ) / "ultratype.sock"
        self._server: asyncio.Server | None = None
        self._registered_binds: list[str] = []

    async def run(self) -> None:
        """Start the daemon: register keybinds, open IPC socket, wait."""
        if self._config.general.notification:
            self._state.on_change(
                lambda s, m: asyncio.get_event_loop().create_task(
                    notify_state_change(s, m)
                )
            )

        if not self._transcriber.check_model():
            model = self._config.whisper.model_path
            print(f"Error: Model not found at {model}", file=sys.stderr)
            print(
                "Run: ultratype model download "
                f"{self._config.whisper.model_name.replace('.bin', '').replace('ggml-', '')}",
                file=sys.stderr,
            )
            sys.exit(1)

        self._socket_path.unlink(missing_ok=True)

        if self._config.keybinds.backend == "hyprland":
            await self._register_keybinds()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.ensure_future(self.shutdown())
            )

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._socket_path)
        )
        os.chmod(self._socket_path, 0o600)

        self._state.set(State.IDLE, "Ready")
        print(f"UltraType daemon listening on {self._socket_path}")

        async with self._server:
            await self._server.serve_forever()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single IPC command."""
        try:
            data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            command = data.decode().strip()
            response = await self._dispatch(command)
            writer.write(json.dumps(response).encode())
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass  # Client disconnected, that's fine
        except Exception as e:
            log.exception("IPC handler error")
            try:
                writer.write(json.dumps({"error": str(e)}).encode())
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError, OSError):
                pass

    async def _dispatch(self, command: str) -> dict:
        """Dispatch IPC commands. Returns immediately for long-running ops."""
        match command:
            case "dictate":
                return await self._start_recording()
            case "stop":
                return self._begin_processing(translate=False)
            case "translate":
                return self._begin_processing(translate=True)
            case "status":
                return {
                    "ok": True,
                    "state": self._state.state.value,
                    "message": self._state.message,
                }
            case "reload":
                self._config = load_config()
                self._recorder = Recorder(self._config.recording)
                self._transcriber = Transcriber(self._config.whisper)
                return {"ok": True, "message": "Config reloaded"}
            case "shutdown":
                asyncio.get_running_loop().call_soon(
                    lambda: asyncio.ensure_future(self.shutdown())
                )
                return {"ok": True, "message": "Shutting down"}
            case _:
                return {"error": f"Unknown command: {command}"}

    async def _start_recording(self) -> dict:
        """Start recording if idle. No-op if already recording."""
        if self._state.state == State.RECORDING:
            return {"ok": True, "state": "recording", "message": "Already recording"}
        if self._state.state != State.IDLE:
            return {"ok": False, "error": f"Cannot record in state {self._state.state.value}"}

        try:
            await self._recorder.start()
            self._state.set(State.RECORDING, "Recording...")
            return {"ok": True, "state": "recording"}
        except Exception as e:
            self._state.set(State.ERROR, str(e))
            return {"ok": False, "error": str(e)}

    def _begin_processing(self, translate: bool = False) -> dict:
        """Ack immediately, run the processing pipeline in the background."""
        if self._state.state == State.IDLE:
            return {"ok": True, "message": "Nothing to stop"}
        if self._state.state != State.RECORDING:
            return {"ok": False, "error": f"Cannot stop in state {self._state.state.value}"}

        # Fire-and-forget: process in background so IPC response is instant
        asyncio.get_event_loop().create_task(self._process_pipeline(translate))
        return {"ok": True, "state": "processing"}

    async def _process_pipeline(self, translate: bool = False) -> None:
        """Stop recording, transcribe, optionally post-process/translate, inject."""
        wav_path = await self._recorder.stop()
        self._state.set(State.PROCESSING, "Transcribing...")

        try:
            text = await self._transcriber.transcribe(wav_path)

            if not text or text.strip("[] ").upper() in ("BLANK_AUDIO", "BLANK AUDIO", ""):
                self._state.set(State.IDLE, "No speech detected")
                return

            # LLM post-processing
            if self._config.llm.api_key or os.environ.get("ULTRATYPE_API_KEY"):
                try:
                    async with LLMClient(self._config.llm) as llm:
                        text = await llm.post_process(text)
                        if translate:
                            text = await llm.translate(
                                text, self._config.translation
                            )
                except Exception as e:
                    log.warning("LLM post-processing failed, using raw text: %s", e)
                    if self._config.general.notification:
                        await notify(
                            "LLM Error",
                            f"Using raw transcription: {e}",
                            urgency="normal",
                        )

            # Inject
            await self._injector.inject(text)
            self._state.set(State.IDLE, f"Typed: {text[:80]}")

        except Exception as e:
            log.exception("Processing failed")
            self._state.set(State.ERROR, str(e))
            await asyncio.sleep(3)
            self._state.set(State.IDLE)
        finally:
            Recorder.cleanup(wav_path)

    async def _register_keybinds(self) -> None:
        """Register keybinds with Hyprland."""
        binds = {
            "dictate": self._config.keybinds.dictate,
            "stop": self._config.keybinds.stop,
            "translate": self._config.keybinds.translate,
        }
        for action, key_str in binds.items():
            if not key_str:
                continue
            hypr_bind = _keybind_to_hyprland(key_str)
            cmd = f"hyprctl keyword bind {hypr_bind},exec,ultratype {action}"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                log.warning("Failed to register keybind %s: %s", key_str, stderr.decode().strip())
            else:
                self._registered_binds.append(hypr_bind)
                log.info("Registered keybind: %s -> ultratype %s", key_str, action)

    async def _unregister_keybinds(self) -> None:
        """Remove keybinds from Hyprland."""
        for hypr_bind in self._registered_binds:
            cmd = f"hyprctl keyword unbind {hypr_bind}"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        self._registered_binds.clear()

    async def shutdown(self) -> None:
        """Clean shutdown."""
        log.info("Shutting down...")
        if self._recorder.is_recording:
            wav_path = await self._recorder.stop()
            Recorder.cleanup(wav_path)
        await self._unregister_keybinds()
        self._state.cleanup()
        self._socket_path.unlink(missing_ok=True)
        if self._server:
            self._server.close()


async def run_daemon() -> None:
    """Entry point for 'ultratype daemon'."""
    config = load_config()
    daemon = Daemon(config)
    await daemon.run()


async def send_command(command: str) -> dict:
    """Send a command to the running daemon via Unix socket."""
    socket_path = Path(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    ) / "ultratype.sock"

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
        return {"error": "Daemon not running. Start with: ultratype daemon"}
