"""
RAG Agent
Chunks retrieved text, embeds the subset with text-embedding-3-small,
then semantically reranks candidates before passing to the ranking agent.
"""


async def retrieve_and_rerank(raw_results: list[dict], query: str) -> list[dict]:
    # TODO: chunk → embed → pgvector similarity search → rerank
    return []
