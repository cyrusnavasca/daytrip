"""
Phase 3 Orchestrator — LangGraph multi-agent graph
====================================================
Replaces the Phase 2 monolithic orchestrator with a proper StateGraph pipeline:

  geocode → search → rag → rank → route → constraint_check
    → streaming LLM synthesis → SSE output

Graph aborts immediately after geocode if the location cannot be resolved
(conditional edge to END). All subsequent nodes treat individual tool failures
as non-fatal and degrade gracefully.

SSE event envelope (unchanged from Phase 2 — no breaking API change):
  data: {"type": "<event_type>", "payload": <value>}\n\n

Event types:
  progress   — {"message": str}         — pipeline step update
  token      — {"text": str}            — streaming LLM token
  itinerary  — Itinerary JSON object    — final parsed result
  error      — {"message": str}         — unrecoverable failure
  [DONE]     — literal string, signals stream end
"""

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator, TypedDict

from langgraph.graph import END, StateGraph
from openai import AsyncOpenAI

from app.agents.constraint_checker import run_constraint_check
from app.agents.rag_agent import run_rag
from app.agents.ranking_agent import run_ranking
from app.agents.routing_agent import run_routing
from app.agents.search_agent import run_search
from app.models.request import TripRequest
from app.tools.google_places import geocode

logger = logging.getLogger(__name__)

_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


# ── Graph state schema ─────────────────────────────────────────────────────────

class TripState(TypedDict):
    # ── Fixed input ────────────────────────────────────────────────────────────
    request: TripRequest
    trip_id: str

    # ── Geocode node ───────────────────────────────────────────────────────────
    lat: float | None
    lng: float | None
    city: str

    # ── Search node ────────────────────────────────────────────────────────────
    reddit_results: list[dict]
    google_activities: list[dict]
    google_restaurants: list[dict]
    google_cafes: list[dict]
    atlas_spots: list[dict]
    weather: dict

    # ── RAG node ───────────────────────────────────────────────────────────────
    reranked_docs: list[dict]

    # ── Rank node ──────────────────────────────────────────────────────────────
    ranked_candidates: list[dict]

    # ── Route node ─────────────────────────────────────────────────────────────
    ordered_stops: list[dict]

    # ── Constraint check node ──────────────────────────────────────────────────
    constraint_warnings: list[str]

    # ── Error propagation — any node may set this to abort synthesis ───────────
    error: str | None


# ── Progress messages per node ─────────────────────────────────────────────────

_NODE_PROGRESS: dict[str, str] = {
    "geocode":           "📍 Locating your destination…",
    "search":            "🔍 Scouring Reddit, Google Places, and Atlas Obscura…",
    "rag":               "🧠 Embedding and semantically ranking local intel…",
    "rank":              "⭐ Scoring stops by vibe, cost, rating, and uniqueness…",
    "route":             "🗺️ Optimizing your route and computing travel times…",
    "constraint_check":  "✅ Validating budget and pacing…",
}


# ── Synthesis system prompt ────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a hyper-local, opinionated day-trip planner. An intelligent agent pipeline \
has already selected, scored, and route-optimized the stops below. Your job is to write \
a vivid, readable itinerary narrative — NOT a generic tourist brochure.

OUTPUT RULES
============
- Output ONLY a single valid JSON object. No markdown, no prose outside the JSON.
- Include ALL pre-selected stops in the exact order provided. Do not add or remove stops.
- Write rich descriptions: weave in specific Reddit quotes or reviewer language when \
  the intel section contains relevant content. 2–4 sentences per stop.
- Add exactly 2 alternative suggestions per stop (different places with a similar vibe).
- Do not hallucinate addresses, coordinates, or costs — use only what is provided.
- If weather data is available, incorporate a one-sentence advisory into weather_note.
- Start times must begin at the estimated_arrival provided for each stop.

