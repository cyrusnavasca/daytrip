"""
Phase 2 Orchestrator
====================
Parallel tool calls → context assembly → GPT-4o streaming synthesis → SSE.

Phase 3 will replace this with a full LangGraph multi-agent graph
(Search Agent, RAG Agent, Ranking Agent, Routing Agent). This module
deliberately keeps its interface identical so the swap is non-breaking:
  routes.py calls `run_trip_plan(request)` → async generator of SSE strings.

SSE event envelope:
  data: {"type": "<event_type>", "payload": <value>}\n\n

Event types:
  progress   — {"message": str}                  — pipeline step update
  token      — {"text": str}                      — streaming LLM token
  itinerary  — Itinerary JSON object              — final parsed result
  error      — {"message": str}                   — unrecoverable failure
  [DONE]     — literal string, signals stream end
"""

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator

from openai import AsyncOpenAI

from app.models.request import TripRequest
from app.tools.atlas_obscura import search_nearby as atlas_search_nearby
from app.tools.google_places import geocode, search_nearby, search_places
from app.tools.mapbox import get_multi_leg_times, transport_to_profile
from app.tools.openweather import get_forecast
from app.tools.reddit import search_reddit

logger = logging.getLogger(__name__)

_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a hyper-local, opinionated day-trip planner. You have access to live data \
from Reddit, Google Places, Atlas Obscura, and weather APIs. Your job is to build \
a realistic, memorable itinerary — NOT a generic tourist brochure.

OUTPUT RULES
============
- Output ONLY a single valid JSON object. No markdown, no prose outside the JSON.
- If something genuinely has no matching data, make a reasonable expert recommendation.
- Prioritize Reddit-mentioned spots over generic tourist picks.
- Weave in Atlas Obscura hidden gems whenever they fit the vibe.
- Budget tracking is strict: keep a running tally across stops.
- Timing must be realistic: include travel time between stops.
- Start no earlier than 9:00 AM; end by 10:00 PM.
- Include at least one food or coffee stop appropriate to the vibe and budget.

