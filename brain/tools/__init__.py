"""Jarvis tools — registered with the AgentSession for LLM function calling."""

from brain.tools.datetime_tool import get_current_datetime
from brain.tools.weather_tool import get_weather
from brain.tools.system_tool import run_command, get_screenshot


def get_tools() -> list:
    return [
        get_current_datetime,
        get_weather,
        run_command,
        get_screenshot,
    ]
