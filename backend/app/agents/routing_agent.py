"""
Routing Agent
=============
Takes the ranked candidate shortlist and produces a final ordered itinerary
of stops with realistic timing.

Steps:
  1. Select a feasible number of stops from the shortlist based on duration.
  2. Prefer candidates with known coordinates for routing; append coord-less
     candidates at the end.
  3. Order stops with a nearest-neighbor greedy algorithm starting from the
     trip's geocoded origin.
  4. Request actual travel times from Mapbox for consecutive legs.
  5. Assign estimated arrival and departure times to every stop starting at
     9:00 AM, accounting for visit durations and travel time between stops.

Mapbox failure is non-fatal: estimated travel times per transport mode are
used as a fallback so timing assignment always completes.
"""

import logging
import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.orchestrator import TripState

from app.models.request import TripRequest
from app.tools.mapbox import get_multi_leg_times, transport_to_profile

logger = logging.getLogger(__name__)

_START_HOUR = 9           # 9:00 AM trip start
_BUFFER_MIN = 5           # 5-minute buffer added after each leg

# Default visit durations by category (minutes)
_VISIT_DURATION: dict[str, int] = {
    "coffee":     35,
    "food":       75,
    "nature":     90,
    "activity":   90,
    "hidden_gem": 50,
    "shopping":   40,
}

# Fallback travel-time estimates per transport mode (minutes)
_FALLBACK_TRAVEL_MIN: dict[str, int] = {
    "walking": 18,
    "cycling": 12,
    "driving": 14,
    "transit": 22,
}


async def run_routing(state: "TripState") -> dict:
    """
    Order ranked candidates into a feasible, time-stamped route.
    Returns ordered_stops with arrival times, visit durations, and travel legs.
    """
    request: TripRequest = state["request"]
    ranked: list[dict] = state.get("ranked_candidates", [])
    origin_lat: float = state.get("lat") or 0.0
    origin_lng: float = state.get("lng") or 0.0

    if not ranked:
        logger.warning("Routing: no ranked candidates to route")
        return {"ordered_stops": []}

    # ── 1. Split candidates by coordinate availability ─────────────────────────
    with_coords = [c for c in ranked if c.get("lat") and c.get("lng")]
    without_coords = [c for c in ranked if not (c.get("lat") and c.get("lng"))]

    # ── 2. Select a feasible number of stops ──────────────────────────────────
    max_stops = _max_stops_for_duration(request.duration_hours)

    # Fill from coord-candidates first, then top up from non-coord candidates
    selected_with = with_coords[:max_stops]
    remaining_slots = max(0, max_stops - len(selected_with))
    selected_without = without_coords[:remaining_slots]

    if not selected_with and not selected_without:
        return {"ordered_stops": []}

    # ── 3. Nearest-neighbor ordering ──────────────────────────────────────────
    ordered_with = _nearest_neighbor(selected_with, (origin_lat, origin_lng))
    ordered_stops = ordered_with + selected_without

    # ── 4. Fetch Mapbox travel times ───────────────────────────────────────────
    profile = transport_to_profile(request.transport)
    coords = [(float(s["lat"]), float(s["lng"])) for s in ordered_with]
    leg_times_str: list[str] = []

    if len(coords) >= 2:
        try:
            leg_times_str = await get_multi_leg_times(coords, profile=profile)
            logger.debug("Mapbox: received %d leg times", len(leg_times_str))
        except Exception as exc:
            logger.warning("Mapbox routing failed, using fallback estimates: %s", exc)

    # Pad with fallback estimates if Mapbox returned fewer legs than expected
    expected_legs = len(ordered_stops) - 1
    fallback_min = _FALLBACK_TRAVEL_MIN.get(request.transport, 14)
    fallback_str = f"{fallback_min} min"
    while len(leg_times_str) < expected_legs:
        leg_times_str.append(fallback_str)

    # ── 5. Assign arrival / departure times ───────────────────────────────────
    current_time = datetime.now().replace(
        hour=_START_HOUR, minute=0, second=0, microsecond=0
    )

    for i, stop in enumerate(ordered_stops):
        visit_min = (
            stop.get("visit_duration_min")
            or _VISIT_DURATION.get(stop.get("category", "activity"), 60)
        )

        stop["estimated_arrival"] = _fmt_time(current_time)
        stop["visit_duration_min"] = visit_min
        departure = current_time + timedelta(minutes=visit_min)
        stop["estimated_departure"] = _fmt_time(departure)

        if i < len(leg_times_str):
            travel_str = leg_times_str[i]
            stop["travel_time_to_next"] = travel_str
            travel_min = _parse_minutes(travel_str)
            current_time = departure + timedelta(minutes=travel_min + _BUFFER_MIN)
        else:
            stop["travel_time_to_next"] = None
            current_time = departure

    logger.debug(
        "Routing: %d stops ordered, trip ends ~%s",
        len(ordered_stops),
        _fmt_time(current_time),
    )

    return {"ordered_stops": ordered_stops}


# ── Nearest-neighbor greedy TSP ────────────────────────────────────────────────

def _nearest_neighbor(
    stops: list[dict],
    origin: tuple[float, float],
) -> list[dict]:
    """
    Greedy nearest-neighbor route starting from origin.
    Runs in O(n²) — suitable for n ≤ 15.
    """
    remaining = list(stops)
    ordered: list[dict] = []
    current = origin

    while remaining:
        nearest = min(
            remaining,
            key=lambda s: _haversine_km(current[0], current[1], float(s["lat"]), float(s["lng"])),
        )
        ordered.append(nearest)
        current = (float(nearest["lat"]), float(nearest["lng"]))
        remaining.remove(nearest)

    return ordered


# ── Helpers ────────────────────────────────────────────────────────────────────

def _max_stops_for_duration(duration_hours: float) -> int:
    """
    Estimate how many stops fit comfortably in the trip duration.
    Assumes ~1.25 hours per stop on average (visit + travel + buffer).
    Clamps to [3, 8].
    """
    return max(3, min(int(duration_hours / 1.25), 8))


def _parse_minutes(time_str: str) -> int:
    """Parse '15 min' or '1 hr 5 min' into a total integer number of minutes."""
    s = time_str.strip().lower()
    total = 0
    if "hr" in s:
        parts = s.replace("hr", " ").replace("min", " ").split()
        try:
            total += int(parts[0]) * 60
        except (IndexError, ValueError):
            pass
        try:
            total += int(parts[1])
        except (IndexError, ValueError):
            pass
    elif "min" in s:
        try:
            total = int(s.replace("min", "").strip())
        except ValueError:
            pass
    return total if total > 0 else 12


def _fmt_time(dt: datetime) -> str:
    """Format a datetime as '9:00 AM' (no leading zero on hour)."""
    return dt.strftime("%I:%M %p").lstrip("0")


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometers between two lat/lng points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
