"""
Phase 3 / 4 Orchestrator — LangGraph multi-agent graph
=======================================================
LangGraph StateGraph pipeline:

  geocode → search → rag → rank → route → constraint_check
    → streaming LLM synthesis (Phase 4) → SSE output

Phase 4 additions
-----------------
* OpenAI Structured Outputs (response_format json_schema, strict=True) — the LLM
  is hard-constrained to output exactly the Itinerary schema.  No more defensive
  fence-stripping or hoping the model follows prompt instructions.
* Full Pydantic validation + coercion of the parsed LLM response against
  app.models.response.Itinerary / Stop before the `itinerary` SSE event fires.
* _fill_missing_alternatives() — post-processing pass that draws from the
  ranked_candidates pool to ensure every stop always has exactly 2 alternatives,
  even when the LLM omits or truncates them.
* Enhanced synthesis prompt: explicit tone, strict alternatives rules, and
  practical-tip requirement per stop description.

Graph aborts immediately after geocode if the location cannot be resolved
(conditional edge to END).  All subsequent nodes treat individual tool failures
as non-fatal and degrade gracefully.

SSE event envelope (unchanged — no breaking API change):
  data: {"type": "<event_type>", "payload": <value>}\\n\\n

Event types:
  progress   — {"message": str}         — pipeline step update
  token      — {"text": str}            — streaming LLM token
  itinerary  — Itinerary JSON object    — final parsed + validated result
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
from pydantic import ValidationError

from app.agents.constraint_checker import run_constraint_check
from app.agents.rag_agent import run_rag
from app.agents.ranking_agent import run_ranking
from app.agents.routing_agent import run_routing
from app.agents.search_agent import run_search
from app.models.request import TripRequest
from app.models.response import Itinerary
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


# ── Phase 4: Structured output JSON schema ─────────────────────────────────────
# Passed as response_format to the OpenAI chat completion call.
# strict=True hard-constrains the model to exactly this shape — no extra keys,
# no missing required fields, correct enum values for category.

_ITINERARY_JSON_SCHEMA: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "itinerary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "trip_id": {"type": "string"},
                "summary": {"type": "string"},
                "stops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "time":        {"type": "string"},
                            "name":        {"type": "string"},
                            "description": {"type": "string"},
                            "address":     {"type": "string"},
                            "estimated_cost": {"type": "number"},
                            "travel_time_to_next": {
                                "anyOf": [{"type": "string"}, {"type": "null"}]
                            },
                            "lat": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                            "lng": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                            "category": {
                                "type": "string",
                                "enum": ["activity", "food", "coffee",
                                         "hidden_gem", "nature", "shopping"],
                            },
                            "alternatives": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "time", "name", "description", "address",
                            "estimated_cost", "travel_time_to_next",
                            "lat", "lng", "category", "alternatives",
                        ],
                        "additionalProperties": False,
                    },
                },
                "total_estimated_cost": {"type": "number"},
                "weather_note": {"type": "string"},
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "trip_id", "summary", "stops",
                "total_estimated_cost", "weather_note", "warnings",
            ],
            "additionalProperties": False,
        },
    },
}


# ── Phase 4: Synthesis system prompt ───────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a hyper-local, opinionated day-trip planner. The pipeline has already \
selected, scored, and route-optimized every stop — your only job is to write \
vivid, human narrative and provide smart backup options.

TONE & STYLE
============
- Write like a knowledgeable local friend, not a generic travel brochure.
- Use specific sensory detail: what you will see, smell, taste, or feel at each stop.
- Quote Reddit threads or reviewer language verbatim when the Local Intel section \
  has relevant content. Attribute inline: e.g. "One Redditor called it 'the best \
  hidden cove in the county.'"
- Each stop description: 2–4 sentences — direct, specific, and personal. \
  End with one practical tip (parking, best time of day, what to order, etc.).

STOPS
=====
- Include ALL pre-selected stops in the EXACT order provided. Do not add, remove, \
  or resequence stops.
- Use the scheduled arrival time verbatim as each stop's "time" field.
- Do NOT hallucinate addresses, coordinates, or costs — use only values provided. \
  If an address is missing, use an empty string.

ALTERNATIVES
============
- Provide exactly 2 alternatives per stop.
- Alternatives must be SPECIFIC real place names — e.g. "Handlebar Coffee", \
  "Funk Zone", "Shoreline Park". Never use generic phrases like "a nearby cafe" \
  or "another restaurant."
- Choose alternatives that share the stop's vibe and category.
- Prefer places mentioned in the Local Intel section or ranked candidates pool \
  when available.

WEATHER
=======
- If weather data is provided, write a single practical advisory sentence \
  (e.g. "Bring a light layer — highs only reach 62 °F with a 30% chance of \
  afternoon drizzle.").
- If no weather data is available, set weather_note to an empty string.

COST & WARNINGS
===============
- Set total_estimated_cost to the sum of all stop estimated_cost values.
- Copy any constraint warnings from the Constraint Warnings section verbatim \
  into the warnings array.
- Add your own warning if a stop is likely to be crowded, has seasonal hours, \
  or strongly benefits from advance booking.
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
            response_format=_ITINERARY_JSON_SCHEMA,  # Phase 4: enforce schema
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

    # ── Parse, validate, fill alternatives, enrich warnings ──────────────────
    itinerary = _parse_itinerary(full_response, trip_id, final_state)

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
    The LLM receives pre-selected ordered stops and only needs to write
    narratives and choose alternatives — it does not pick or sequence stops.

    Phase 4 additions:
    - Surfaces ranked_candidates NOT selected as ordered stops so the LLM can
      draw from them for specific alternative suggestions.
    - Expands weather section with all available fields.
    - Adds an explicit alternatives pool section.
    """
    request: TripRequest = state["request"]
    trip_id: str = state["trip_id"]
    lat: float = state.get("lat") or 0.0
    lng: float = state.get("lng") or 0.0
    weather: dict = state.get("weather") or {}
    reranked_docs: list[dict] = state.get("reranked_docs") or []
    ordered_stops: list[dict] = state.get("ordered_stops") or []
    ranked_candidates: list[dict] = state.get("ranked_candidates") or []
    constraint_warnings: list[str] = state.get("constraint_warnings") or []

    ordered_names: set[str] = {s.get("name", "") for s in ordered_stops}

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
    if weather:
        summary = weather.get("summary", "")
        high = weather.get("high_f", "?")
        low = weather.get("low_f", "?")
        precip = weather.get("max_precip_pct", 0)
        condition = weather.get("condition", "")
        date_label = weather.get("date", "today")
        weather_lines = [f"## Weather — {date_label}"]
        if summary:
            weather_lines.append(summary)
        weather_lines.append(
            f"High {high}°F / Low {low}°F — Rain chance: {precip}%"
            + (f" — {condition}" if condition else "")
        )
        parts.append("\n".join(weather_lines))

    # ── Semantically reranked local intel ──────────────────────────────────────
    if reranked_docs:
        parts.append(
            "## Local Intel — Top Reddit & Atlas Obscura Excerpts\n"
            "Weave these into stop descriptions. Quote verbatim where relevant and attribute inline."
        )
        for doc in reranked_docs[:8]:
            content = (doc.get("content") or "")[:400].strip()
            if not content:
                continue
            sim = doc.get("similarity", 0.0)
            source_label = doc.get("source") or "Thread"
            doc_type = doc.get("type", "unknown")
            parts.append(
                f"**{source_label}** [relevance {sim:.2f}, type: {doc_type}]\n{content}"
            )

    # ── Pre-selected, ordered stops ────────────────────────────────────────────
    if ordered_stops:
        parts.append(
            f"## Route-Optimized Stops — include ALL {len(ordered_stops)} in this EXACT order\n"
            "Do NOT add, remove, or resequence any stop."
        )
        for i, stop in enumerate(ordered_stops, 1):
            lines = [
                f"### Stop {i}: {stop.get('name', 'Unknown')}",
                f"- Category:          {stop.get('category', 'activity')}",
                f"- Scheduled arrival: {stop.get('estimated_arrival', 'TBD')}",
                f"- Visit duration:    {stop.get('visit_duration_min', 60)} min",
                f"- Travel to next:    {stop.get('travel_time_to_next', 'N/A')}",
                f"- Estimated cost:    ${float(stop.get('estimated_cost') or 0):.0f}",
                f"- Address:           {stop.get('address') or ''}",
                f"- Coordinates:       ({stop.get('lat', '')}, {stop.get('lng', '')})",
                f"- Rating:            {stop.get('rating', 'N/A')}",
                f"- Source:            {stop.get('source', 'N/A')}",
            ]
            if stop.get("description"):
                lines.append(f"- Note:              {str(stop['description'])[:200]}")
            parts.append("\n".join(lines))

    # ── Alternatives pool (Phase 4) ────────────────────────────────────────────
    # Provide unused ranked candidates so the LLM has real place names to draw from.
    alt_pool = [c for c in ranked_candidates if c.get("name") not in ordered_names]
    if alt_pool:
        pool_lines = ["## Alternatives Pool — use these for stop 'alternatives' fields"]
        pool_lines.append(
            "Prefer names from this list (real scored candidates). "
            "Pick alternatives with the same category/vibe as the stop."
        )
        for c in alt_pool[:20]:
            name = c.get("name", "")
            cat = c.get("category", "")
            addr = c.get("address", "")
            if name:
                pool_lines.append(f"- {name} [{cat}]{(' — ' + addr) if addr else ''}")
        parts.append("\n".join(pool_lines))

    # ── Constraint warnings ────────────────────────────────────────────────────
    if constraint_warnings:
        parts.append(
            "## Constraint Warnings — copy these verbatim into the `warnings` array"
        )
        for w in constraint_warnings:
            parts.append(f"- {w}")

    # ── Final instructions ─────────────────────────────────────────────────────
    parts.append(
        "## Instructions\n"
        f"- Use trip_id exactly: {trip_id}\n"
        f"- Include ALL {len(ordered_stops)} stops in the exact order given above\n"
        "- Use each stop's 'Scheduled arrival' as its `time` field\n"
        "- Write 2–4 sentences per description; end with one practical tip\n"
        "- alternatives: exactly 2 specific real place names drawn from the pool above\n"
        f"- total_estimated_cost must equal the sum of all stop estimated_cost values\n"
        f"- Budget ceiling: ${request.budget:.0f}"
    )

    return "\n\n".join(parts)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sse(event_type: str, payload: dict | str) -> str:
    return f"data: {json.dumps({'type': event_type, 'payload': payload})}\n\n"


