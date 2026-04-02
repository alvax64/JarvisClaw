"""Tool: weather via Open-Meteo (no API key required)."""

import json
import urllib.request
import urllib.parse

from livekit.agents import function_tool, RunContext

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

_WMO_ES = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado",
    3: "nublado", 45: "niebla", 48: "niebla con escarcha",
    51: "llovizna ligera", 53: "llovizna moderada", 55: "llovizna intensa",
    61: "lluvia ligera", 63: "lluvia moderada", 65: "lluvia intensa",
    71: "nieve ligera", 73: "nieve moderada", 75: "nieve intensa",
    80: "chubascos ligeros", 81: "chubascos moderados", 82: "chubascos intensos",
    95: "tormenta eléctrica", 96: "tormenta con granizo ligero",
    99: "tormenta con granizo fuerte",
}


@function_tool(
    name="get_weather",
    description="Get current weather for a city.",
)
async def get_weather(context: RunContext, city: str) -> str:
    """Get current weather for a city.

    Args:
        city: City name, e.g. 'Lima', 'Madrid', 'New York'.
    """
    try:
        params = urllib.parse.urlencode({"name": city, "count": 1, "language": "es"})
        with urllib.request.urlopen(f"{_GEOCODE_URL}?{params}", timeout=4) as r:
            geo = json.loads(r.read())

        results = geo.get("results")
        if not results:
            return f"City not found: {city}"

        lat, lon = results[0]["latitude"], results[0]["longitude"]
        name = results[0].get("name", city)

        params = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "timezone": "auto",
        })
        with urllib.request.urlopen(f"{_WEATHER_URL}?{params}", timeout=4) as r:
            weather = json.loads(r.read())

        cur = weather["current"]
        desc = _WMO_ES.get(cur["weather_code"], "variable")
        return (
            f"En {name}: {desc}, {cur['temperature_2m']}°C, "
            f"humedad {cur['relative_humidity_2m']}%, "
            f"viento {cur['wind_speed_10m']} km/h."
        )
    except Exception:
        return f"Weather lookup failed for {city}."
