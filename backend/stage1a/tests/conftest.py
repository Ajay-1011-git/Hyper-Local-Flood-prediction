"""Shared test fixtures for the Stage 1A suite."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest


# Both probes below run on their own short-lived event loop at collection
# time, so they deliberately build throwaway connections instead of touching
# `db.py`'s process-wide singletons — a singleton created here would stay
# bound to this loop after it closes, and every later test would fail with
# "Event loop is closed".


def _database_reachable() -> bool:
    """Return True if the configured PostgreSQL is up right now."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from stage1a.config import get_settings
    from stage1a.db import _async_database_url

    async def _check() -> bool:
        engine = create_async_engine(
            _async_database_url(get_settings().database_url)
        )
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    return asyncio.run(_check())


def _redis_reachable() -> bool:
    """Return True if the configured Redis is up right now."""
    import redis.asyncio as aioredis

    from stage1a.config import get_settings

    async def _check() -> bool:
        client = aioredis.Redis.from_url(get_settings().redis_url)
        try:
            await client.ping()
            return True
        except Exception:
            return False
        finally:
            await client.aclose()

    return asyncio.run(_check())


requires_postgres = pytest.mark.skipif(
    not _database_reachable(),
    reason="PostgreSQL not reachable — run `docker compose up -d` in backend/stage1a/",
)

requires_redis = pytest.mark.skipif(
    not _redis_reachable(),
    reason="Redis not reachable — run `docker compose up -d` in backend/stage1a/",
)


@pytest.fixture(scope="session", autouse=True)
async def _close_shared_connections() -> AsyncIterator[None]:
    """Dispose db.py's singletons inside the session event loop.

    Must be async and session-loop-scoped: the engine and Redis client are
    bound to that loop, so tearing them down from a fresh `asyncio.run()`
    after it closes raises "Event loop is closed".
    """
    yield
    from stage1a.db import dispose_connections

    await dispose_connections()
