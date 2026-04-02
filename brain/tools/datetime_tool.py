"""Tool: current date and time. Recycled from nebu, stripped LiveKit decorator."""

import datetime
from zoneinfo import ZoneInfo

DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def get_current_datetime(timezone: str = "America/Lima") -> str:
    """Get current date and time in the specified timezone."""
    try:
        tz = ZoneInfo(timezone)
    except KeyError:
        tz = ZoneInfo("UTC")

    now = datetime.datetime.now(tz)
    return (
        f"Hoy es {DAYS[now.weekday()]} {now.day} de {MONTHS[now.month - 1]} de {now.year}. "
        f"Son las {now.strftime('%H:%M')} horas."
    )
