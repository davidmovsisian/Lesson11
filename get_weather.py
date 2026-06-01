"""
Open WebUI Filter Function — Current Weather (Open-Meteo)
==========================================================
Install:  Admin Panel → Functions → (+) New Function → paste this file
Type:     Filter (inlet only)

How it works:
  - Detects when the user asks about weather for a university city
  - Step 1: Geocodes the city name using Open-Meteo's free geocoding API
            (https://geocoding-api.open-meteo.com/v1/search)
  - Step 2: Fetches current weather using coordinates from step 1
            (https://api.open-meteo.com/v1/forecast)
  - Injects temperature, wind, humidity, and conditions into the system
    prompt before the LLM responds

Requirements:
  - None. Open-Meteo is completely free, no API key, no signup.
  - Attribution required under CC BY 4.0 for non-commercial use.

Weather codes reference: https://open-meteo.com/en/docs#weathervariables
"""

import json
import urllib.request
import urllib.parse
from typing import Optional
from pydantic import BaseModel, Field

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL   = "https://api.open-meteo.com/v1/forecast"

# WMO Weather Interpretation Codes → human-readable description
# https://open-meteo.com/en/docs#weathervariables
WMO_CODES = {
    0:  "Clear sky",
    1:  "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

# Keywords triggering weather enrichment
WEATHER_KEYWORDS = [
    "weather", "temperature", "forecast", "rain", "raining",
    "snow", "snowing", "wind", "windy",
    "humidity", "humid", "sun", "sunny",
    "cloud", "cloudy", "storm", "outside",
    "umbrella", "jacket", "coat", "hot",
    "cold", "warm", "cool",
]

class Filter:
    class Valves(BaseModel):
        """Admin-configurable settings."""
        temperature_unit: str = Field(
            default="celsius",
            description="Temperature unit: 'celsius' or 'fahrenheit'.",
        )
        wind_speed_unit: str = Field(
            default="kmh",
            description="Wind speed unit: 'kmh', 'mph', 'ms', or 'kn' (knots).",
        )
        timeout_seconds: int = Field(
            default=8,
            description="Max seconds to wait for Open-Meteo responses.",
        )
        debug: bool = Field(
            default=False,
            description="Append a debug block showing geocoding result and API URLs.",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_weather_query(self, text: str) -> bool:
        """Return True if message contains a weather keyword."""
        lower = text.lower()
        return any(kw in lower for kw in WEATHER_KEYWORDS)

    def _extract_city(self, text: str) -> Optional[str]:
        """
        Best-effort city extraction from the user message.

        Strategy:
          1. Look for "in <City>" / "at <City>" / "near <City>" patterns
          2. Look for known city names directly in the message
          3. Fall back to the whole message as a search query (Open-Meteo
             geocoding is robust enough to handle this gracefully)
        """
        import re
        lower = text.lower()

        # Pattern: "weather in Oxford" / "weather at Tokyo" / "near Berlin"
        match = re.search(
            r"\b(?:in|at|near|for|of)\s+([A-Z][a-zA-Z\s\-]{2,30}?)(?:\s+university|\s+college|[?,.]|$)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()

        # Fallback: return None (caller will use full query for geocoding)
        return None

    def _geocode(self, city: str) -> Optional[dict]:
        """
        Resolve a city name to coordinates using Open-Meteo's geocoding API.
        Returns dict with latitude, longitude, name, country, timezone — or None.
        """
        params = urllib.parse.urlencode({
            "name":    city,
            "count":   1,
            "language": "en",
            "format":  "json",
        })
        url = f"{GEOCODING_URL}?{params}"
        with urllib.request.urlopen(url, timeout=self.valves.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])
        return results[0] if results else None

    def _get_weather(self, lat: float, lng: float) -> dict:
        """
        Fetch current weather from Open-Meteo for given coordinates.
        Returns the full API response dict.
        """
        temp_unit = (
            "fahrenheit"
            if self.valves.temperature_unit == "fahrenheit"
            else "celsius"
        )
        params = urllib.parse.urlencode({
            "latitude":           lat,
            "longitude":          lng,
            "current":            ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "weather_code",
                "wind_speed_10m",
                "wind_direction_10m",
                "precipitation",
                "cloud_cover",
            ]),
            "temperature_unit":   temp_unit,
            "wind_speed_unit":    self.valves.wind_speed_unit,
            "timezone":           "auto",
        })
        url = f"{WEATHER_URL}?{params}"
        with urllib.request.urlopen(url, timeout=self.valves.timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _wind_direction(self, degrees: Optional[float]) -> str:
        """Convert wind direction in degrees to compass abbreviation."""
        if degrees is None:
            return "?"
        compass = ["N","NE","E","SE","S","SW","W","NW"]
        return compass[round(degrees / 45) % 8]

    def _format_weather(self, geo: dict, weather: dict) -> str:
        """Render geocoding + weather data as a clean LLM-readable context block."""
        city_name = geo.get("name", "?")
        country   = geo.get("country", "?")
        timezone  = geo.get("timezone", "?")

        cur = weather.get("current", {})
        units = weather.get("current_units", {})

        temp        = cur.get("temperature_2m")
        feels_like  = cur.get("apparent_temperature")
        humidity    = cur.get("relative_humidity_2m")
        wind_speed  = cur.get("wind_speed_10m")
        wind_dir    = cur.get("wind_direction_10m")
        precip      = cur.get("precipitation")
        cloud       = cur.get("cloud_cover")
        wmo_code    = cur.get("weather_code")
        condition   = WMO_CODES.get(wmo_code, f"Code {wmo_code}")

        temp_u  = units.get("temperature_2m", "°C")
        wind_u  = units.get("wind_speed_10m", "km/h")
        precip_u = units.get("precipitation", "mm")

        lines = [
            "--- CURRENT WEATHER (Open-Meteo) ---",
            f"Location:    {city_name}, {country}  (timezone: {timezone})",
            f"Conditions:  {condition}",
            f"Temperature: {temp}{temp_u}  (feels like {feels_like}{temp_u})",
            f"Humidity:    {humidity}%",
            f"Wind:        {wind_speed} {wind_u}, {self._wind_direction(wind_dir)} ({wind_dir}°)",
            f"Precipitation:{precip} {precip_u}",
            f"Cloud cover: {cloud}%",
            "Source: Open-Meteo (open-meteo.com) — CC BY 4.0",
            "--- END WEATHER ---",
        ]
        return "\n".join(lines)

    # ── Inlet ─────────────────────────────────────────────────────────────────

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """
        Pre-LLM intercept.

        Checks the latest user message for a weather question. If detected:
          1. Extracts the city name from the message
          2. Geocodes it with Open-Meteo's geocoding API (no API key needed)
          3. Fetches current weather using the resolved coordinates
          4. Injects the formatted result into the system prompt

        Open-Meteo requires no authentication — the two GET requests are
        made directly without any credentials.
        """
        messages = body.get("messages", [])
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )

        if not last_user or not self._is_weather_query(last_user):
            return body  # Not a weather query — pass through

        city = self._extract_city(last_user) or last_user  # Fallback to full query for geocoding

        geocode_url = None
        weather_url = None

        try:
            geo = self._geocode(city)
            if not geo:
                context = (
                    "--- CURRENT WEATHER ---\n"
                    f"Could not geocode city '{city}'. "
                    "Please ask the user to specify the city more clearly.\n"
                    "--- END ---"
                )
            else:
                lat, lng = geo["latitude"], geo["longitude"]
                weather  = self._get_weather(lat, lng)
                context  = self._format_weather(geo, weather)

                if self.valves.debug:
                    geocode_url = (
                        f"{GEOCODING_URL}?name={urllib.parse.quote(city)}&count=1"
                    )
                    weather_url = (
                        f"{WEATHER_URL}?latitude={lat}&longitude={lng}&current=temperature_2m"
                    )

        except Exception as exc:
            context = (
                "--- CURRENT WEATHER ---\n"
                f"Open-Meteo API error: {exc}\n"
                "--- END ---"
            )

        if self.valves.debug:
            context += f"\n[DEBUG] Extracted city: '{city}'"
            if geocode_url:
                context += f"\n[DEBUG] Geocoding URL: {geocode_url}"
            if weather_url:
                context += f"\n[DEBUG] Weather URL: {weather_url}"

        enrichment = f"\n\n{context}"
        system_msg = next(
            (m for m in body["messages"] if m.get("role") == "system"), None
        )
        if system_msg:
            system_msg["content"] += enrichment
        else:
            body["messages"].insert(0, {
                "role":    "system",
                "content": (
                    "You are a helpful university assistant. "
                    "Use the weather information below when answering the user."
                    + enrichment
                ),
            })

        return body

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """Pass-through — no modification to the LLM response."""
        return body