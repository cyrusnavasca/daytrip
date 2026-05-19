"""
Atlas Obscura — hidden and unique local spots searched by lat/lng.

Uses Atlas Obscura's public web endpoint (no API key required).
The endpoint powering their own map view is queried directly via httpx.
Falls back to an empty list on any HTTP or parse failure so it never
blocks the rest of the pipeline.
"""

import httpx

BASE_URL = "https://www.atlasobscura.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.atlasobscura.com/",
    "X-Requested-With": "XMLHttpRequest",
}


async def search_nearby(
    lat: float,
    lng: float,
    radius_km: int = 50,
    max_results: int = 12,
) -> list[dict]:
    """
    Return up to `max_results` Atlas Obscura places within `radius_km` of lat/lng.
    Tries two known endpoint patterns; returns [] on failure rather than raising.
    """
    places = await _try_places_endpoint(lat, lng, radius_km, max_results)
    if places:
        return places

    places = await _try_search_endpoint(lat, lng, radius_km, max_results)
    return places


async def _try_places_endpoint(
    lat: float,
    lng: float,
    radius_km: int,
    max_results: int,
) -> list[dict]:
    """
    Primary: /places.json with nearby[] params — powers their interactive map.
    """
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(
                f"{BASE_URL}/places.json",
                params={
                    "nearby[latitude]": lat,
                    "nearby[longitude]": lng,
                    "nearby[radius]": radius_km,
                    "per_page": max_results,
                    "page": 1,
                },
                headers=_HEADERS,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception:
        return []

    items = data if isinstance(data, list) else data.get("places", data.get("results", []))
    return [p for p in (_parse_item(i) for i in items[:max_results]) if p]


async def _try_search_endpoint(
    lat: float,
    lng: float,
    radius_km: int,
    max_results: int,
) -> list[dict]:
    """
    Fallback: /search/nearby.json used by their mobile client.
    """
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(
                f"{BASE_URL}/search/nearby.json",
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "distance": radius_km,
                    "limit": max_results,
                },
                headers=_HEADERS,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception:
        return []

    items = data if isinstance(data, list) else data.get("places", data.get("results", []))
    return [p for p in (_parse_item(i) for i in items[:max_results]) if p]


def _parse_item(item: dict) -> dict | None:
    name = item.get("title") or item.get("name") or item.get("place_name")
    if not name:
        return None

    slug = item.get("slug") or item.get("place_slug")
    url = f"{BASE_URL}/places/{slug}" if slug else item.get("url", "")

    return {
        "name": name,
        "description": (
            item.get("subtitle")
            or item.get("description")
            or item.get("teaser")
            or ""
        )[:300],
        "url": url,
        "lat": _safe_float(item.get("lat") or item.get("latitude") or item.get("location_lat")),
        "lng": _safe_float(item.get("lng") or item.get("longitude") or item.get("location_lng")),
        "city": item.get("city") or item.get("location_city") or "",
        "country": item.get("country") or item.get("location_country") or "",
    }


def _safe_float(val: object) -> float | None:
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