def _fill_missing_alternatives(
    itinerary: dict,
    ranked_candidates: list[dict],
    ordered_stop_names: set[str],
) -> dict:
    """
    Phase 4 post-processing: ensure every stop has exactly 2 alternatives.

    Strategy:
    1. Collect ranked_candidates not selected as ordered stops, grouped by category.
    2. For each stop with < 2 alternatives, fill from same-category candidates first,
       then cross-category if needed.
    3. Deduplicate against existing alternatives and the stop's own name.
    """
    # Build pool: unused candidates keyed by category
    pool_by_category: dict[str, list[str]] = {}
    pool_all: list[str] = []
    seen_in_pool: set[str] = set()

    for candidate in ranked_candidates:
        name = (candidate.get("name") or "").strip()
        if not name or name in ordered_stop_names:
            continue
        cat = candidate.get("category") or "activity"
        if name not in seen_in_pool:
            pool_by_category.setdefault(cat, []).append(name)
            pool_all.append(name)
            seen_in_pool.add(name)

    for stop in itinerary.get("stops", []):
        existing_alts: list[str] = [
            a.strip() for a in (stop.get("alternatives") or []) if a.strip()
        ]
        if len(existing_alts) >= 2:
            stop["alternatives"] = existing_alts[:2]
            continue

        needed = 2 - len(existing_alts)
        used_names: set[str] = set(existing_alts) | {stop.get("name", "")}
        cat = stop.get("category") or "activity"

        # Same-category candidates first
        fill: list[str] = []
        for name in pool_by_category.get(cat, []):
            if name not in used_names:
                fill.append(name)
                used_names.add(name)
            if len(fill) >= needed:
                break

        # Cross-category fallback
        if len(fill) < needed:
            for name in pool_all:
                if name not in used_names:
                    fill.append(name)
                    used_names.add(name)
                if len(fill) >= needed:
                    break

        stop["alternatives"] = existing_alts + fill[:needed]

    return itinerary


