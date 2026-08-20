"""DEM interpolation to site terrain (T2.2).

Since the GLB has no terrain, this builds one from Stage 1B's regional DEM
(via `dem_source.find_terrain_grid_path`), positioned using the real-world
bounding box the site's buildings occupy — computed from the anchor point
and T2.1's mesh extents.

API CONFIRMED IN-SESSION (rasterio 1.5.1) — reusing what's already
verified working in this repo: `rasterio.warp.reproject` /
`calculate_default_transform` are the exact functions
`backend/stage1b/dem/processing.py` already uses successfully against a
real fetched raster (see that module's docstring for its own VERIFY);
`rasterio.warp.transform` and `rasterio.transform.from_origin`'s
signatures were checked directly against the installed package this
session (`from_origin(west, north, xsize, ysize)`,
`transform(src_crs, dst_crs, xs, ys, zs=None)`).

Scene-to-real-world axis conversion (an explicitly stated, unconfirmed
assumption) lives in `anchor_transform.py`, shared with
`footprint_extraction.py` — see that module's docstring.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import rasterio
import trimesh
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterio.warp import transform as warp_transform

from stage2.shared.contracts import AnchorPoint, TerrainGrid
from stage2.terrain.anchor_transform import scene_offset_to_latlon as _scene_offset_to_latlon


def compute_site_bbox_latlon(
    objects: Dict[str, trimesh.Trimesh], anchor: AnchorPoint
) -> Tuple[float, float, float, float]:
    """Real-world (min_lat, max_lat, min_lon, max_lon) covering every object's mesh extents."""
    lats = []
    lons = []
    for mesh in objects.values():
        min_corner, max_corner = mesh.bounds
        for x in (min_corner[0], max_corner[0]):
            for y in (min_corner[1], max_corner[1]):
                for z in (min_corner[2], max_corner[2]):
                    lat, lon = _scene_offset_to_latlon(
                        np.array([x, y, z]), anchor
                    )
                    lats.append(lat)
                    lons.append(lon)
    return min(lats), max(lats), min(lons), max(lons)


def interpolate_terrain(
    dem_raster_path: str | Path,
    site_id: str,
    bbox_latlon: Tuple[float, float, float, float],
    resolution_m: float,
) -> TerrainGrid:
    """Resample Stage 1B's regional elevation band to `resolution_m` over `bbox_latlon`.

    `dem_raster_path` is Stage 1B's 3-band terrain GeoTIFF (band 1 =
    elevation_m, per `backend/stage1b/dem/processing.py`'s
    `write_terrain_grids_geotiff`) — only band 1 is read; slope/aspect
    (bands 2/3) aren't part of `TerrainGrid`.

    Always sets `interpolated_from_regional_dem = True` — this is an
    approximation of a coarser regional DEM, never a real site survey
    (photogrammetry, which would have provided that, didn't work out; see
    CLAUDE.md ground truth).
    """
    min_lat, max_lat, min_lon, max_lon = bbox_latlon

    with rasterio.open(dem_raster_path) as src:
        src_crs = src.crs
        xs, ys = warp_transform(
            "EPSG:4326",
            src_crs,
            [min_lon, max_lon],
            [min_lat, max_lat],
        )
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        width = max(1, int(math.ceil((max_x - min_x) / resolution_m)))
        height = max(1, int(math.ceil((max_y - min_y) / resolution_m)))
        dst_transform = from_origin(min_x, max_y, resolution_m, resolution_m)

        elevation = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=elevation,
            src_transform=src.transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=src_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    origin_lon, origin_lat = warp_transform(src_crs, "EPSG:4326", [min_x], [max_y])
    origin_lat_val = origin_lat[0]
    origin_lon_val = origin_lon[0]

    return TerrainGrid(
        site_id=site_id,
        resolution_m=resolution_m,
        origin_lat=origin_lat_val,
        origin_lon=origin_lon_val,
        elevation_grid=elevation.tolist(),
        interpolated_from_regional_dem=True,
    )
