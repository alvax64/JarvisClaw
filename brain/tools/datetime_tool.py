"""Tool: current date and time."""

import datetime
from zoneinfo import ZoneInfo

_DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def get_current_datetime(timezone: str = "America/Lima") -> str:
    """Return current date and time as a human-readable Spanish string."""
    try:
        tz = ZoneInfo(timezone)
    except KeyError:
        tz = ZoneInfo("UTC")

    now = datetime.datetime.now(tz)
    return (
        f"Hoy es {_DAYS_ES[now.weekday()]} {now.day} de {_MONTHS_ES[now.month - 1]} "
        f"de {now.year}. Son las {now.strftime('%H:%M')} horas."
    )