def _parse_itinerary(raw: str, trip_id: str, state: dict) -> dict:
    """
    Phase 4 — parse, validate, and coerce the LLM JSON output.

    Steps:
    1. Strip markdown fences (defensive — shouldn't be needed with json_schema
       response_format but guards against model regressions).
    2. json.loads() the accumulated streaming text.
    3. Pin trip_id (LLM should output it, but we enforce it here).
    4. Fill missing alternatives from the ranked_candidates pool.
    5. Validate the full structure with Pydantic Itinerary/Stop models,
       coercing cost strings and cleaning empty alternatives.
    6. On ValidationError: log, apply best-effort defaults, return raw dict
       rather than raising — the frontend should always receive something.
    """
    text = raw.strip()

    # Defensive fence strip — structured output shouldn't produce these
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    # ── JSON parse ─────────────────────────────────────────────────────────────
    try:
        parsed: dict = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "LLM output failed JSON parse (len=%d); returning raw fallback", len(raw)
        )
        return {
            "trip_id": trip_id,
            "summary": "Itinerary generated but could not be parsed as JSON.",
            "stops": [],
            "total_estimated_cost": 0.0,
            "weather_note": "",
            "warnings": ["Parse error — itinerary text unavailable"],
            "raw_text": raw,
        }

    # ── Enforce trip_id ────────────────────────────────────────────────────────
    parsed["trip_id"] = trip_id

    # ── Fill missing alternatives (Phase 4) ───────────────────────────────────
    ranked_candidates: list[dict] = state.get("ranked_candidates") or []
    ordered_stop_names: set[str] = {
        s.get("name", "") for s in (state.get("ordered_stops") or [])
    }
    parsed = _fill_missing_alternatives(parsed, ranked_candidates, ordered_stop_names)

    # ── Pydantic validation + coercion ─────────────────────────────────────────
    try:
        itinerary_model = Itinerary(**parsed)
        return itinerary_model.model_dump(exclude_none=False)
    except ValidationError as exc:
        logger.warning(
            "Itinerary Pydantic validation failed (%d error(s)); returning coerced dict",
            exc.error_count(),
        )
        # Best-effort coercion: ensure required keys exist with safe defaults
        parsed.setdefault("summary", "")
        parsed.setdefault("stops", [])
        parsed.setdefault("total_estimated_cost", 0.0)
        parsed.setdefault("weather_note", "")
        parsed.setdefault("warnings", [])
        parsed["warnings"] = list(parsed["warnings"]) + [
            "Itinerary schema validation warning — some fields may be incomplete."
        ]
        return parsed


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
