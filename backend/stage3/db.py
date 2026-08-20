"""Database & Redis connection layer — T3.0 dependency.

Only `get_redis_client()` is implemented so far: T3.6 (the first task
that actually needs this file) requires Redis caching for the damage
ranking, per its literal spec ("cached in Redis thereafter") -- it does
NOT require persisting `DamageRankEntry` rows to Postgres (unlike Stage
1B's T1B.9, which explicitly needed a DB table for idempotent forecast
storage). No task so far has needed one.

An async SQLAlchemy engine/session (mirroring Stage 1B's db.py pattern)
will be added here once a real task needs to persist something to
Postgres -- not built speculatively ahead of that need.
"""

from __future__ import annotations

import redis.asyncio as redis_asyncio

from backend.stage3.config import settings

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
