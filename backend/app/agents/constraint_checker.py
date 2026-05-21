"""
Constraint Checker
==================
Validates the finalized, route-ordered itinerary against the user's stated
constraints and emits human-readable warnings. Warnings are forwarded to the
LLM synthesis step so they appear in the final itinerary JSON.

Checks performed:
  1. Budget        — total estimated cost vs request.budget
  2. Timing fit    — trip duration vs request.duration_hours (±20% tolerance)
  3. Pacing        — individual stops shorter than 20 min flagged as rushed
  4. Business hrs  — stops with open_now=False get a "verify hours" warning
  5. Coverage      — if no stops were produced, emit an actionable warning
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.orchestrator import TripState

from app.models.request import TripRequest

logger = logging.getLogger(__name__)

_MIN_VISIT_MIN = 20          # fewer minutes than this is uncomfortably rushed
_OVER_BUDGET_TOLERANCE = 0.05   # 5% over budget is OK before we warn
_OVER_TIME_TOLERANCE = 0.20     # 20% over duration triggers a warning
_UNDER_TIME_THRESHOLD = 0.50    # filling less than 50% of duration also warns


def run_constraint_check(state: "TripState") -> dict:
    """
    Validate the ordered itinerary and return a list of warning strings.
    This node is always non-fatal — it only adds to the warnings list.
    """
    request: TripRequest = state["request"]
    ordered_stops: list[dict] = state.get("ordered_stops", [])
    warnings: list[str] = []

    # ── Coverage check ─────────────────────────────────────────────────────────
    if not ordered_stops:
        warnings.append(
            "No stops could be generated for this request. "
            "Try a broader location, different vibe, or higher budget."
        )
        return {"constraint_warnings": warnings}

    # ── Budget check ───────────────────────────────────────────────────────────
    total_cost = sum(float(s.get("estimated_cost") or 0.0) for s in ordered_stops)
    budget = request.budget

    if total_cost > budget * (1.0 + _OVER_BUDGET_TOLERANCE):
        overage = total_cost - budget
        warnings.append(
            f"Estimated total (${total_cost:.0f}) is ${overage:.0f} over your "
            f"${budget:.0f} budget. Consider swapping pricier stops for the "
            f"listed alternatives or reducing food/activity spend."
        )

    # ── Timing fit check ───────────────────────────────────────────────────────
    total_trip_min = _total_trip_minutes(ordered_stops)
    allowed_min = request.duration_hours * 60

    if total_trip_min > allowed_min * (1.0 + _OVER_TIME_TOLERANCE):
        over_min = int(total_trip_min - allowed_min)
        warnings.append(
            f"The itinerary runs approximately {over_min} minutes over your "
            f"{request.duration_hours:.0f}-hour window. Consider removing one stop "
            f"or shortening visit times."
        )
    elif total_trip_min < allowed_min * _UNDER_TIME_THRESHOLD:
        filled_hr = total_trip_min // 60
        filled_min = total_trip_min % 60
        warnings.append(
            f"The itinerary fills only {filled_hr}h {filled_min}m of your "
            f"{request.duration_hours:.0f}-hour day — you'll have time to explore "
            f"nearby spots spontaneously."
        )

    # ── Pacing check ───────────────────────────────────────────────────────────
    for stop in ordered_stops:
        visit_min = int(stop.get("visit_duration_min") or 0)
        if 0 < visit_min < _MIN_VISIT_MIN:
            warnings.append(
                f"'{stop.get('name')}' has only {visit_min} min scheduled — "
                f"you may feel rushed. Swap it for one of the alternatives if time is tight."
            )

    # ── Business hours check ───────────────────────────────────────────────────
    for stop in ordered_stops:
        if stop.get("open_now") is False:
            warnings.append(
                f"'{stop.get('name')}' appears to be currently closed. "
                f"Verify its hours before building your day around it."
            )

    if warnings:
        logger.debug("Constraint checker: %d warning(s) generated", len(warnings))

    return {"constraint_warnings": warnings}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _total_trip_minutes(stops: list[dict]) -> int:
    """Sum all visit durations and travel times across the itinerary."""
    total = 0
    for stop in stops:
        total += int(stop.get("visit_duration_min") or 60)
        total += _parse_minutes(stop.get("travel_time_to_next") or "")
    return total


def _parse_minutes(time_str: str) -> int:
    """Parse '15 min', '1 hr 5 min', or '' into a total integer minutes value."""
    s = time_str.strip().lower()
    if not s or s in ("n/a", "unknown"):
        return 0
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
    return total
