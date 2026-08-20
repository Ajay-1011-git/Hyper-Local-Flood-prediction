"""Database & Redis connection layer — T1B.1.

Provides `get_db_session()` (an async SQLAlchemy session against
PostgreSQL+PostGIS) and `get_redis_client()` (an async Redis client), and
defines/creates the three tables this stage owns:

- `downscaled_forecast_field` — one row per (site_id, source_forecast_id):
  the persisted form of the `DownscaledForecastField` contract (T1B.8/9's
  output). `site_lat`/`site_lon` are stored both as plain floats (so a row
  round-trips back into the Pydantic model without lossy geometry parsing)
  and as a PostGIS `POINT` geometry column (`site_geom`), per this task's
  requirement to index site location geospatially.
- `sensor_reading` — one row per (sensor_id, timestamp): the persisted form
  of the `SensorReading` contract (T1B.11's input).
- `dem_metadata` — one row per processed DEM raster (T1B.2/T1B.3's output):
  references the raster file on disk by path rather than storing the
  binary in the database, per the project's stated convention.

Verified in-session: SQLAlchemy 2.0's async engine/session API
(`sqlalchemy.ext.asyncio`), GeoAlchemy2 0.20's `Geometry` column type for
PostGIS columns, and `redis.asyncio`'s client — none of these were
assumed from memory (see requirements.txt for the exact pinned versions).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

import redis.asyncio as redis_asyncio
from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.stage1b.config import settings


class Base(DeclarativeBase):
    """Declarative base for every table this stage owns."""


class DownscaledForecastFieldRow(Base):
    """Persisted `DownscaledForecastField` (backend/shared/contracts.py).

    `members` (the nested per-ensemble-member trajectory list) is stored as
    JSONB rather than normalized into child tables — the contract treats it
    as an opaque nested structure the API round-trips whole, and Stage 2
    (the eventual consumer) reads it the same way.
    """

    __tablename__ = "downscaled_forecast_field"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "source_forecast_id", name="uq_downscaled_site_forecast"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    site_lat: Mapped[float] = mapped_column(Float, nullable=False)
    site_lon: Mapped[float] = mapped_column(Float, nullable=False)
    site_geom: Mapped[str] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=False
    )
    resolution_km: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    calibration_source: Mapped[str] = mapped_column(
        String, nullable=False, default="TN WRD"
    )
    calibration_confidence: Mapped[str] = mapped_column(String, nullable=False)
    source_forecast_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    members: Mapped[list] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SensorReadingRow(Base):
    """Persisted `SensorReading` (backend/shared/contracts.py)."""

    __tablename__ = "sensor_reading"
    __table_args__ = (
        UniqueConstraint("sensor_id", "timestamp", name="uq_sensor_reading_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sensor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    distance_cm: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assimilated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DemMetadataRow(Base):
    """Metadata for a processed DEM raster (T1B.2 raw fetch, T1B.3 terrain grids).

    The raster itself and any derived terrain-grid arrays live on disk under
    `DEM_RASTER_STORAGE_DIR`; this row just points at them so later tasks
    (T1B.3, T1B.7/8) can look up the right file without re-fetching/
    re-deriving it.
    """

    __tablename__ = "dem_metadata"
    __table_args__ = (
        UniqueConstraint(
            "min_lat",
            "max_lat",
            "min_lon",
            "max_lon",
            "grid_resolution_km",
            name="uq_dem_bbox_resolution",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    raster_path: Mapped[str] = mapped_column(String, nullable=False)
    # Populated once T1B.3 derives elevation/slope/aspect grids from the raw
    # raster above; NULL until then. Not required at T1B.1 (this task
    # exists so T1B.3 has a table to write into, per its "Files you may
    # touch" not including db.py).
    grid_resolution_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    terrain_grid_path: Mapped[str | None] = mapped_column(String, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis_client: redis_asyncio.Redis | None = None


def _to_asyncpg_url(database_url: str) -> str:
    """Normalize a plain `postgresql://` URL (as in .env.example / §B.1) to
    the `postgresql+asyncpg://` form SQLAlchemy's async engine requires.
    Leaves an already-qualified URL (e.g. one a test overrides with a
    different driver) untouched.
    """
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url[len("postgresql://") :]
    return database_url


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(_to_asyncpg_url(settings.database_url))
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False
        )
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a `AsyncSession`.

    Usage: `async with get_db_session() as session: ...`
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


def get_redis_client() -> redis_asyncio.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_asyncio.Redis.from_url(
            settings.redis_url, decode_responses=True
        )
    return _redis_client


async def init_models() -> None:
    """Create the PostGIS extension (if missing) and this stage's tables.

    Idempotent: `CREATE EXTENSION IF NOT EXISTS` and
    `Base.metadata.create_all` are both safe to re-run.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    """Close the engine and Redis connection. Call on app shutdown / in tests."""
    global _engine, _redis_client
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
