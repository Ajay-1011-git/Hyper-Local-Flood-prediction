"""PostgreSQL + PostGIS and Redis connection layer (T1A.1).

API note (anti-hallucination rule 2): every third-party API used here was
confirmed against the installed packages in-session, not recalled from
memory — SQLAlchemy 2.0.52 (`sqlalchemy.ext.asyncio.create_async_engine`,
`async_sessionmaker`, `AsyncSession`; the 2.0 `DeclarativeBase`/`Mapped`/
`mapped_column` declarative API), GeoAlchemy2 0.20.0 (`Geography`), and
redis 8.1.0 (`redis.asyncio.Redis.from_url`).

Design notes
------------
* `DATABASE_URL` in `.env.example` is a plain ``postgresql://`` URL (that
  file is verbatim §B.1 and must not change). SQLAlchemy's async engine
  needs an async DBAPI, so the driver is normalised to ``+asyncpg`` here
  rather than by editing the contract'd env file.
* Both tables are keyed on their natural identity — `forecast_id` for the
  regional ensemble, `station_id` for the river stage — so the upsert
  helpers below are idempotent, per the §A quality gate.
* `river_stage_forecast.geom` is a PostGIS ``GEOGRAPHY(POINT, 4326)``
  column with a GiST index, so later nearest-station queries are real
  spatial queries rather than hand-rolled distance arithmetic.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import redis.asyncio as aioredis
from geoalchemy2 import Geography
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from stage1a.config import get_settings
from stage1a.shared.contracts import RegionalEnsembleForecast, RiverStageForecast


class Stage1ADatabaseError(RuntimeError):
    """Raised when a Stage 1A persistence operation fails."""


def _async_database_url(url: str) -> str:
    """Return `url` with an async DBAPI driver.

    `postgresql://` and `postgresql+psycopg2://` are rewritten to
    `postgresql+asyncpg://`; a URL that already names an async driver is
    returned unchanged.
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url[len("postgresql+psycopg2://") :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    raise Stage1ADatabaseError(f"Unsupported DATABASE_URL scheme: {url!r}")


class Base(DeclarativeBase):
    """Declarative base for Stage 1A tables."""


class RegionalEnsembleForecastRow(Base):
    """Storage form of §B.2's `RegionalEnsembleForecast`.

    The bounding box is flattened to four columns and the ensemble members
    are stored as JSONB — the members list is read back whole, never
    queried field-by-field, so a relational child table would buy nothing.
    """

    __tablename__ = "regional_ensemble_forecast"

    forecast_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    resolution_km: Mapped[float] = mapped_column(Float, nullable=False)
    members: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    stored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RiverStageForecastRow(Base):
    """Storage form of §B.2's `RiverStageForecast`."""

    __tablename__ = "river_stage_forecast"

    station_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    station_name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    forecast_horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    trajectory: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    breach_threshold_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    breach_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    station_proximity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_river_stage_forecast_geom", "geom", postgresql_using="gist"),
    )


_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_redis: Optional[aioredis.Redis] = None

# The event loop each singleton was built on. asyncpg connections and Redis
# sockets are bound to the loop that created them, so a singleton reused
# across loops fails with "attached to a different loop" or "Event loop is
# closed". This matters in production, not just in tests: every Celery task
# runs its coroutine under a fresh `asyncio.run()`, so the second task in a
# worker process would otherwise inherit the first task's dead pool.
_engine_loop: Optional[asyncio.AbstractEventLoop] = None
_redis_loop: Optional[asyncio.AbstractEventLoop] = None


