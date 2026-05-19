"""OpenWeather API — current conditions and forecast for trip planning."""

import os
from datetime import date, datetime

import httpx

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
BASE_URL = "https://api.openweathermap.org/data/2.5"


async def get_forecast(lat: float, lng: float) -> dict:
    """
    Fetch the 5-day / 3-hour forecast and return a concise summary for today.
    Falls back to current conditions if no today slots are available.
    """
    if not OPENWEATHER_API_KEY:
        return _empty_weather()

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{BASE_URL}/forecast",
            params={
                "lat": lat,
                "lon": lng,
                "appid": OPENWEATHER_API_KEY,
                "units": "imperial",
                "cnt": 16,  # ~48 hours of 3-hour slots
            },
        )
        resp.raise_for_status()
        data = resp.json()

    today = date.today()
    slots = []
    for item in data.get("list", []):
        dt = datetime.fromtimestamp(item["dt"])
        if dt.date() != today:
            continue
        slots.append({
            "time": dt.strftime("%I:%M %p"),
            "temp_f": round(item["main"]["temp"]),
            "feels_like_f": round(item["main"]["feels_like"]),
            "description": item["weather"][0]["description"],
            "icon": item["weather"][0]["icon"],
            "pop": round(item.get("pop", 0) * 100),  # precipitation probability %
            "wind_mph": round(item["wind"]["speed"]),
        })

    if not slots:
        return await get_current_weather(lat, lng)

    avg_temp = round(sum(s["temp_f"] for s in slots) / len(slots))
    max_pop = max(s["pop"] for s in slots)
    descriptions = list({s["description"] for s in slots})

    return {
        "date": today.strftime("%A, %B %d"),
        "avg_temp_f": avg_temp,
        "high_f": max(s["temp_f"] for s in slots),
        "low_f": min(s["temp_f"] for s in slots),
        "max_precip_pct": max_pop,
        "descriptions": descriptions,
        "summary": _build_summary(avg_temp, max_pop, descriptions),
        "hourly": slots,
        "city": data.get("city", {}).get("name", ""),
    }


async def get_current_weather(lat: float, lng: float) -> dict:
    """Fetch current weather conditions as a fallback."""
    if not OPENWEATHER_API_KEY:
        return _empty_weather()

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{BASE_URL}/weather",
            params={
                "lat": lat,
                "lon": lng,
                "appid": OPENWEATHER_API_KEY,
                "units": "imperial",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    temp = round(data["main"]["temp"])
    description = data["weather"][0]["description"]

    return {
        "date": date.today().strftime("%A, %B %d"),
        "avg_temp_f": temp,
        "high_f": round(data["main"]["temp_max"]),
        "low_f": round(data["main"]["temp_min"]),
        "max_precip_pct": 0,
        "descriptions": [description],
        "summary": _build_summary(temp, 0, [description]),
        "hourly": [],
        "city": data.get("name", ""),
    }


def _build_summary(avg_temp: int, max_pop: int, descriptions: list[str]) -> str:
    desc = descriptions[0] if descriptions else "clear skies"
    rain_note = f" Rain chance up to {max_pop}% — bring a layer." if max_pop > 30 else ""
    return f"{avg_temp}°F and {desc}.{rain_note}"


def _empty_weather() -> dict:
    return {
        "date": date.today().strftime("%A, %B %d"),
        "avg_temp_f": None,
        "high_f": None,
        "low_f": None,
        "max_precip_pct": 0,
        "descriptions": [],
        "summary": "Weather data unavailable.",
        "hourly": [],
        "city": "",
    }
