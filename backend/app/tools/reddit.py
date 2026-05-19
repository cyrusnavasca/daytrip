"""
Reddit search via Tavily.
Reddit's API is closed to new developers, so we query Reddit threads
through Tavily's web search using site:reddit.com filters.
"""
import os
from tavily import AsyncTavilyClient

_client: AsyncTavilyClient | None = None


def _get_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            raise ValueError("TAVILY_API_KEY is not set")
        _client = AsyncTavilyClient(api_key=api_key)
    return _client


async def search_reddit(query: str, subreddits: list[str] | None = None) -> list[dict]:
    """
    Search Reddit threads via Tavily.
    Optionally restrict to specific subreddits (e.g. ["travel", "solotravel"]).
    Returns a list of dicts with keys: title, url, content, score.
    """
    client = _get_client()

    site_filter = "site:reddit.com"
    if subreddits:
        subreddit_filter = " OR ".join(f"subreddit:{r}" for r in subreddits)
        full_query = f"{query} {site_filter} ({subreddit_filter})"
    else:
        full_query = f"{query} {site_filter}"

    response = await client.search(
        query=full_query,
        search_depth="advanced",
        max_results=10,
        include_answer=False,
    )

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "score": r.get("score", 0.0),
        }
        for r in response.get("results", [])
    ]