JSON SCHEMA (output exactly this shape):
{
  "trip_id": "<uuid provided in request context>",
  "summary": "<2–3 sentences — the spirit/theme of this day trip>",
  "stops": [
    {
      "time": "10:00 AM",
      "name": "Place Name",
      "description": "<What to do/see/eat here. Mention specific Reddit quotes or reviews if available. 2–4 sentences.>",
      "address": "123 Main St, City, CA 93101",
      "estimated_cost": 15.00,
      "travel_time_to_next": "8 min",
      "lat": 34.4208,
      "lng": -119.6982,
      "category": "activity | food | coffee | hidden_gem | nature",
      "alternatives": ["Backup Option A", "Backup Option B"]
    }
  ],
  "total_estimated_cost": 75.00,
  "weather_note": "<one sentence weather advisory, or empty string>",
  "warnings": ["Any pacing, budget, or hours-of-operation warnings"]
}
"""


# ── Public entry point ─────────────────────────────────────────────────────────

async def run_trip_plan(request: TripRequest) -> AsyncGenerator[str, None]:
    """
    Full Phase 2 pipeline.
    Yields SSE-formatted strings; called directly by FastAPI StreamingResponse.
    """
    trip_id = str(uuid.uuid4())

    # ── 1. Geocode ────────────────────────────────────────────────────────────
    yield _sse("progress", {"message": "📍 Locating your destination…"})
    try:
        lat, lng = await geocode(request.location)
    except Exception as exc:
        logger.exception("Geocoding failed")
        yield _sse("error", {"message": f"Could not locate '{request.location}': {exc}"})
        return

    # ── 2. Parallel tool calls ─────────────────────────────────────────────
    yield _sse("progress", {"message": "🔍 Scouring Reddit, Google Places, and Atlas Obscura…"})

    mapbox_profile = transport_to_profile(request.transport)
    queries = _build_queries(request)

    (
        reddit_main,
        reddit_gems,
        google_activities,
        google_restaurants,
        google_cafes,
        atlas_spots,
        weather,
    ) = await asyncio.gather(
        search_reddit(queries["reddit_main"]),
        search_reddit(queries["reddit_gems"]),
        search_places(queries["google_activities"], lat, lng, radius_m=12_000),
        search_nearby(lat, lng, place_type="restaurant", radius_m=8_000),
        search_nearby(lat, lng, place_type="cafe", radius_m=5_000),
        atlas_search_nearby(lat, lng, radius_km=50),
        get_forecast(lat, lng),
        return_exceptions=True,
    )

    yield _sse("progress", {"message": "🗺️ Planning your route and timing…"})

    # ── 3. Assemble LLM context ───────────────────────────────────────────────
    context = _build_context(
        request=request,
        trip_id=trip_id,
        lat=lat,
        lng=lng,
        reddit_main=_safe(reddit_main),
        reddit_gems=_safe(reddit_gems),
        google_activities=_safe(google_activities),
        google_restaurants=_safe(google_restaurants),
        google_cafes=_safe(google_cafes),
        atlas_spots=_safe(atlas_spots),
        weather=weather if isinstance(weather, dict) else {},
    )

    # ── 4. Stream GPT-4o synthesis ────────────────────────────────────────────
    yield _sse("progress", {"message": "✨ Crafting your personalized itinerary…"})

    full_response = ""
    try:
        stream = await _openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            temperature=0.7,
            max_tokens=2500,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_response += delta
                yield _sse("token", {"text": delta})
    except Exception as exc:
        logger.exception("OpenAI streaming failed")
        yield _sse("error", {"message": f"LLM synthesis failed: {exc}"})
        return

    # ── 5. Parse + enrich with real travel times ──────────────────────────────
    itinerary = _parse_itinerary(full_response, trip_id)

    stops_with_coords = [
        s for s in itinerary.get("stops", [])
        if s.get("lat") and s.get("lng")
    ]
    if len(stops_with_coords) >= 2:
        coords = [(s["lat"], s["lng"]) for s in stops_with_coords]
        try:
            leg_times = await get_multi_leg_times(coords, profile=mapbox_profile)
            for i, stop in enumerate(stops_with_coords[:-1]):
                stop["travel_time_to_next"] = leg_times[i]
        except Exception:
            pass  # LLM-provided estimates remain if Mapbox fails

    yield _sse("itinerary", itinerary)

    # ── 6. Persist trip to DB (best-effort, non-blocking) ─────────────────────
    asyncio.create_task(_save_trip(request, itinerary))

    yield "data: [DONE]\n\n"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sse(event_type: str, payload: dict | str) -> str:
    return f"data: {json.dumps({'type': event_type, 'payload': payload})}\n\n"


def _safe(result: object) -> list:
    """Return [] if asyncio.gather returned an exception for this task."""
    if isinstance(result, (Exception, BaseException)):
        return []
    return result or []  # type: ignore[return-value]


def _build_queries(request: TripRequest) -> dict[str, str]:
    loc = request.location
    vibe = request.vibe
    return {
        "reddit_main": f"best {vibe} day trip {loc} recommendations reddit",
        "reddit_gems": f"hidden gems underrated spots {loc} local favorites",
        "google_activities": f"{vibe} things to do in {loc}",
    }


def _build_context(
    request: TripRequest,
    trip_id: str,
    lat: float,
    lng: float,
    reddit_main: list[dict],
    reddit_gems: list[dict],
    google_activities: list[dict],
    google_restaurants: list[dict],
    google_cafes: list[dict],
    atlas_spots: list[dict],
    weather: dict,
) -> str:
    parts: list[str] = []

    parts.append(
        f"## Trip Request\n"
        f"- Trip ID: {trip_id}\n"
        f"- Location: {request.location} (lat {lat:.4f}, lng {lng:.4f})\n"
        f"- Budget: ${request.budget:.0f} total\n"
        f"- Transport: {request.transport}\n"
        f"- Duration: {request.duration_hours} hours\n"
        f"- Vibe / preferences: {request.vibe}\n"
        f"- Extra constraints: {request.constraints or 'none'}\n"
    )

    if weather and weather.get("summary"):
        parts.append(
            f"## Weather — {weather.get('date', 'today')}\n"
            f"{weather['summary']}\n"
            f"High {weather.get('high_f', '?')}°F / Low {weather.get('low_f', '?')}°F — "
            f"Rain chance: {weather.get('max_precip_pct', 0)}%"
        )

    reddit_combined = (reddit_main + reddit_gems)[:10]
    if reddit_combined:
        parts.append("## Reddit Insights (prioritize these)")
        for r in reddit_combined:
            content = (r.get("content") or "")[:500].strip()
            if content:
                parts.append(
                    f"**{r.get('title', 'Thread')}** (relevance {r.get('score', 0):.2f})\n"
                    f"{content}"
                )

    if google_activities:
        parts.append("## Google Places — Activities & Attractions")
        for p in google_activities[:7]:
            price = "$" * (p.get("price_level") or 0) or "Free/unknown"
            parts.append(
                f"- {p['name']} | ⭐ {p.get('rating', 'N/A')} "
                f"({p.get('user_ratings_total', 0)} reviews) | "
                f"Price: {price} | Open now: {p.get('open_now', 'unknown')} | "
                f"Coords: ({p.get('lat', '')}, {p.get('lng', '')})"
            )

    if google_restaurants:
        parts.append("## Google Places — Restaurants")
        for p in google_restaurants[:6]:
            price = "$" * (p.get("price_level") or 0) or "unknown"
            parts.append(
                f"- {p['name']} | ⭐ {p.get('rating', 'N/A')} | "
                f"Price: {price} | Open: {p.get('open_now', 'unknown')} | "
                f"Coords: ({p.get('lat', '')}, {p.get('lng', '')})"
            )

    if google_cafes:
        parts.append("## Google Places — Cafes & Coffee")
        for p in google_cafes[:5]:
            parts.append(
                f"- {p['name']} | ⭐ {p.get('rating', 'N/A')} | "
                f"Open: {p.get('open_now', 'unknown')} | "
                f"Coords: ({p.get('lat', '')}, {p.get('lng', '')})"
            )

    if atlas_spots:
        parts.append("## Atlas Obscura — Hidden & Unique Spots (high value for local/unique vibe)")
        for s in atlas_spots[:8]:
            desc = (s.get("description") or "")[:200]
            parts.append(
                f"- **{s['name']}**: {desc} "
                f"| Coords: ({s.get('lat', '')}, {s.get('lng', '')})"
                f"| URL: {s.get('url', '')}"
            )

    parts.append(
        f"\n## Final Instructions\n"
        f"Build a {request.duration_hours}-hour itinerary for the request above.\n"
        f"- Use the exact trip_id: {trip_id}\n"
        f"- Blend Reddit recommendations with Google Places data\n"
        f"- Insert at least one Atlas Obscura gem if it fits the vibe\n"
        f"- Keep total cost under ${request.budget:.0f}\n"
        f"- Respect transport mode '{request.transport}' for timing\n"
        f"- Output valid JSON only — no additional text\n"
    )

    return "\n\n".join(parts)


def _parse_itinerary(raw: str, trip_id: str) -> dict:
    """
    Parse the LLM output as JSON. If it fails (e.g. wrapped in markdown fences),
    strip fences and retry. Returns a best-effort dict in all cases.
    """
    text = raw.strip()

    # Strip ```json ... ``` fences that the model sometimes emits despite instructions
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    try:
        itinerary = json.loads(text)
        itinerary["trip_id"] = trip_id
        return itinerary
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM output as JSON; returning raw text")
        return {
            "trip_id": trip_id,
            "summary": "Itinerary generated but could not be parsed as JSON.",
            "stops": [],
            "total_estimated_cost": 0,
            "weather_note": "",
            "warnings": ["Parse error — see raw_text field"],
            "raw_text": raw,
        }


async def _save_trip(request: TripRequest, itinerary: dict) -> None:
    """Best-effort background DB save. Logs and swallows errors."""
    try:
        from app.db.queries import save_trip  # lazy import to avoid hard crash if DB is down
        await save_trip(
            query=f"{request.location} | {request.vibe} | ${request.budget}",
            itinerary_json=itinerary,
            user_id=None,
        )
    except Exception:
        logger.warning("Could not persist trip to DB (non-fatal)", exc_info=True)
