"""
Ranking Agent
=============
Scores every candidate place across five orthogonal dimensions and returns
a category-diverse shortlist for the routing agent.

Scoring dimensions (weights sum to 1.0):
  vibe_score     (0.35) — keyword + synonym overlap with request vibe
  rating_score   (0.25) — normalized Google rating (1–5 → 0–1)
  cost_score     (0.15) — suitability of price_level to per-stop budget share
  uniqueness     (0.15) — Atlas Obscura places receive a full bonus
  reddit_boost   (0.10) — name found in any Reddit thread content

Diversity enforcement (applied after sorting):
  - At most 3 stops per category (activity, nature, hidden_gem, shopping)
  - At most 3 food/coffee stops combined (max 2 per sub-category)
  - Up to 15 candidates are returned to give the routing agent room to work
"""

import logging
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.orchestrator import TripState

from app.models.request import TripRequest

logger = logging.getLogger(__name__)


# ── Cost lookup ────────────────────────────────────────────────────────────────

_PRICE_LEVEL_COST: dict[int | None, float] = {
    0: 0.0,
    1: 8.0,
    2: 22.0,
    3: 50.0,
    4: 80.0,
    None: 12.0,
}

# ── Category inference from Google place types ─────────────────────────────────

_TYPE_TO_CATEGORY: list[tuple[str, list[str]]] = [
    ("coffee",   ["cafe", "coffee_shop", "bakery"]),
    ("food",     ["restaurant", "bar", "food", "meal_takeaway", "meal_delivery", "night_club"]),
    ("nature",   ["park", "natural_feature", "campground", "beach", "hiking_area", "rv_park"]),
    ("activity", ["museum", "art_gallery", "amusement_park", "aquarium", "stadium",
                  "tourist_attraction", "point_of_interest", "zoo", "bowling_alley",
                  "movie_theater", "spa"]),
    ("shopping", ["store", "shopping_mall", "market", "clothing_store", "book_store",
                  "home_goods_store"]),
]

# ── Vibe synonym expansion ─────────────────────────────────────────────────────

_VIBE_SYNONYMS: dict[str, list[str]] = {
    "beach":     ["beach", "coastal", "ocean", "surf", "sand", "wave", "shore", "waterfront"],
    "foodie":    ["restaurant", "food", "tasting", "brunch", "cafe", "bakery", "bar",
                  "wine", "coffee", "eat", "dining", "cuisine", "chef", "bistro"],
    "adventure": ["hiking", "trail", "nature", "outdoor", "park", "bike", "kayak",
                  "climb", "trek", "explore", "wilderness"],
    "art":       ["art", "gallery", "museum", "mural", "creative", "culture",
                  "exhibit", "sculpture", "installation"],
    "quirky":    ["obscura", "weird", "unusual", "unique", "hidden", "secret",
                  "eccentric", "odd", "offbeat", "strange"],
    "romantic":  ["scenic", "sunset", "view", "garden", "wine", "intimate",
                  "quiet", "peaceful", "cozy"],
    "family":    ["park", "aquarium", "museum", "kid", "family", "playground",
                  "zoo", "carousel", "miniature"],
    "local":     ["local", "neighborhood", "hidden", "gem", "underrated",
                  "authentic", "dive", "hole-in-the-wall"],
    "solo":      ["coffee", "bookstore", "walk", "explore", "wander", "cafe",
                  "observation", "quiet"],
    "coastal":   ["beach", "ocean", "harbor", "pier", "coastal", "waterfront",
                  "cove", "cliff", "lighthouse", "marina"],
    "nature":    ["park", "trail", "forest", "garden", "botanical", "wildlife",
                  "reserve", "creek", "canyon", "mountain"],
    "history":   ["historic", "heritage", "museum", "landmark", "mission",
                  "monument", "historical", "colonial", "vintage"],
}

# ── Visit duration estimates per category (minutes) ───────────────────────────

_VISIT_DURATION: dict[str, int] = {
    "coffee":     35,
    "food":       75,
    "nature":     90,
    "activity":   90,
    "hidden_gem": 50,
    "shopping":   40,
}


# ── Public entry point ─────────────────────────────────────────────────────────

