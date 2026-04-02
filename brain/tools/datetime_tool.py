"""Tool: current date and time."""

import datetime
from zoneinfo import ZoneInfo

from livekit.agents import function_tool, RunContext

_DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


@function_tool(
    name="get_current_datetime",
    description="Get the current date and time.",
)
async def get_current_datetime(
    context: RunContext,
    timezone: str = "America/Lima",
) -> str:
    """Get current date and time.

    Args:
        timezone: IANA timezone, e.g. 'America/Lima', 'America/Mexico_City'.
    """
    try:
        tz = ZoneInfo(timezone)
    except KeyError:
        tz = ZoneInfo("UTC")

    now = datetime.datetime.now(tz)
    return (
        f"Hoy es {_DAYS_ES[now.weekday()]} {now.day} de {_MONTHS_ES[now.month - 1]} "
        f"de {now.year}. Son las {now.strftime('%H:%M')} horas."
    )
