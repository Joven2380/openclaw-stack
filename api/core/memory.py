"""Vector memory layer using Supabase pgvector.

Provides embed_text, store_memory, and search_memory backed by the
agent_memories table (namespace, agent_name, content, embedding, metadata).
"""

import json
import os
from typing import Any

import asyncpg
import structlog

log = structlog.get_logger(__name__)

# Embedding dimension must match the vector(1536) column in agent_memories.
# OpenAI text-embedding-3-small → 1536 dims (primary).
# Ollama nomic-embed-text → 768 dims (fallback, will fail DB insert — use only if
# you alter the table to vector(768) or use a 1536-dim Ollama model).
_OPENAI_EMBED_MODEL = "text-embedding-3-small"
_OLLAMA_EMBED_MODEL = "nomic-embed-text"


def _get_embedding_provider() -> str:
    """Return configured embedding provider: 'openai' or 'ollama'."""
    explicit = os.getenv("EMBEDDING_PROVIDER", "").lower()
    if explicit in ("openai", "ollama"):
        return explicit
    # Auto-detect: prefer OpenAI if key is set.
    return "openai" if os.getenv("OPENAI_API_KEY") else "ollama"


async def embed_text(text: str) -> list[float]:
    """Embed text into a vector using the configured embedding provider.

    Args:
        text: Plain text to embed. Truncated to 8000 chars for API safety.

    Returns:
        Embedding vector as a list of floats.
        OpenAI text-embedding-3-small → 1536 dimensions.
        Ollama nomic-embed-text → 768 dimensions (requires matching table column).

    Raises:
        RuntimeError: If embedding call fails after the provider is resolved.
    """
    text = text[:8000]  # guard against oversized inputs
    provider = _get_embedding_provider()

    if provider == "openai":
        return await _embed_openai(text)
    return await _embed_ollama(text)


async def _embed_openai(text: str) -> list[float]:
    """Embed via OpenAI text-embedding-3-small."""
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set — cannot embed via OpenAI")

    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.embeddings.create(
            model=_OPENAI_EMBED_MODEL,
            input=text,
        )
        return response.data[0].embedding
    except Exception as exc:
        log.error("openai_embed_failed", error=str(exc))
        raise RuntimeError(f"OpenAI embedding failed: {exc}") from exc


async def _embed_ollama(text: str) -> list[float]:
    """Embed via Ollama local model (nomic-embed-text → 768 dims)."""
    import httpx

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/api/embeddings",
                json={"model": _OLLAMA_EMBED_MODEL, "prompt": text},
            )
            response.raise_for_status()
            data = response.json()
            return data["embedding"]
    except Exception as exc:
        log.error("ollama_embed_failed", error=str(exc))
        raise RuntimeError(f"Ollama embedding failed: {exc}") from exc


async def store_memory(
    agent_name: str,
    content: str,
    metadata: dict[str, Any],
    conn: asyncpg.Connection,
    client_id: str = "internal",
) -> str:
    """Embed content and insert it into agent_memories.

    Args:
        agent_name: Slug of the agent storing this memory (e.g. "nora").
        content: Text content to store and embed.
        metadata: Arbitrary JSON metadata attached to the record.
        conn: Live asyncpg connection.
        client_id: Client identifier for namespace scoping.

    Returns:
        The UUID of the inserted row as a string.

    Raises:
        RuntimeError: If embedding or DB insert fails.
    """
    namespace = f"{client_id}:{agent_name}"
    embedding = await embed_text(content)

    # asyncpg requires the vector as a string in pgvector wire format.
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

    row = await conn.fetchrow(
        """
        INSERT INTO agent_memories (namespace, client_id, agent_name, content, embedding, metadata)
        VALUES ($1, $2, $3, $4, $5::vector, $6::jsonb)
        RETURNING id
        """,
        namespace,
        client_id,
        agent_name,
        content,
        embedding_str,
        json.dumps(metadata),
    )

    memory_id = str(row["id"])
    log.debug("memory_stored", agent=agent_name, id=memory_id, chars=len(content))
    return memory_id


async def search_memory(
    agent_name: str,
    query: str,
    conn: asyncpg.Connection,
    client_id: str = "internal",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search agent memory using cosine similarity via pgvector.

    Args:
        agent_name: Slug of the agent whose memory to search.
        query: Natural language query to embed and compare.
        conn: Live asyncpg connection.
        client_id: Client scope for namespace filtering.
        limit: Maximum number of results to return.

    Returns:
        List of dicts with keys: content, metadata, similarity.
        Ordered by similarity descending (most relevant first).
    """
    namespace = f"{client_id}:{agent_name}"

    try:
        embedding = await embed_text(query)
    except RuntimeError as exc:
        log.warning("memory_search_embed_failed", agent=agent_name, error=str(exc))
        return []

    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

    rows = await conn.fetch(
        """
        SELECT content, metadata, 1 - (embedding <=> $1::vector) AS similarity
        FROM agent_memories
        WHERE namespace = $2
        ORDER BY embedding <=> $1::vector
        LIMIT $3
        """,
        embedding_str,
        namespace,
        limit,
    )

    results = [
        {
            "content": row["content"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "similarity": float(row["similarity"]),
        }
        for row in rows
    ]

    log.debug("memory_search", agent=agent_name, query_chars=len(query), results=len(results))
    return results
