"""Waybar custom module integration."""

from __future__ import annotations

import asyncio
import json

from ultratype.state import STATE_FILE, State

_ICONS = {
    State.IDLE: "\uf130",        #
    State.RECORDING: "\uf111",   #
    State.PROCESSING: "\uf013",  #
    State.ERROR: "\uf071",       #
}


def _read_state() -> dict:
    """Read state file and return Waybar-compatible JSON."""
    try:
        data = json.loads(STATE_FILE.read_text())
        state = State(data["state"])
        message = data.get("message", "")
    except (FileNotFoundError, json.JSONDecodeError, ValueError, KeyError):
        state = State.IDLE
        message = "Daemon not running"

    icon = _ICONS.get(state, "")
    text = icon
    if state == State.RECORDING:
        text = f"{icon} REC"

    tooltip = f"UltraType: {state.value}"
    if message:
        tooltip += f"\n{message}"

    return {
        "text": text,
        "tooltip": tooltip,
        "class": state.value,
    }


async def print_status(watch: bool = False, waybar: bool = True) -> None:
    """Print status for Waybar or human consumption."""
    if not watch:
        data = _read_state()
        if waybar:
            print(json.dumps(data), flush=True)
        else:
            print(f"State: {data['class']}")
            if data["tooltip"]:
                print(f"Info:  {data['tooltip']}")
        return

    # Watch mode: poll every 500ms, only print on change
    last_output = ""
    while True:
        data = _read_state()
        output = json.dumps(data)
        if output != last_output:
            print(output, flush=True)
            last_output = output
        await asyncio.sleep(0.5)