def run_ranking(state: "TripState") -> dict:
    """
    Merge all candidate sources, score each candidate, apply diversity filter,
    and return the top shortlist for the routing agent.
    """
    request: TripRequest = state["request"]
    google_activities: list[dict] = state.get("google_activities", [])
    google_restaurants: list[dict] = state.get("google_restaurants", [])
    google_cafes: list[dict] = state.get("google_cafes", [])
    atlas_spots: list[dict] = state.get("atlas_spots", [])
    reddit_results: list[dict] = state.get("reddit_results", [])
    origin_lat: float = state.get("lat") or 0.0
    origin_lng: float = state.get("lng") or 0.0

    # ── Build flat candidate list ──────────────────────────────────────────────
    candidates: list[dict] = []

    for place in google_activities:
        candidates.append(_normalize_google(place, "activity"))

    for place in google_restaurants:
        candidates.append(_normalize_google(place, "food"))

    for place in google_cafes:
        candidates.append(_normalize_google(place, "coffee"))

    for spot in atlas_spots:
        candidates.append(_normalize_atlas(spot))

    if not candidates:
        logger.warning("Ranking: no candidates to score")
        return {"ranked_candidates": []}

    # ── Build scoring inputs ───────────────────────────────────────────────────
    vibe_tokens = _tokenize(request.vibe)
    expanded_vibe = _expand_vibe(vibe_tokens)

    reddit_corpus = " ".join(
        (r.get("title", "") + " " + r.get("content", "")).lower()
        for r in reddit_results
    )

    budget_per_stop = request.budget / 5.0  # assume ~5 stops

    # ── Score each candidate ───────────────────────────────────────────────────
    for c in candidates:
        c["_score"] = _score(
            candidate=c,
            vibe_tokens=vibe_tokens,
            expanded_vibe=expanded_vibe,
            reddit_corpus=reddit_corpus,
            budget_per_stop=budget_per_stop,
            origin_lat=origin_lat,
            origin_lng=origin_lng,
        )
        c["visit_duration_min"] = _VISIT_DURATION.get(c["category"], 60)

    # Sort by score descending
    candidates.sort(key=lambda x: x["_score"], reverse=True)

    # ── Apply category diversity ───────────────────────────────────────────────
    diverse = _diversify(candidates, max_total=15)

    logger.debug(
        "Ranking: %d raw candidates → %d after diversity filter (top score=%.3f)",
        len(candidates),
        len(diverse),
        diverse[0]["_score"] if diverse else 0.0,
    )

    return {"ranked_candidates": diverse}


# ── Scoring ────────────────────────────────────────────────────────────────────

def _score(
    candidate: dict,
    vibe_tokens: set[str],
    expanded_vibe: set[str],
    reddit_corpus: str,
    budget_per_stop: float,
    origin_lat: float,
    origin_lng: float,
) -> float:
    score = 0.0

    # ── Vibe match (max 0.35) ──────────────────────────────────────────────────
    place_tokens = _tokenize(
        (candidate.get("name") or "")
        + " " + (candidate.get("description") or "")
        + " " + " ".join(candidate.get("types", []))
    )
    raw_overlap = len(vibe_tokens & place_tokens) / max(len(vibe_tokens), 1)
    expanded_overlap = len(expanded_vibe & place_tokens) / max(len(expanded_vibe), 1)
    score += max(raw_overlap, expanded_overlap) * 0.35

    # ── Rating (max 0.25) — Google rating 1–5 normalized to 0–1 ──────────────
    rating = candidate.get("rating")
    if rating is not None:
        score += ((float(rating) - 1.0) / 4.0) * 0.25

    # ── Cost fit (max 0.15) ───────────────────────────────────────────────────
    est_cost = candidate.get("estimated_cost", 12.0)
    if budget_per_stop > 0:
        if est_cost <= budget_per_stop:
            # Reward affordable stops; lower cost = slightly higher score
            score += (1.0 - est_cost / budget_per_stop) * 0.10
            score += 0.05  # always give some credit for fitting budget
        else:
            # Penalize over-budget-per-stop stops
            overage_ratio = min((est_cost - budget_per_stop) / budget_per_stop, 1.0)
            score -= overage_ratio * 0.10

    # ── Uniqueness (max 0.15) — Atlas Obscura hidden gem bonus ────────────────
    if candidate.get("source") == "atlas_obscura":
        score += 0.15

    # ── Reddit boost (max 0.10) ───────────────────────────────────────────────
    name_lower = (candidate.get("name") or "").lower()
    if name_lower and len(name_lower) > 3 and name_lower in reddit_corpus:
        score += 0.10

    # ── Popularity (max 0.05) — log-scaled review count ──────────────────────
    num_reviews = candidate.get("user_ratings_total") or 0
    if num_reviews > 0:
        score += min(math.log10(num_reviews) / 5.0, 0.05)

    # ── Distance penalty (up to -0.10) ────────────────────────────────────────
    c_lat = candidate.get("lat")
    c_lng = candidate.get("lng")
    if c_lat and c_lng and (origin_lat or origin_lng):
        dist_km = _haversine_km(origin_lat, origin_lng, float(c_lat), float(c_lng))
        if dist_km > 50:
            score -= 0.10
        elif dist_km > 30:
            score -= 0.05

    return score