def _current_loop() -> Optional[asyncio.AbstractEventLoop]:
    """The running loop, or None when called from synchronous code."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_engine() -> AsyncEngine:
    """Return the async SQLAlchemy engine for the current event loop.

    Rebuilt if the loop has changed since it was created; the previous
    engine belonged to a loop that has already finished, so its pooled
    connections are unusable and are dropped rather than reused.
    """
    global _engine, _engine_loop, _session_factory
    loop = _current_loop()
    if _engine is None or (loop is not None and loop is not _engine_loop):
        settings = get_settings()
        _engine = create_async_engine(
            _async_database_url(settings.database_url),
            pool_pre_ping=True,
            future=True,
        )
        _engine_loop = loop
        _session_factory = None  # must be rebound to the new engine
    return _engine


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield an `AsyncSession`, committing on success and rolling back on error.

    Usable directly as a FastAPI dependency (T1A.8).
    """
    global _session_factory
    engine = get_engine()  # may rebuild and clear _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_redis_client() -> aioredis.Redis:
    """Return the async Redis client for the current event loop.

    Rebuilt on a loop change, for the same reason as `get_engine`.
    """
    global _redis, _redis_loop
    loop = _current_loop()
    if _redis is None or (loop is not None and loop is not _redis_loop):
        _redis = aioredis.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
        _redis_loop = loop
    return _redis


async def init_db() -> None:
    """Create the PostGIS extension and both Stage 1A tables.

    Idempotent: `CREATE EXTENSION IF NOT EXISTS` and SQLAlchemy's
    `checkfirst` create-all mean re-running this is a no-op.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)


async def upsert_regional_forecast(
    session: AsyncSession, forecast: RegionalEnsembleForecast
) -> None:
    """Insert or update `forecast` keyed on `forecast_id` (idempotent)."""
    values: dict[str, Any] = {
        "forecast_id": forecast.forecast_id,
        "source": forecast.source,
        "min_lat": forecast.region_bbox.min_lat,
        "max_lat": forecast.region_bbox.max_lat,
        "min_lon": forecast.region_bbox.min_lon,
        "max_lon": forecast.region_bbox.max_lon,
        "generated_at": forecast.generated_at,
        "resolution_km": forecast.resolution_km,
        "members": [m.model_dump() for m in forecast.members],
        "stored_at": datetime.now(timezone.utc),
    }
    stmt = pg_insert(RegionalEnsembleForecastRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[RegionalEnsembleForecastRow.forecast_id],
        set_={k: v for k, v in values.items() if k != "forecast_id"},
    )
    await session.execute(stmt)


async def upsert_river_stage_forecast(
    session: AsyncSession, forecast: RiverStageForecast
) -> None:
    """Insert or update `forecast` keyed on `station_id` (idempotent)."""
    values: dict[str, Any] = {
        "station_id": forecast.station_id,
        "source": forecast.source,
        "station_name": forecast.station_name,
        "lat": forecast.lat,
        "lon": forecast.lon,
        "geom": f"SRID=4326;POINT({forecast.lon} {forecast.lat})",
        "forecast_horizon_hours": forecast.forecast_horizon_hours,
        "trajectory": [t.model_dump() for t in forecast.trajectory],
        "breach_threshold_m": forecast.breach_threshold_m,
        "breach_probability": forecast.breach_probability,
        "station_proximity_verified": forecast.station_proximity_verified,
        "stored_at": datetime.now(timezone.utc),
    }
    stmt = pg_insert(RiverStageForecastRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[RiverStageForecastRow.station_id],
        set_={k: v for k, v in values.items() if k != "station_id"},
    )
    await session.execute(stmt)


async def dispose_connections() -> None:
    """Close and forget the process-wide engine and Redis client.

    Used by tests and by application shutdown; a disposed singleton is
    recreated lazily on next use.
    """
    global _engine, _session_factory, _redis, _engine_loop, _redis_loop
    loop = _current_loop()
    if _redis is not None:
        if _redis_loop is None or loop is _redis_loop:
            await _redis.aclose()
        _redis = None
        _redis_loop = None
    if _engine is not None:
        if _engine_loop is None or loop is _engine_loop:
            await _engine.dispose()
        _engine = None
        _engine_loop = None
    _session_factory = None
