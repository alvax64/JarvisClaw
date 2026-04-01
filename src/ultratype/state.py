"""State machine for UltraType."""

from __future__ import annotations

import enum
import json
import time
from pathlib import Path
from typing import Callable

STATE_FILE = Path("/tmp/ultratype_state.json")


class State(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    ERROR = "error"
    # Jarvis-specific states
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    AWAITING = "awaiting"


class StateManager:
    """Manages application state with atomic file-based persistence."""

    def __init__(self) -> None:
        self._state: State = State.IDLE
        self._message: str = ""
        self._timestamp: float = 0.0
        self._callbacks: list[Callable[[State, str], None]] = []

    @property
    def state(self) -> State:
        return self._state

    @property
    def message(self) -> str:
        return self._message

    def set(self, state: State, message: str = "") -> None:
        """Transition to a new state, write state file, fire callbacks."""
        self._state = state
        self._message = message
        self._timestamp = time.time()
        self._write_state_file()
        for cb in self._callbacks:
            cb(state, message)

    def on_change(self, callback: Callable[[State, str], None]) -> None:
        """Register a state change callback."""
        self._callbacks.append(callback)

    def _write_state_file(self) -> None:
        """Atomically write state to JSON file."""
        data = {
            "state": self._state.value,
            "message": self._message,
            "timestamp": self._timestamp,
        }
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.rename(STATE_FILE)

    def cleanup(self) -> None:
        """Remove state file on daemon exit."""
        STATE_FILE.unlink(missing_ok=True)
        STATE_FILE.with_suffix(".tmp").unlink(missing_ok=True)
