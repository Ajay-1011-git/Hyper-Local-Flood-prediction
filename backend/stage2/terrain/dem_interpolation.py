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

SCENE-TO-REAL-WORLD AXIS MAPPING — A STATED ASSUMPTION, NOT CONFIRMED
---------------------------------------------------------------------------
`AnchorPoint.north_axis` (e.g. `"+Y"`) names only which scene axis points
geographic North — a single label, not a full rotation. This module
assumes: (1) the ground plane is the scene's X/Y axes (Z is up, matching
Blender's default), and (2) the horizontal axes are right-handed East/
North/Up, so the axis perpendicular to `north_axis` is East, in a fixed
90-degree relationship. Only the four axis-aligned values
(`+X`/`-X`/`+Y`/`-Y`) are handled — anything else raises
`AmbiguousNorthAxisError` rather than guessing, per CLAUDE.md rule 4. THIS
MUST BE CONFIRMED against the real `anchor_point.json` once it exists; if
Blender's actual convention differs (e.g. Y-up instead of Z-up), this
mapping needs correcting, not the axis-label parsing.
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
from stage2.terrain.errors import AmbiguousNorthAxisError

_METERS_PER_DEGREE_LAT = 111_320.0

# (north_axis) -> (east_scene_axis_index, east_sign, north_scene_axis_index, north_sign)
# Ground plane is scene (x=0, y=1); z (index 2) is up and unused here.
_AXIS_MAPPING: Dict[str, Tuple[int, float, int, float]] = {
    "+Y": (0, 1.0, 1, 1.0),
    "-Y": (0, -1.0, 1, -1.0),
    "+X": (1, -1.0, 0, 1.0),
    "-X": (1, 1.0, 0, -1.0),
}


def _scene_offset_to_latlon(
    scene_xyz: np.ndarray, anchor: AnchorPoint
) -> Tuple[float, float]:
    """Convert a scene-space point to (lat, lon) via the anchor point.

    Raises:
        AmbiguousNorthAxisError: if `anchor.north_axis` isn't one of the
            four axis-aligned values this function can confidently handle.
    """
    mapping = _AXIS_MAPPING.get(anchor.north_axis)
    if mapping is None:
        raise AmbiguousNorthAxisError(
            f"AnchorPoint.north_axis={anchor.north_axis!r} is not one of "
            f"{sorted(_AXIS_MAPPING)}; cannot confidently convert scene "
            "coordinates to real-world orientation without guessing."
        )
    east_idx, east_sign, north_idx, north_sign = mapping

    offset = np.asarray(scene_xyz) - np.asarray(anchor.scene_local_position)
    east_m = east_sign * offset[east_idx] * anchor.scene_to_real_scale_factor
    north_m = north_sign * offset[north_idx] * anchor.scene_to_real_scale_factor

    delta_lat = north_m / _METERS_PER_DEGREE_LAT
    delta_lon = east_m / (
        _METERS_PER_DEGREE_LAT * math.cos(math.radians(anchor.real_world_lat))
    )
    return anchor.real_world_lat + delta_lat, anchor.real_world_lon + delta_lon


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
