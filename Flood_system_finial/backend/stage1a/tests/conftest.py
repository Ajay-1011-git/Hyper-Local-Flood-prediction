"""Shared test fixtures for the Stage 1A suite."""

from __future__ import annotations

import asyncio
import os
import socket
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


#: Gate for tests that make REAL calls to third-party services (the
#: National Water Data Portal, NOAA NOMADS/S3, ...).
#:
#: 2026-08-20: these run BY DEFAULT again, at the project owner's request,
#: after confirming the CWC portal really does pass (5/5 in 44.5s). They
#: were briefly opt-in earlier the same day because the portal had failed
#: with a read timeout and was making the suite take ~2 minutes.
#:
#: Two real escape hatches remain, for two different real situations:
#:  * `SKIP_LIVE_NETWORK_TESTS=1` — skip them explicitly. They add ~45s to
#:    an otherwise ~3s suite, and the portal HAS been observed timing out
#:    and then recovering on identical code, so a fast/hermetic run is
#:    sometimes what you want.
#:  * Host unreachable — skipped automatically, so the suite does not
#:    hard-fail with no internet. This matters concretely: TRD §3.6
#:    requires the system to run fully on a single laptop with no live
#:    internet dependency on demo day.
#:
#: Local infrastructure (PostgreSQL, Redis) is NOT gated this way — it's
#: this project's own stack, not a third party.
_LIVE_NETWORK_DISABLED = os.getenv("SKIP_LIVE_NETWORK_TESTS") == "1"


def _host_reachable(host: str, port: int = 443, timeout: float = 5.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def requires_live_host(host: str, port: int = 443) -> pytest.MarkDecorator:
    """Skip unless live-network tests are enabled AND `host` is reachable."""
    if _LIVE_NETWORK_DISABLED:
        return pytest.mark.skip(reason="SKIP_LIVE_NETWORK_TESTS=1 is set")
    return pytest.mark.skipif(
        not _host_reachable(host, port),
        reason=f"{host} not reachable from this environment",
    )


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
