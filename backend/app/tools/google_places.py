"""Google Places & Geocoding APIs — geocoding, text search, nearby search, place details."""

import os
import httpx
from typing import Optional

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
BASE_URL = "https://maps.googleapis.com/maps/api"


async def geocode(location: str) -> tuple[float, float]:
    """Convert a location name or address to (lat, lng)."""
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_MAPS_API_KEY is not set")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{BASE_URL}/geocode/json",
            params={"address": location, "key": GOOGLE_API_KEY},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "OK" or not data.get("results"):
        raise ValueError(
            f"Could not geocode '{location}'. Google status: {data.get('status')}"
        )

    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


async def search_places(
    query: str,
    lat: float,
    lng: float,
    radius_m: int = 10_000,
) -> list[dict]:
    """Text Search for places matching a query near a lat/lng."""
    if not GOOGLE_API_KEY:
        return []

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{BASE_URL}/place/textsearch/json",
            params={
                "query": query,
                "location": f"{lat},{lng}",
                "radius": radius_m,
                "key": GOOGLE_API_KEY,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return [_parse_place(r) for r in data.get("results", [])[:10]]


async def search_nearby(
    lat: float,
    lng: float,
    place_type: str,
    radius_m: int = 5_000,
    keyword: Optional[str] = None,
) -> list[dict]:
    """Nearby search by Google place type (e.g. 'restaurant', 'cafe', 'park')."""
    if not GOOGLE_API_KEY:
        return []

    params: dict = {
        "location": f"{lat},{lng}",
        "radius": radius_m,
        "type": place_type,
        "rankby": "prominence",
        "key": GOOGLE_API_KEY,
    }
    if keyword:
        params["keyword"] = keyword

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{BASE_URL}/place/nearbysearch/json",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    return [_parse_nearby(r) for r in data.get("results", [])[:10]]


async def get_place_details(place_id: str) -> dict:
    """Fetch full details and top 3 reviews for a place."""
    if not GOOGLE_API_KEY:
        return {}

    fields = ",".join([
        "name",
        "formatted_address",
        "rating",
        "reviews",
        "opening_hours",
        "website",
        "price_level",
        "geometry",
        "editorial_summary",
    ])

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{BASE_URL}/place/details/json",
            params={"place_id": place_id, "fields": fields, "key": GOOGLE_API_KEY},
        )
        resp.raise_for_status()
        data = resp.json()

    result = data.get("result", {})
    oh = result.get("opening_hours", {})

    return {
        "name": result.get("name"),
        "address": result.get("formatted_address"),
        "rating": result.get("rating"),
        "website": result.get("website"),
        "price_level": result.get("price_level"),
        "open_now": oh.get("open_now"),
        "hours": oh.get("weekday_text", []),
        "editorial_summary": result.get("editorial_summary", {}).get("overview", ""),
        "reviews": [
            {
                "author": rev.get("author_name"),
                "rating": rev.get("rating"),
                "text": rev.get("text", "")[:400],
                "time": rev.get("relative_time_description"),
            }
            for rev in result.get("reviews", [])[:3]
        ],
        "lat": result.get("geometry", {}).get("location", {}).get("lat"),
        "lng": result.get("geometry", {}).get("location", {}).get("lng"),
    }


# ── Private helpers ────────────────────────────────────────────────────────────

def _parse_place(r: dict) -> dict:
    return {
        "name": r.get("name"),
        "place_id": r.get("place_id"),
        "address": r.get("formatted_address"),
        "rating": r.get("rating"),
        "user_ratings_total": r.get("user_ratings_total"),
        "price_level": r.get("price_level"),
        "lat": r.get("geometry", {}).get("location", {}).get("lat"),
        "lng": r.get("geometry", {}).get("location", {}).get("lng"),
        "types": r.get("types", []),
        "open_now": r.get("opening_hours", {}).get("open_now"),
    }


def _parse_nearby(r: dict) -> dict:
    return {
        "name": r.get("name"),
        "place_id": r.get("place_id"),
        "address": r.get("vicinity"),
        "rating": r.get("rating"),
        "user_ratings_total": r.get("user_ratings_total"),
        "price_level": r.get("price_level"),
        "lat": r.get("geometry", {}).get("location", {}).get("lat"),
        "lng": r.get("geometry", {}).get("location", {}).get("lng"),
        "types": r.get("types", []),
        "open_now": r.get("opening_hours", {}).get("open_now"),
    }
