"""Mapbox Directions API — routing, travel time estimates, and profile mapping."""

import os

import httpx

MAPBOX_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN", "")
BASE_URL = "https://api.mapbox.com/directions/v5/mapbox"

# Maps TripRequest.transport → Mapbox routing profile
_PROFILE_MAP: dict[str, str] = {
    "driving": "driving-traffic",
    "walking": "walking",
    "cycling": "cycling",
    "transit": "driving-traffic",  # Mapbox doesn't offer public-transit routing
}


def transport_to_profile(transport: str) -> str:
    """Convert a TripRequest transport mode to the correct Mapbox profile slug."""
    return _PROFILE_MAP.get(transport, "driving-traffic")


async def get_directions(
    coordinates: list[tuple[float, float]],
    profile: str = "driving-traffic",
) -> dict:
    """
    Fetch a route between two or more waypoints.

    Args:
        coordinates: List of (lat, lng) tuples — at least 2, at most 25.
        profile:     Mapbox routing profile. Use `transport_to_profile()` to convert
                     from a TripRequest transport string.

    Returns:
        Dict with duration_seconds, distance_meters, geometry (GeoJSON LineString),
        and per-leg breakdowns. Returns {} if routing fails.
    """
    if len(coordinates) < 2:
        raise ValueError("Need at least 2 waypoints for directions.")
    if len(coordinates) > 25:
        raise ValueError("Mapbox Directions supports at most 25 waypoints.")
    if not MAPBOX_TOKEN:
        return {}

    # Mapbox expects lng,lat order (opposite of lat,lng convention)
    coord_str = ";".join(f"{lng},{lat}" for lat, lng in coordinates)

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                f"{BASE_URL}/{profile}/{coord_str}",
                params={
                    "access_token": MAPBOX_TOKEN,
                    "geometries": "geojson",
                    "overview": "full",
                    "steps": "false",
                    "annotations": "duration,distance",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return {}

    routes = data.get("routes", [])
    if not routes:
        return {}

    route = routes[0]
    legs = route.get("legs", [])

    return {
        "duration_seconds": route.get("duration"),
        "distance_meters": route.get("distance"),
        "geometry": route.get("geometry"),
        "legs": [
            {
                "duration_seconds": leg.get("duration"),
                "distance_meters": leg.get("distance"),
                "summary": leg.get("summary", ""),
            }
            for leg in legs
        ],
    }


async def get_travel_time(
    origin: tuple[float, float],
    destination: tuple[float, float],
    profile: str = "driving-traffic",
) -> str:
    """
    Return a human-readable travel time string between two points.
    Returns 'unknown' if the Mapbox call fails or token is missing.
    """
    result = await get_directions([origin, destination], profile=profile)
    if not result or result.get("duration_seconds") is None:
        return "unknown"
    return _format_duration(result["duration_seconds"])


async def get_multi_leg_times(
    stops: list[tuple[float, float]],
    profile: str = "driving-traffic",
) -> list[str]:
    """
    For an ordered list of stops, return a human-readable travel time
    for each consecutive leg (len == len(stops) - 1).
    """
    result = await get_directions(stops, profile=profile)
    if not result or not result.get("legs"):
        return ["unknown"] * max(0, len(stops) - 1)
    return [_format_duration(leg["duration_seconds"]) for leg in result["legs"]]


def _format_duration(seconds: float | int) -> str:
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, remaining = divmod(minutes, 60)
    if remaining == 0:
        return f"{hours} hr"
    return f"{hours} hr {remaining} min"
