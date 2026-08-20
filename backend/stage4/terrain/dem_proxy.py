"""Terrain heightmap proxy for the 3D scene (T4B.3).

WHY THIS EXISTS — a real, confirmed cross-stage gap
---------------------------------------------------------------------
T4B.3 asks the frontend to "fetch Stage 1B's regional DEM heightmap and
Stage 2's `TerrainGrid`". Neither is reachable over HTTP — confirmed by
listing every route in all four backends this session:

    stage1b: /api/forecast/downscaled, /api/sensor/reading, /ws/site/...
    stage2:  /api/simulation/site/{id}, /api/simulation/assimilate, /ws/...
    stage3:  /api/damage-ranking/{id}
    stage4:  /api/alert/{id}

Stage 2 computes a real `TerrainGrid` internally and holds real mesh
nodes (with `x_m`/`y_m`/`elevation_m`) in its in-process `SiteRuntimeState`,
but exposes neither: its only endpoint returns `SimulationResult`, whose
`NodeState` carries **no position at all** — just a `node_id` string.
So the 3D scene has no geometry to render.

The project owner chose (2026-08-20) to close this by proxying terrain
through Stage 4 rather than adding an endpoint to Stage 2, keeping this
work inside Stage 4's own module boundary (its CLAUDE.md rule 6).

WHY READING THE SAME DEM IS HONEST, NOT A SUBSTITUTE
---------------------------------------------------------------------
This module reads the *same* Stage 1B DEM raster that Stage 2's own
`interpolate_terrain` reads, via the *same* `dem_metadata` lookup. That
is not an approximation of Stage 2's terrain — Stage 2's `TerrainGrid`
is itself derived from this raster by resampling, which is exactly why
its `interpolated_from_regional_dem` flag is `True` (Stage 2's CLAUDE.md
ground truth: the GLB has no terrain; it is constructed from this DEM).

Two real consequences, both stated rather than smoothed over:
  * The two LODs are derived from ONE native-resolution read and share
    source pixels exactly, so the "no visible seam" T4B.3 asks for is
    structural rather than tuned. NOTE: an earlier version claimed this
    while doing two independent bilinear windowed reads — that claim was
    false and measuring it proved it (2.9m disagreement, a visible cliff
    in the render). See `read_lod_pair` for what actually makes it true.
  * This is still DEM-interpolated terrain, NOT a survey. `interpolated_
    from_regional_dem` is propagated as `True` so the About page (T4C.6)
    can state the limitation, per Stage 4's CLAUDE.md ground truth. At
    ~30m CartoDEM sampling, a ~300m site patch holds only ~10x10 real
    samples; the site LOD is at the raster's native resolution and no
    detail beyond it is synthesised.

What this module does NOT provide: Stage 2's site-local computational
mesh (per-node wall/road tagging, building footprints). Those still live
only inside Stage 2. T4B.4 (buildings/roads) loads the GLB directly, so
it does not need them; if a later task needs real mesh node positions,
that will require a Stage 2 endpoint and should be raised then rather
than faked here.

NODATA IS `None`, NEVER A FABRICATED NUMBER
---------------------------------------------------------------------
CartoDEM has real voids, and Stage 1B masks physically implausible
values to NaN (its `processing.py` documents ~7% of raw pixels). JSON
cannot carry NaN, so those cells are emitted as `null`. The renderer
substitutes the patch mean and says so — filling them here with a
plausible-looking number would launder missing data into apparent data.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform
from rasterio.windows import from_bounds as window_from_bounds
from sqlalchemy import Column, Float, MetaData, String, Table, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.stage4.config import settings
from backend.stage4.shared.contracts import TerrainHeightmap, SiteTerrainResponse

logger = logging.getLogger(__name__)

_METERS_PER_DEGREE_LAT = 111_320.0

_metadata = MetaData()

#: Read-only view of Stage 1B's `dem_metadata`. Column names/types copied
#: verbatim from `backend/stage1b/db.py`'s `DemMetadataRow` — only the
#: columns actually read here. Deliberately a partial Table used ONLY for
#: SELECT: never pass this to `create_all()`, which would create an
#: incomplete version of a table this stage does not own (a real bug that
#: already happened once in this project — see stage2/tests/test_terrain.py's
#: `test_find_terrain_grid_path_real_db_round_trip` docstring).
dem_metadata_table = Table(
    "dem_metadata",
    _metadata,
    Column("min_lat", Float),
    Column("max_lat", Float),
    Column("min_lon", Float),
    Column("max_lon", Float),
    Column("raster_path", String),
    Column("terrain_grid_path", String),
)


class TerrainUnavailableError(RuntimeError):
    """No real DEM covers the requested site, or it could not be read.

    Raised instead of returning a flat/synthetic surface — a fabricated
    terrain would be indistinguishable from real terrain in the 3D scene,
    which is exactly the kind of silent substitution this project's
    honesty rules forbid.
    """


def _to_asyncpg_url(database_url: str) -> str:
    """Normalise a plain `postgresql://` URL to the async driver.

    Mirrors Stage 1A/1B/2's identical helpers — SQLAlchemy's async engine
    requires an async DBAPI.
    """
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url[len("postgresql://") :]
    return database_url


_engine: Optional[AsyncEngine] = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _to_asyncpg_url(settings.database_url), pool_pre_ping=True
        )
    return _engine


async def find_terrain_raster_path(site_lat: float, site_lon: float) -> str:
    """Return the best real DEM raster covering `(site_lat, site_lon)`.

    PREFERS `raster_path` (Stage 1B's RAW fetched CartoDEM) over
    `terrain_grid_path` (its derived slope/aspect product) — a real,
    measured decision, not a guess. Confirmed against this project's own
    registered DEM row this session:

        raster_path        3600x3600, EPSG:4326, ~30m/px   <- used
        terrain_grid_path    56x55,   EPSG:32644, 2000m/px

    Stage 1B derives the terrain grid at `grid_resolution_km` (2km here),
    which is correct for its own downscaling purpose but is far too coarse
    to render: a 300m site patch is a *fraction of one pixel* of it. An
    earlier version of this function used it and produced a real 2x2 grid
    with a single repeated elevation — caught by running this against the
    real raster, not by inspection.

    Falls back to `terrain_grid_path` only if no raw raster is recorded,
    so a row created by an older pipeline still renders something real.

    Raises:
        TerrainUnavailableError: if no row covers the point, or the row
            records neither raster. Never invents a path.
    """
    stmt = select(
        dem_metadata_table.c.raster_path,
        dem_metadata_table.c.terrain_grid_path,
    ).where(
        dem_metadata_table.c.min_lat <= site_lat,
        dem_metadata_table.c.max_lat >= site_lat,
        dem_metadata_table.c.min_lon <= site_lon,
        dem_metadata_table.c.max_lon >= site_lon,
    )
    async with _get_engine().connect() as conn:
        row = (await conn.execute(stmt)).first()

    if row is None:
        raise TerrainUnavailableError(
            f"No Stage 1B dem_metadata row covers ({site_lat}, {site_lon}). "
            "Run Stage 1B's DEM fetch/processing for this region first."
        )

    raw_path, derived_path = row[0], row[1]
    chosen = raw_path or derived_path
    if not chosen:
        raise TerrainUnavailableError(
            f"The dem_metadata row covering ({site_lat}, {site_lon}) records "
            "neither a raw raster nor a derived terrain grid."
        )
    if not raw_path:
        logger.warning(
            "No raw DEM raster recorded; falling back to the derived terrain "
            "grid (%s), which is much coarser and will render blocky.",
            derived_path,
        )
    return str(chosen)


def _bbox_around(lat: float, lon: float, half_span_m: float) -> Tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lon, max_lon) spanning `half_span_m` each way.

    Flat-earth approximation, consistent with how Stage 1B/2 convert
    metres to degrees elsewhere in this project.
    """
    d_lat = half_span_m / _METERS_PER_DEGREE_LAT
    d_lon = half_span_m / (_METERS_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    return lat - d_lat, lat + d_lat, lon - d_lon, lon + d_lon


def _grid_to_heightmap(
    data: np.ndarray,
    bbox_latlon: Tuple[float, float, float, float],
) -> TerrainHeightmap:
    """Wrap a real elevation array + its real bbox as a `TerrainHeightmap`."""
    min_lat, max_lat, min_lon, max_lon = bbox_latlon
    rows, cols = data.shape

    finite = data[np.isfinite(data)]
    if finite.size == 0:
        raise TerrainUnavailableError(
            f"Terrain window over {bbox_latlon} contains no finite elevation "
            "values — refusing to return an all-null surface."
        )

    span_m = (max_lat - min_lat) * _METERS_PER_DEGREE_LAT
    resolution_m = span_m / max(rows - 1, 1)

    grid: List[List[Optional[float]]] = [
        [None if not math.isfinite(v) else round(float(v), 3) for v in row]
        for row in data
    ]
    return TerrainHeightmap(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        rows=rows,
        cols=cols,
        resolution_m=round(resolution_m, 3),
        elevation_grid=grid,
        min_elevation_m=round(float(finite.min()), 3),
        max_elevation_m=round(float(finite.max()), 3),
        nodata_cell_count=int(np.count_nonzero(~np.isfinite(data))),
    )


def read_lod_pair(
    raster_path: str,
    regional_bbox: Tuple[float, float, float, float],
    site_bbox: Tuple[float, float, float, float],
    regional_max_dim: int,
) -> Tuple[TerrainHeightmap, TerrainHeightmap]:
    """Read BOTH terrain LODs from ONE native-resolution window.

    GENUINELY SEAMLESS, AND WHY THE OBVIOUS APPROACH IS NOT
    ---------------------------------------------------------------
    An earlier version read the two extents as two independent windowed,
    bilinear-resampled reads of the same raster and claimed they agreed
    "by construction". **That was wrong, and measuring it proved it**: the
    two windows land on different sampling phases, so identical lat/lons
    disagreed by up to 2.9m — a real, visible cliff around the site patch
    in the rendered scene. Same raster does NOT mean same sampling.

    This reads the regional extent ONCE at the raster's native resolution,
    then derives both LODs from that single array:
      * regional = `native[::step, ::step]` (a strided subsample)
      * site     = a slice of the same array, snapped so its edges land
                   exactly on regional sample lines (`step` multiples)
    Every shared vertex is therefore literally the same source pixel — not
    an interpolation that happens to be close. Along the site's edges the
    regional surface linearly interpolates between the same two endpoint
    pixels the site slice starts and ends on, which is an ordinary LOD
    stitch with no discontinuity.

    Also fixes an inverted LOD: previously the "detailed" site patch came
    out at 33.3m/cell against a 31.25m/cell regional — i.e. coarser than
    the surround. The site slice is now at the raster's native resolution
    and the regional is genuinely decimated below it.

    Raises:
        TerrainUnavailableError: if the raster can't be read, or the
            requested extents don't intersect its real coverage.
    """
    r_min_lat, r_max_lat, r_min_lon, r_max_lon = regional_bbox
    s_min_lat, s_max_lat, s_min_lon, s_max_lon = site_bbox

    try:
        with rasterio.open(raster_path) as src:
            xs, ys = warp_transform(
                "EPSG:4326", src.crs, [r_min_lon, r_max_lon], [r_min_lat, r_max_lat]
            )
            window = window_from_bounds(
                min(xs), min(ys), max(xs), max(ys), src.transform
            )
            # Snap to whole source pixels so every sample below is a real
            # pixel rather than a phase-shifted interpolation of two.
            window = window.round_offsets().round_lengths()
            if window.height <= 1 or window.width <= 1:
                raise TerrainUnavailableError(
                    f"Regional bbox {regional_bbox} does not meaningfully "
                    f"intersect {raster_path}'s coverage {src.bounds} ({src.crs})."
                )
            native = src.read(
                1, window=window, boundless=True, fill_value=float("nan")
            ).astype(float)
            win_bounds = rasterio.windows.bounds(window, src.transform)
            # Native window's real lat/lon extent (its own corners, not the
            # requested bbox -- they differ by the pixel snapping above).
            lons, lats = warp_transform(
                src.crs,
                "EPSG:4326",
                [win_bounds[0], win_bounds[2]],
                [win_bounds[1], win_bounds[3]],
            )
    except TerrainUnavailableError:
        raise
    except Exception as exc:  # rasterio raises its own error types
        raise TerrainUnavailableError(
            f"Failed to read terrain raster {raster_path}: {exc}"
        ) from exc

    n_rows, n_cols = native.shape
    nat_min_lat, nat_max_lat = min(lats), max(lats)
    nat_min_lon, nat_max_lon = min(lons), max(lons)

    def _lat_to_row(lat: float) -> float:
        # Row 0 is the north edge.
        return (nat_max_lat - lat) / (nat_max_lat - nat_min_lat) * (n_rows - 1)

    def _lon_to_col(lon: float) -> float:
        return (lon - nat_min_lon) / (nat_max_lon - nat_min_lon) * (n_cols - 1)

    step = max(1, int(math.ceil(max(n_rows, n_cols) / max(regional_max_dim, 2))))

    # Site slice, snapped OUTWARD to `step` multiples so its corners coincide
    # exactly with regional sample lines.
    r0 = int(math.floor(_lat_to_row(s_max_lat) / step) * step)
    r1 = int(math.ceil(_lat_to_row(s_min_lat) / step) * step)
    c0 = int(math.floor(_lon_to_col(s_min_lon) / step) * step)
    c1 = int(math.ceil(_lon_to_col(s_max_lon) / step) * step)
    r0, c0 = max(0, r0), max(0, c0)
    r1, c1 = min(n_rows - 1, r1), min(n_cols - 1, c1)
    if r1 - r0 < 1 or c1 - c0 < 1:
        raise TerrainUnavailableError(
            f"Site bbox {site_bbox} is smaller than one DEM pixel of "
            f"{raster_path} — no real site-local detail exists to render."
        )

    regional_data = native[::step, ::step]
    site_data = native[r0 : r1 + 1, c0 : c1 + 1]

    def _row_to_lat(r: float) -> float:
        return nat_max_lat - (r / (n_rows - 1)) * (nat_max_lat - nat_min_lat)

    def _col_to_lon(c: float) -> float:
        return nat_min_lon + (c / (n_cols - 1)) * (nat_max_lon - nat_min_lon)

    regional_bbox_real = (
        _row_to_lat((regional_data.shape[0] - 1) * step),
        nat_max_lat,
        nat_min_lon,
        _col_to_lon((regional_data.shape[1] - 1) * step),
    )
    site_bbox_real = (_row_to_lat(r1), _row_to_lat(r0), _col_to_lon(c0), _col_to_lon(c1))

    return (
        _grid_to_heightmap(regional_data, regional_bbox_real),
        _grid_to_heightmap(site_data, site_bbox_real),
    )


async def build_site_terrain(site_id: str) -> SiteTerrainResponse:
    """Real regional + site-local heightmaps for `site_id`, from Stage 1B's DEM.

    Both patches are windows onto the same real raster (see module
    docstring), so they are seamless by construction.

    Raises:
        TerrainUnavailableError: if the site coordinates aren't configured,
            no DEM covers them, or the raster can't be read.
    """
    lat, lon = settings.target_site_lat, settings.target_site_lon
    if lat is None or lon is None:
        raise TerrainUnavailableError(
            "TARGET_SITE_LAT/TARGET_SITE_LON are not configured for Stage 4 — "
            "cannot locate the site's terrain without real coordinates."
        )

    raster_path = await find_terrain_raster_path(lat, lon)

    # Both LODs come from ONE native read so they share source pixels
    # exactly -- see read_lod_pair's docstring for why two independent
    # windowed reads produced a real 2.9m seam.
    regional, site = read_lod_pair(
        raster_path,
        _bbox_around(lat, lon, settings.regional_terrain_half_span_m),
        _bbox_around(lat, lon, settings.site_terrain_half_span_m),
        settings.regional_terrain_max_dim,
    )

    return SiteTerrainResponse(
        site_id=site_id,
        site_lat=lat,
        site_lon=lon,
        # Propagated as True to match Stage 2's own TerrainGrid honesty flag:
        # this surface is DEM-derived, never a survey. T4C.6's About page
        # must state this (Stage 4 CLAUDE.md ground truth).
        interpolated_from_regional_dem=True,
        source_raster=raster_path,
        regional=regional,
        site=site,
    )