# ── Vibe expansion ─────────────────────────────────────────────────────────────

def _expand_vibe(vibe_tokens: set[str]) -> set[str]:
    """Expand the vibe token set by adding synonyms that match known vibe keys."""
    expanded = set(vibe_tokens)
    for vibe_key, synonyms in _VIBE_SYNONYMS.items():
        # Activate this synonym group if any vibe token is the key or in the group
        if vibe_key in vibe_tokens or any(s in vibe_tokens for s in synonyms):
            expanded.update(synonyms)
    return expanded


# ── Diversity filter ───────────────────────────────────────────────────────────

def _diversify(candidates: list[dict], max_total: int = 15) -> list[dict]:
    """
    Select a diverse shortlist:
      - Max 3 per non-food category (activity, nature, hidden_gem, shopping)
      - Max 3 food/coffee combined (2 per sub-category)
      - Return up to max_total candidates
    """
    cat_counts: dict[str, int] = {}
    food_coffee_total = 0
    result: list[dict] = []

    for c in candidates:
        cat = c.get("category", "activity")

        if cat in ("food", "coffee"):
            if food_coffee_total >= 3:
                continue
            if cat_counts.get(cat, 0) >= 2:
                continue
            food_coffee_total += 1
        else:
            if cat_counts.get(cat, 0) >= 3:
                continue

        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        result.append(c)

        if len(result) >= max_total:
            break

    return result


# ── Normalization ──────────────────────────────────────────────────────────────

def _normalize_google(place: dict, default_category: str) -> dict:
    """Convert a raw Google Places result into a normalized candidate dict."""
    types: list[str] = place.get("types") or []
    category = _infer_category(types) or default_category

    return {
        "name": place.get("name", ""),
        "place_id": place.get("place_id"),
        "address": place.get("address", ""),
        "lat": place.get("lat"),
        "lng": place.get("lng"),
        "rating": place.get("rating"),
        "user_ratings_total": place.get("user_ratings_total", 0),
        "estimated_cost": _PRICE_LEVEL_COST.get(place.get("price_level"), 12.0),
        "category": category,
        "types": types,
        "description": "",
        "source": "google_places",
        "open_now": place.get("open_now"),
        "_score": 0.0,
    }


def _normalize_atlas(spot: dict) -> dict:
    """Convert a raw Atlas Obscura result into a normalized candidate dict."""
    city = spot.get("city", "")
    country = spot.get("country", "")
    address_parts = [p for p in [city, country] if p]

    return {
        "name": spot.get("name", ""),
        "place_id": None,
        "address": ", ".join(address_parts),
        "lat": spot.get("lat"),
        "lng": spot.get("lng"),
        "rating": None,
        "user_ratings_total": 0,
        "estimated_cost": 0.0,
        "category": "hidden_gem",
        "types": ["point_of_interest"],
        "description": spot.get("description", ""),
        "source": "atlas_obscura",
        "url": spot.get("url", ""),
        "open_now": None,
        "_score": 0.0,
    }


def _infer_category(types: list[str]) -> str | None:
    """Map Google place types to our internal category taxonomy."""
    for category, type_keywords in _TYPE_TO_CATEGORY:
        for t in types:
            if t in type_keywords or any(kw in t for kw in type_keywords):
                return category
    return None


# ── Utilities ──────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Lowercase word tokenizer — strips punctuation."""
    return set(re.findall(r"[a-z]+", text.lower()))


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points in kilometers."""
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
