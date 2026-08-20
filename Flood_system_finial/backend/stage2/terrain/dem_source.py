"""Read-only access to Stage 1B's `dem_metadata` table (T2.2).

WHY A STANDALONE QUERY, NOT AN IMPORT OF STAGE 1B'S CODE
------------------------------------------------------------
Confirmed by reading `backend/stage1b/routes.py`: there is no HTTP API for
DEM data (only `/api/forecast/downscaled` and `/api/sensor/reading`).
`backend/stage1b/db.py`'s `DemMetadataRow` ORM class points at the real
terrain GeoTIFF via `terrain_grid_path`. Rather than `import
backend.stage1b.db` (which would couple Stage 2 to Stage 1B's internal
code — not done anywhere else in this project; only
`backend/shared/contracts.py` is shared across stages), this module runs
its own minimal, read-only SQL query against the same table, using
SQLAlchemy Core against a real, confirmed schema (column names/types
copied from `backend/stage1b/db.py`'s `DemMetadataRow`, not guessed).

Confirmed default: Stage 1B's own `config.py`/`.env.example` both default
`DATABASE_URL` to `postgresql://localhost:5432/floodsystem` — the same
value Stage 1A uses too. The project's demo deployment (TRD §3.6) shares
one local Postgres instance/database across stages, each owning its own
tables — `STAGE1B_DATABASE_URL` here defaults to that same value.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Column, Float, MetaData, String, Table, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stage2.config import Stage2Settings, get_settings
from stage2.terrain.errors import Stage1BTerrainUnavailableError

_metadata = MetaData()

# Schema copied verbatim from backend/stage1b/db.py's DemMetadataRow —
# only the columns this module actually reads.
dem_metadata_table = Table(
    "dem_metadata",
    _metadata,
    Column("min_lat", Float),
    Column("max_lat", Float),
    Column("min_lon", Float),
    Column("max_lon", Float),
    Column("terrain_grid_path", String),
)


def _to_asyncpg_url(database_url: str) -> str:
    """Normalise a plain `postgresql://` URL to the async driver.

    Mirrors Stage 1A's `db.py`/Stage 1B's `db.py`, both of which do this
    same normalisation for the same reason (SQLAlchemy's async engine
    needs an async DBAPI).
    """
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url[len("postgresql://") :]
    return database_url


_engine: Optional[AsyncEngine] = None


def _get_stage1b_engine(settings: Stage2Settings) -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _to_asyncpg_url(settings.stage1b_database_url), pool_pre_ping=True
        )
    return _engine


async def find_terrain_grid_path(
    site_lat: float, site_lon: float, settings: Optional[Stage2Settings] = None
) -> str:
    """Return the `terrain_grid_path` of the `dem_metadata` row covering `(site_lat, site_lon)`.

    Matches Stage 1B's own bbox-containment query pattern (seen in
    `stage1b/routes.py`), plus `terrain_grid_path IS NOT NULL` (a row can
    exist from T1B.2's raw fetch before T1B.3 has derived the terrain
    grid). Ordered by no particular column when multiple rows match — if
    that ever matters (overlapping regions at different resolutions),
    revisit; not a real scenario yet with a single demo site.

    Raises:
        Stage1BTerrainUnavailableError: if no matching row exists. Never
            fabricates a terrain grid in its place.
    """
    settings = settings or get_settings()
    engine = _get_stage1b_engine(settings)

    stmt = select(dem_metadata_table.c.terrain_grid_path).where(
        dem_metadata_table.c.min_lat <= site_lat,
        dem_metadata_table.c.max_lat >= site_lat,
        dem_metadata_table.c.min_lon <= site_lon,
        dem_metadata_table.c.max_lon >= site_lon,
        dem_metadata_table.c.terrain_grid_path.is_not(None),
    )
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        row = result.first()

    if row is None:
        raise Stage1BTerrainUnavailableError(
            f"No Stage 1B dem_metadata row (with a derived terrain grid) "
            f"covers ({site_lat}, {site_lon}). Run Stage 1B's T1B.2/T1B.3 "
            "for this region first."
        )
    return str(row[0])
