"""Database & Redis connection layer — T4A.0 dependency.

Only `get_redis_client()` is implemented, mirroring Stage 3's own T3.0/
T3.6 precedent exactly: T4A.3 (the first task that actually needs this
file) requires caching the generated `Alert` (real Sarvam translation
calls are real, paid, ~1-2s-latency network requests -- recomputing on
every request would be wasteful and costly), not Postgres persistence.
An async SQLAlchemy engine/session will be added here once a real task
needs to persist something to Postgres -- not built speculatively ahead
of that need.
"""

from __future__ import annotations

import redis.asyncio as redis_asyncio

from backend.stage4.config import settings

_redis_client: redis_asyncio.Redis | None = None


def get_redis_client() -> redis_asyncio.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_asyncio.Redis.from_url(
            settings.redis_url, decode_responses=True
        )
    return _redis_client


async def dispose() -> None:
    """Close the Redis connection. Call on app shutdown / in tests."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
