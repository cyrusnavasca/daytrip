"""
RAG Agent
=========
Implements runtime Retrieval-Augmented Generation over the freshly-fetched
search results. No pre-indexed corpus — we embed only the retrieved subset.

Pipeline:
  1. Extract text chunks from Reddit threads and Atlas Obscura spots.
  2. Build a query embedding from the trip request (vibe + location).
  3. Embed all chunks in a single batched OpenAI API call.
  4. Rank chunks by cosine similarity to the query embedding.
  5. Save top chunks to retrieval_cache (best-effort, for future caching).
  6. Return the top-K semantically reranked chunks as reranked_docs.

Graceful fallback: if OpenAI embedding fails, returns the raw chunks ordered
by original search score (Reddit relevance score or Atlas Obscura order).
"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.orchestrator import TripState

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

_EMBED_MODEL = "text-embedding-3-small"
_TOP_K = 10
_CHUNK_MAX_CHARS = 500


async def run_rag(state: "TripState") -> dict:
    """
    Embed retrieved content and return semantically reranked top-K docs.
    Falls back gracefully if embedding fails.
    """
    request = state["request"]
    reddit_results: list[dict] = state.get("reddit_results", [])
    atlas_spots: list[dict] = state.get("atlas_spots", [])
    city: str = state.get("city") or request.location.split(",")[0].strip()

    chunks = _build_chunks(reddit_results, atlas_spots)

    if not chunks:
        logger.debug("RAG: no chunks to embed, skipping")
        return {"reranked_docs": []}

    query_text = (
        f"{request.vibe} day trip {request.location} "
        f"local recommendations hidden gems authentic"
    )

    try:
        texts_to_embed = [query_text] + [c["content"] for c in chunks]
        embeddings = await _embed_batch(texts_to_embed)

        query_emb = embeddings[0]
        chunk_embs = embeddings[1:]

        for i, chunk in enumerate(chunks):
            chunk["similarity"] = _cosine_similarity(query_emb, chunk_embs[i])

        ranked = sorted(chunks, key=lambda x: x["similarity"], reverse=True)[:_TOP_K]

        # Best-effort cache write in background — never blocks pipeline
        asyncio.create_task(_cache_to_db(ranked, city))

        logger.debug(
            "RAG: ranked %d chunks, top similarity=%.3f",
            len(ranked),
            ranked[0]["similarity"] if ranked else 0.0,
        )
        return {"reranked_docs": ranked}

    except Exception as exc:
        logger.warning("RAG embedding failed, returning unranked chunks: %s", exc)
        fallback = chunks[:_TOP_K]
        for c in fallback:
            c.setdefault("similarity", 0.0)
        return {"reranked_docs": fallback}


# ── Text chunking ──────────────────────────────────────────────────────────────

def _build_chunks(reddit_results: list[dict], atlas_spots: list[dict]) -> list[dict]:
    """
    Combine Reddit thread content and Atlas Obscura descriptions into
    a flat list of text chunks for embedding.
    """
    chunks: list[dict] = []

    for r in reddit_results:
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        combined = f"{title} {content}".strip()
        if not combined:
            continue
        chunks.append({
            "source": title or "Reddit thread",
            "content": combined[:_CHUNK_MAX_CHARS],
            "url": r.get("url", ""),
            "type": "reddit",
            "original_score": float(r.get("score", 0.0)),
            "similarity": 0.0,
        })

    for spot in atlas_spots:
        name = (spot.get("name") or "").strip()
        description = (spot.get("description") or "").strip()
        combined = f"{name} — {description}".strip(" —")
        if not combined:
            continue
        chunks.append({
            "source": name or "Atlas Obscura spot",
            "content": combined[:_CHUNK_MAX_CHARS],
            "url": spot.get("url", ""),
            "type": "atlas_obscura",
            "original_score": 0.0,
            "similarity": 0.0,
        })

    return chunks


# ── OpenAI embeddings ──────────────────────────────────────────────────────────

async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts in one OpenAI API call.
    Embeddings are returned ordered by their original index.
    """
    response = await _openai.embeddings.create(
        model=_EMBED_MODEL,
        input=texts,
    )
    ordered = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in ordered]


# ── Cosine similarity (pure Python — avoids numpy dependency) ─────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length float vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── DB caching (best-effort background task) ───────────────────────────────────

async def _cache_to_db(ranked_docs: list[dict], city: str) -> None:
    """
    Persist reranked chunks to retrieval_cache for future queries.
    Embeddings are intentionally NOT stored here to keep this non-blocking;
    Phase 6 will add full embedding persistence with pgvector lookups.
    """
    try:
        from app.db.queries import save_retrieval_cache  # lazy import
        for doc in ranked_docs:
            await save_retrieval_cache(
                source=doc.get("source", ""),
                content=doc.get("content", ""),
                city=city,
                category=doc.get("type", "general"),
                embedding=None,
            )
    except Exception:
        logger.debug("RAG DB cache write failed (non-fatal)", exc_info=True)
