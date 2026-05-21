"""
Search Agent
============
Generates targeted queries from the trip request and executes parallel
tool calls: Reddit (via Tavily), Google Places (activities, restaurants,
cafes), Atlas Obscura (hidden gems), and OpenWeather.

All tool failures are treated as non-fatal — individual APIs return []/{} on
error so the rest of the pipeline is not blocked.

Returns a partial TripState update dict consumed by the LangGraph orchestrator.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.orchestrator import TripState

from app.models.request import TripRequest
from app.tools.atlas_obscura import search_nearby as atlas_search_nearby
from app.tools.google_places import search_nearby, search_places
from app.tools.openweather import get_forecast
from app.tools.reddit import search_reddit

logger = logging.getLogger(__name__)


async def run_search(state: "TripState") -> dict:
    """
    Fire all external searches in parallel and return a state update dict.
    Individual API failures are logged but never propagate as exceptions.
    """
    request: TripRequest = state["request"]
    lat: float = state["lat"]
    lng: float = state["lng"]

    queries = _generate_queries(request)

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

    # Log individual failures without aborting
    _log_if_exc("reddit_main", reddit_main)
    _log_if_exc("reddit_gems", reddit_gems)
    _log_if_exc("google_activities", google_activities)
    _log_if_exc("google_restaurants", google_restaurants)
    _log_if_exc("google_cafes", google_cafes)
    _log_if_exc("atlas_spots", atlas_spots)
    _log_if_exc("weather", weather)

    # Combine Reddit results (main + hidden gems), cap at 15 total
    combined_reddit = (_safe_list(reddit_main) + _safe_list(reddit_gems))[:15]

    return {
        "reddit_results": combined_reddit,
        "google_activities": _safe_list(google_activities),
        "google_restaurants": _safe_list(google_restaurants),
        "google_cafes": _safe_list(google_cafes),
        "atlas_spots": _safe_list(atlas_spots),
        "weather": _safe_dict(weather),
    }


# ── Query generation ──────────────────────────────────────────────────────────

def _generate_queries(request: TripRequest) -> dict[str, str]:
    """
    Produce three targeted search queries from the trip request.
    Queries are scoped to surface Reddit recommendations and activity-specific
    Google Places results rather than generic tourist results.
    """
    loc = request.location
    vibe = request.vibe
    transport = request.transport

    # Main Reddit query: vibe + location + travel recommendations
    reddit_main = f"best {vibe} day trip {loc} recommendations"

    # Hidden gems query: surfaces local favorites and off-the-beaten-path spots
    reddit_gems = f"hidden gems underrated spots {loc} local favorites not tourist"

    # Google Places text search: activity-oriented query
    google_activities = f"{vibe} things to do {loc}"

    # If transport is walking, bias toward walkable / neighborhood results
    if transport == "walking":
        google_activities = f"walkable {vibe} attractions {loc} neighborhood"

    return {
        "reddit_main": reddit_main,
        "reddit_gems": reddit_gems,
        "google_activities": google_activities,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_list(result: object) -> list:
    """Return [] if asyncio.gather returned an exception for this task."""
    if isinstance(result, (Exception, BaseException)):
        return []
    return result or []  # type: ignore[return-value]


def _safe_dict(result: object) -> dict:
    """Return {} if asyncio.gather returned an exception for this task."""
    if isinstance(result, (Exception, BaseException)):
        return {}
    return result or {}  # type: ignore[return-value]


def _log_if_exc(name: str, result: object) -> None:
    if isinstance(result, (Exception, BaseException)):
        logger.warning("Search tool '%s' failed (non-fatal): %s", name, result)
