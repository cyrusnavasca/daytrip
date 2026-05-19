"""Typed SQL helpers for trips, retrieval cache, and user preferences."""

import json
import logging
from typing import Optional

from app.db.client import get_pool

logger = logging.getLogger(__name__)


# ── Trips ──────────────────────────────────────────────────────────────────────

async def save_trip(
    query: str,
    itinerary_json: dict,
    user_id: Optional[str] = None,
) -> str:
    """Insert a new trip and return its UUID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO trips (user_id, query, itinerary_json)
        VALUES ($1, $2, $3::jsonb)
        RETURNING id
        """,
        user_id,
        query,
        json.dumps(itinerary_json),
    )
    return str(row["id"])


async def get_trip(trip_id: str) -> Optional[dict]:
    """Fetch a trip by UUID. Returns None if not found."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM trips WHERE id = $1",
        trip_id,
    )
    return dict(row) if row else None


async def list_trips(user_id: str, limit: int = 20) -> list[dict]:
    """Return the most recent trips for a user."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM trips WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
        user_id,
        limit,
    )
    return [dict(r) for r in rows]


# ── Retrieval cache ────────────────────────────────────────────────────────────

async def get_cached_retrieval(city: str, category: str) -> list[dict]:
    """
    Fetch cached retrieval rows for a city + category.
    Used by the RAG Agent (Phase 3) to skip redundant fetches.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, source, content, city, category, created_at
        FROM retrieval_cache
        WHERE city = $1 AND category = $2
        ORDER BY created_at DESC
        LIMIT 50
        """,
        city,
        category,
    )
    return [dict(r) for r in rows]


async def save_retrieval_cache(
    source: str,
    content: str,
    city: str,
    category: str,
    embedding: Optional[list[float]] = None,
) -> str:
    """
    Persist a retrieved document (Reddit thread, Google review, etc.)
    with an optional pgvector embedding for semantic search in Phase 3.
    """
    pool = await get_pool()
    if embedding is not None:
        row = await pool.fetchrow(
            """
            INSERT INTO retrieval_cache (source, content, embedding, city, category)
            VALUES ($1, $2, $3::vector, $4, $5)
            RETURNING id
            """,
            source,
            content,
            embedding,
            city,
            category,
        )
    else:
        row = await pool.fetchrow(
            """
            INSERT INTO retrieval_cache (source, content, city, category)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            source,
            content,
            city,
            category,
        )
    return str(row["id"])


async def vector_search(
    query_embedding: list[float],
    city: str,
    limit: int = 10,
) -> list[dict]:
    """
    Semantic similarity search within a city using pgvector cosine distance.
    Used by the RAG Agent in Phase 3.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, source, content, city, category,
               1 - (embedding <=> $1::vector) AS similarity
        FROM retrieval_cache
        WHERE city = $2
          AND embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        query_embedding,
        city,
        limit,
    )
    return [dict(r) for r in rows]


# ── User preferences ───────────────────────────────────────────────────────────

async def upsert_user_preferences(
    user_id: str,
    vibe_tags: list[str],
    disliked_tags: list[str],
    budget_min: float,
    budget_max: float,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO user_preferences (user_id, vibe_tags, disliked_tags, budget_range)
        VALUES ($1, $2, $3, numrange($4, $5))
        ON CONFLICT (user_id) DO UPDATE
          SET vibe_tags     = EXCLUDED.vibe_tags,
              disliked_tags = EXCLUDED.disliked_tags,
              budget_range  = EXCLUDED.budget_range
        """,
        user_id,
        vibe_tags,
        disliked_tags,
        budget_min,
        budget_max,
    )


async def get_user_preferences(user_id: str) -> Optional[dict]:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM user_preferences WHERE user_id = $1",
        user_id,
    )
    return dict(row) if row else None