JSON SCHEMA (output exactly this shape — no extra keys):
{
  "trip_id": "<trip_id>",
  "summary": "<2–3 sentences capturing the spirit/theme of this day trip>",
  "stops": [
    {
      "time": "10:00 AM",
      "name": "Place Name",
      "description": "<What to do/see/eat here. Quote Reddit if relevant. 2–4 sentences.>",
      "address": "123 Main St, City, CA 93101",
      "estimated_cost": 15.00,
      "travel_time_to_next": "8 min",
      "lat": 34.4208,
      "lng": -119.6982,
      "category": "activity | food | coffee | hidden_gem | nature | shopping",
      "alternatives": ["Backup Option A", "Backup Option B"]
    }
  ],
  "total_estimated_cost": 75.00,
  "weather_note": "<one sentence, or empty string if no weather data>",
  "warnings": ["Any pacing, budget, or hours-of-operation warnings"]
}
"""


# ── LangGraph node functions ───────────────────────────────────────────────────

async def _geocode_node(state: TripState) -> dict:
    try:
        lat, lng = await geocode(state["request"].location)
        city = state["request"].location.split(",")[0].strip()
        return {"lat": lat, "lng": lng, "city": city}
    except Exception as exc:
        logger.exception("Geocoding failed for '%s'", state["request"].location)
        return {"error": f"Could not locate '{state['request'].location}': {exc}"}


async def _search_node(state: TripState) -> dict:
    return await run_search(state)  # type: ignore[arg-type]


async def _rag_node(state: TripState) -> dict:
    return await run_rag(state)  # type: ignore[arg-type]


def _rank_node(state: TripState) -> dict:
    return run_ranking(state)  # type: ignore[arg-type]


async def _route_node(state: TripState) -> dict:
    return await run_routing(state)  # type: ignore[arg-type]


def _constraint_node(state: TripState) -> dict:
    return run_constraint_check(state)  # type: ignore[arg-type]


# ── Conditional edge: abort on geocode failure ────────────────────────────────

def _after_geocode(state: TripState) -> str:
    """Route to 'search' on success, END immediately on geocode failure."""
    return END if state.get("error") else "search"


# ── Graph construction ─────────────────────────────────────────────────────────

def _build_graph():
    builder = StateGraph(TripState)

    builder.add_node("geocode",          _geocode_node)
    builder.add_node("search",           _search_node)
    builder.add_node("rag",              _rag_node)
    builder.add_node("rank",             _rank_node)
    builder.add_node("route",            _route_node)
    builder.add_node("constraint_check", _constraint_node)

    builder.set_entry_point("geocode")

    # After geocode: abort if error, else continue to search
    builder.add_conditional_edges(
        "geocode",
        _after_geocode,
        {END: END, "search": "search"},
    )

    builder.add_edge("search",           "rag")
    builder.add_edge("rag",              "rank")
    builder.add_edge("rank",             "route")
    builder.add_edge("route",            "constraint_check")
    builder.add_edge("constraint_check", END)

    return builder.compile()


# ── Public entry point ─────────────────────────────────────────────────────────

async def run_trip_plan(request: TripRequest) -> AsyncGenerator[str, None]:
    """
    Execute the full Phase 3 pipeline and yield SSE-formatted strings.
    Called directly by FastAPI StreamingResponse — interface is identical to Phase 2.
    """
    trip_id = str(uuid.uuid4())
    graph = _build_graph()

    initial_state: TripState = {
        "request": request,
        "trip_id": trip_id,
        "lat": None,
        "lng": None,
        "city": "",
        "reddit_results": [],
        "google_activities": [],
        "google_restaurants": [],
        "google_cafes": [],
        "atlas_spots": [],
        "weather": {},
        "reranked_docs": [],
        "ranked_candidates": [],
        "ordered_stops": [],
        "constraint_warnings": [],
        "error": None,
    }

    # ── Run LangGraph graph — emit SSE progress per node ──────────────────────
    accumulated: dict = dict(initial_state)

    async for update in graph.astream(initial_state, stream_mode="updates"):
        # Each update is {node_name: partial_state_dict}
        for node_name, node_output in update.items():
            if node_name.startswith("__"):
                # LangGraph internal bookkeeping keys (e.g. __end__)
                continue

            accumulated.update(node_output)

            # Geocode failure → abort with error SSE immediately
            if accumulated.get("error"):
                yield _sse("error", {"message": accumulated["error"]})
                return

            msg = _NODE_PROGRESS.get(node_name)
            if msg:
                yield _sse("progress", {"message": msg})

    final_state: dict = accumulated

    # ── Streaming LLM synthesis ────────────────────────────────────────────────
    yield _sse("progress", {"message": "✨ Crafting your personalized itinerary…"})

    context = _build_synthesis_context(final_state)
    full_response = ""

    try:
        stream = await _openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            temperature=0.7,
            max_tokens=3000,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_response += delta
                yield _sse("token", {"text": delta})
    except Exception as exc:
        logger.exception("OpenAI streaming synthesis failed")
        yield _sse("error", {"message": f"LLM synthesis failed: {exc}"})
        return

    # ── Parse, enrich warnings, emit final itinerary ──────────────────────────
    itinerary = _parse_itinerary(full_response, trip_id)

    # Merge constraint-checker warnings into the LLM-produced warnings list
    constraint_warnings = final_state.get("constraint_warnings", [])
    if constraint_warnings:
        itinerary.setdefault("warnings", [])
        itinerary["warnings"] = list(
            dict.fromkeys(itinerary["warnings"] + constraint_warnings)  # dedupe, preserve order
        )

    yield _sse("itinerary", itinerary)

    # ── Persist trip (best-effort, non-blocking) ───────────────────────────────
    asyncio.create_task(_save_trip(request, itinerary))

    yield "data: [DONE]\n\n"


# ── Synthesis context builder ──────────────────────────────────────────────────

def _build_synthesis_context(state: dict) -> str:
    """
    Assemble a rich, structured prompt context from the accumulated graph state.
    The LLM receives pre-selected, ordered stops and only needs to write
    narratives — it does not need to pick or sequence stops.
    """
    request: TripRequest = state["request"]
    trip_id: str = state["trip_id"]
    lat: float = state.get("lat") or 0.0
    lng: float = state.get("lng") or 0.0
    weather: dict = state.get("weather") or {}
    reranked_docs: list[dict] = state.get("reranked_docs") or []
    ordered_stops: list[dict] = state.get("ordered_stops") or []
    constraint_warnings: list[str] = state.get("constraint_warnings") or []

    parts: list[str] = []

    # ── Request summary ────────────────────────────────────────────────────────
    parts.append(
        "## Trip Request\n"
        f"- Trip ID: {trip_id}\n"
        f"- Location: {request.location} (lat {lat:.4f}, lng {lng:.4f})\n"
        f"- Budget: ${request.budget:.0f} total\n"
        f"- Transport: {request.transport}\n"
        f"- Duration: {request.duration_hours} hours\n"
        f"- Vibe / preferences: {request.vibe}\n"
        f"- Extra constraints: {request.constraints or 'none'}"
    )

    # ── Weather ────────────────────────────────────────────────────────────────
    if weather and weather.get("summary"):
        parts.append(
            f"## Weather — {weather.get('date', 'today')}\n"
            f"{weather['summary']}\n"
            f"High {weather.get('high_f', '?')}°F / Low {weather.get('low_f', '?')}°F — "
            f"Rain chance: {weather.get('max_precip_pct', 0)}%"
        )

    # ── Semantically reranked local intel ──────────────────────────────────────
    if reranked_docs:
        parts.append(
            "## Local Intel — Top Reddit & Atlas Obscura Excerpts\n"
            "(Prioritize these in stop descriptions — quote directly where relevant)"
        )
        for doc in reranked_docs[:8]:
            content = (doc.get("content") or "")[:400].strip()
            if content:
                sim = doc.get("similarity", 0.0)
                parts.append(
                    f"**{doc.get('source', 'Thread')}** "
                    f"[relevance {sim:.2f}, type: {doc.get('type', 'unknown')}]\n"
                    f"{content}"
                )

    # ── Pre-selected, ordered stops ────────────────────────────────────────────
    if ordered_stops:
        parts.append(
            f"## Route-Optimized Stops — include ALL {len(ordered_stops)} in this exact order"
        )
        for i, stop in enumerate(ordered_stops, 1):
            lines = [
                f"### Stop {i}: {stop.get('name', 'Unknown')}",
                f"- Category:          {stop.get('category', 'activity')}",
                f"- Scheduled arrival: {stop.get('estimated_arrival', 'TBD')}",
                f"- Visit duration:    {stop.get('visit_duration_min', 60)} min",
                f"- Travel to next:    {stop.get('travel_time_to_next', 'N/A')}",
                f"- Estimated cost:    ${float(stop.get('estimated_cost') or 0):.0f}",
                f"- Address:           {stop.get('address', 'N/A')}",
                f"- Coordinates:       ({stop.get('lat', '')}, {stop.get('lng', '')})",
                f"- Rating:            {stop.get('rating', 'N/A')}",
                f"- Source:            {stop.get('source', 'N/A')}",
            ]
            if stop.get("description"):
                lines.append(f"- Note:              {str(stop['description'])[:200]}")
            parts.append("\n".join(lines))

    # ── Constraint warnings ────────────────────────────────────────────────────
    if constraint_warnings:
        parts.append(
            "## Constraint Warnings — include in the itinerary `warnings` array"
        )
        for w in constraint_warnings:
            parts.append(f"- {w}")

    # ── Final instructions ─────────────────────────────────────────────────────
    parts.append(
        "## Instructions\n"
        f"- Use trip_id: {trip_id}\n"
        f"- Include ALL {len(ordered_stops)} stops above in the exact order given\n"
        "- Use the scheduled arrival time as each stop's `time` field\n"
        "- Write 2–4 sentences per stop description; quote Reddit where possible\n"
        "- Add exactly 2 alternatives per stop\n"
        f"- Keep total_estimated_cost under ${request.budget:.0f}\n"
        "- Output valid JSON only — no additional text outside the JSON object"
    )

    return "\n\n".join(parts)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sse(event_type: str, payload: dict | str) -> str:
    return f"data: {json.dumps({'type': event_type, 'payload': payload})}\n\n"


def _parse_itinerary(raw: str, trip_id: str) -> dict:
    """
    Parse LLM output as JSON. Strips markdown fences if present.
    Returns a best-effort dict — never raises.
    """
    text = raw.strip()

    # Strip ```json ... ``` fences the model sometimes emits despite instructions
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
        logger.warning("Failed to parse LLM output as JSON; returning raw text fallback")
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
    """Best-effort background DB save — logs and swallows all errors."""
    try:
        from app.db.queries import save_trip  # lazy import — DB may not be available in dev
        await save_trip(
            query=f"{request.location} | {request.vibe} | ${request.budget:.0f}",
            itinerary_json=itinerary,
            user_id=None,
        )
    except Exception:
        logger.warning("Could not persist trip to DB (non-fatal)", exc_info=True)
