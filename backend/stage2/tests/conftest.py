"""Shared test fixtures for the Stage 2 suite."""

from __future__ import annotations

import asyncio

import pytest


def _postgres_reachable() -> bool:
    """True if the configured (shared) PostgreSQL is up right now."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from stage2.config import get_settings
    from stage2.terrain.dem_source import _to_asyncpg_url

    async def _check() -> bool:
        engine = create_async_engine(
            _to_asyncpg_url(get_settings().stage1b_database_url)
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


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Shared PostgreSQL not reachable — run `docker compose up -d` "
    "in backend/stage1a/ (stages share one local Postgres instance)",
)
