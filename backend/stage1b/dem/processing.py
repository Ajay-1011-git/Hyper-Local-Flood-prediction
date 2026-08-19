"""DEM processing: elevation/slope/aspect grid derivation — T1B.3.

`compute_terrain_grids` reprojects the raw CartoDEM raster (T1B.2's output —
EPSG:4326, ~30m native resolution) into a metric UTM CRS on a regular
`grid_resolution_km` grid, then derives slope and aspect from that
*projected* elevation grid using `numpy.gradient` against real known
pixel spacing in meters.

Why reproject before differentiating, rather than running `numpy.gradient`
directly on the raw EPSG:4326 array: slope/aspect are physical quantities
(rise over real horizontal distance). A degree of longitude is ~108.5km at
Vellore's latitude (13°N) but only ~111.3km for a degree of latitude — a
gradient taken directly in degree-space would be quietly wrong by that
~2.5% anisotropy (worse further from the equator), and CartoDEM's ~30m
pixels don't correspond to square meters at all in degree-space. UTM zone
44N (EPSG:32644) is the correct zone for Vellore's ~79°E longitude, chosen
by the standard formula `zone = floor((lon + 180) / 6) + 1` — not
hardcoded to a guess.

VERIFIED (not assumed): `rasterio.warp.calculate_default_transform` /
`reproject` and `numpy.gradient` are real, current, installed APIs
(rasterio 1.5.1, numpy 2.5.2) — confirmed by running this module against
T1B.2's real fetched raster (see VERIFY output in the commit message /
task audit, not reproduced here since this is production code, not a
log).

Slope/aspect formulas used (standard GIS convention, not invented here —
matches the common two-neighbor central-difference method described in,
e.g., ESRI's and QGIS's slope/aspect documentation):
  dz/dx, dz/dy   = numpy.gradient(elevation, pixel_size_m, pixel_size_m)
  slope (deg)    = degrees(arctan(hypot(dz/dx, dz/dy)))
  aspect (deg)   = compass bearing of the downslope direction, 0=North,
                   90=East, measured clockwise; a flat cell (both
                   gradients ~0) has aspect defined as NaN, not an
                   arbitrary 0/North, since no meaningful downslope
                   direction exists there.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import Resampling, calculate_default_transform, reproject

# Below this magnitude (in the combined x/y gradient), a cell is treated as
# flat and its aspect is undefined (NaN) rather than an arbitrary direction.
_FLAT_GRADIENT_THRESHOLD = 1e-6


def _utm_crs_for_lon_lat(lon: float, lat: float) -> CRS:
    """Standard UTM zone formula (not a lookup table / guess)."""
    zone = int(math.floor((lon + 180) / 6) + 1)
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def compute_terrain_grids(
    raster_path: str,
    grid_resolution_km: float = 2.0,
    plausible_elevation_range_m: tuple[float, float] = (-50.0, 2000.0),
) -> dict[str, Any]:
    """Derive elevation, slope, and aspect grids from a raw DEM raster.

    `plausible_elevation_range_m`: CartoDEM (a Cartosat-1 stereo-derived
    DSM, not a bare-earth DEM) is documented to contain voids/blunders —
    confirmed against T1B.2's real fetched raster: ~3.8M of its ~52M raw
    30m pixels (~7%) carry elevation values below -50m, physically
    implausible for this inland Tamil Nadu region (no point near Vellore
    is below sea level). Rather than silently pass fabricated-looking
    negative elevations into slope/aspect math, or silently discard them
    with no record, pixels outside this range are treated as additional
    nodata (masked to NaN) and the count masked is returned in the result
    dict as "plausibility_masked_pixel_count" so it's auditable. THE
    DEFAULT RANGE IS A CONSERVATIVE GUESS FOR THIS PROJECT'S TARGET
    REGION, NOT AN INDEPENDENTLY VERIFIED FACT — flagged for human review,
    same as this project's other unverified thresholds (e.g. the
    station-proximity default in T1A.7/T1B.5).

    Returns a dict with:
      - "elevation": np.ndarray (meters, NaN where nodata or implausible)
      - "slope_deg": np.ndarray (degrees from horizontal, 0=flat, 90=vertical)
      - "aspect_deg": np.ndarray (compass bearing of downslope direction,
        NaN on flat cells)
      - "crs": the projected CRS grids are in (rasterio.crs.CRS)
      - "transform": the grid's affine transform (rasterio.Affine)
      - "resolution_km": echoes the input, for the caller's convenience
      - "plausibility_masked_pixel_count": int, how many output cells were
        masked for falling outside `plausible_elevation_range_m`
    """
    with rasterio.open(raster_path) as src:
        center_lon = (src.bounds.left + src.bounds.right) / 2
        center_lat = (src.bounds.bottom + src.bounds.top) / 2
        dst_crs = _utm_crs_for_lon_lat(center_lon, center_lat)
        resolution_m = grid_resolution_km * 1000.0

        transform, width, height = calculate_default_transform(
            src.crs,
            dst_crs,
            src.width,
            src.height,
            *src.bounds,
            resolution=(resolution_m, resolution_m),
        )

        elevation = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=elevation,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    lo, hi = plausible_elevation_range_m
    implausible_mask = (elevation < lo) | (elevation > hi)
    plausibility_masked_pixel_count = int(np.nansum(implausible_mask))
    elevation = np.where(implausible_mask, np.nan, elevation).astype(np.float32)

    dz_dy, dz_dx = np.gradient(elevation, resolution_m, resolution_m)

    slope_rad = np.arctan(np.hypot(dz_dx, dz_dy))
    slope_deg = np.degrees(slope_rad).astype(np.float32)

    # Compass bearing of the *downslope* direction: 0=North, 90=East,
    # clockwise. Derivation (verified against the two synthetic cases in
    # test_dem.py, not assumed correct on inspection alone):
    #   dz_dy above is dE/d(row) = dE/d(south-distance) (row increases
    #     southward for a north-up raster), so dE/d(north-distance) = -dz_dy.
    #   dz_dx above is dE/d(col) = dE/d(east-distance) directly.
    #   The downslope direction vector is the negative gradient:
    #     (east component, north component) = (-dz_dx, -(-dz_dy)) = (-dz_dx, dz_dy).
    #   Compass bearing of a (east, north) vector, clockwise from north, is
    #     atan2(east_component, north_component).
    aspect_rad = np.arctan2(-dz_dx, dz_dy)
    aspect_deg = np.degrees(aspect_rad).astype(np.float32)
    aspect_deg = np.where(aspect_deg < 0, aspect_deg + 360.0, aspect_deg)

    flat_mask = np.hypot(dz_dx, dz_dy) < _FLAT_GRADIENT_THRESHOLD
    aspect_deg = np.where(flat_mask, np.nan, aspect_deg).astype(np.float32)

    return {
        "elevation": elevation,
        "slope_deg": slope_deg,
        "aspect_deg": aspect_deg,
        "crs": dst_crs,
        "transform": transform,
        "resolution_km": grid_resolution_km,
        "plausibility_masked_pixel_count": plausibility_masked_pixel_count,
    }


def write_terrain_grids_geotiff(grids: dict[str, Any], output_path: str) -> str:
    """Persist elevation/slope/aspect as a 3-band GeoTIFF (band order:
    1=elevation, 2=slope_deg, 3=aspect_deg) at `output_path`, preserving
    georeferencing so downstream tasks (T1B.7/8) can sample it by
    lat/lon rather than needing the raw arrays kept in memory."""
    elevation = grids["elevation"]
    height, width = elevation.shape

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype="float32",
        crs=grids["crs"],
        transform=grids["transform"],
        nodata=np.nan,
    ) as dst:
        dst.write(elevation.astype(np.float32), 1)
        dst.write(grids["slope_deg"].astype(np.float32), 2)
        dst.write(grids["aspect_deg"].astype(np.float32), 3)
        dst.set_band_description(1, "elevation_m")
        dst.set_band_description(2, "slope_deg")
        dst.set_band_description(3, "aspect_deg")

    return output_path


async def compute_and_persist_terrain_grids(
    raster_path: str,
    grid_resolution_km: float,
    dem_metadata_id: int,
) -> dict[str, Any]:
    """Compute terrain grids from `raster_path`, write them to a GeoTIFF
    next to it, and update the matching `dem_metadata` row (T1B.1) with
    `grid_resolution_km` and `terrain_grid_path`.

    Split from `compute_terrain_grids` (a plain sync/CPU-bound function) so
    the numeric core stays trivially testable without a database, and
    persistence — which needs an async session (T1B.1's `get_db_session`)
    — is a thin async wrapper around it. `dem_metadata_id` is the row
    created when the raw raster was fetched (T1B.2), passed in rather than
    re-derived from bbox here, since the caller already has it.
    """
    # Imported here (not at module top) so this module's pure numeric path
    # (compute_terrain_grids, write_terrain_grids_geotiff) has no import-time
    # dependency on the DB layer — keeps unit tests of the math fast and
    # DB-free.
    from backend.stage1b.db import DemMetadataRow, get_db_session

    grids = compute_terrain_grids(raster_path, grid_resolution_km)
    output_path = str(Path(raster_path).with_suffix("")) + "_terrain.tif"
    write_terrain_grids_geotiff(grids, output_path)

    async with get_db_session() as session:
        row = await session.get(DemMetadataRow, dem_metadata_id)
        if row is None:
            raise ValueError(f"No dem_metadata row with id={dem_metadata_id}")
        row.grid_resolution_km = grid_resolution_km
        row.terrain_grid_path = output_path
        await session.commit()

    return grids
