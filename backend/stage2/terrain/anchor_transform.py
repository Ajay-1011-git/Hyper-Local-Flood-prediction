"""Scene-local -> real-world coordinate conversion via `AnchorPoint`.

Shared by `dem_interpolation.py` (needs lat/lon) and `footprint_extraction.py`
(needs real-world meters, site-local frame) — factored out so the one
non-trivial, EXPLICITLY UNCONFIRMED assumption in this conversion (see
below) lives in exactly one place, not duplicated and risking a fix landing
in only one of the two callers later.

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
from typing import Dict, Tuple

import numpy as np

from stage2.shared.contracts import AnchorPoint
from stage2.terrain.errors import AmbiguousNorthAxisError

METERS_PER_DEGREE_LAT = 111_320.0

# (north_axis) -> (east_scene_axis_index, east_sign, north_scene_axis_index, north_sign)
# Ground plane is scene (x=0, y=1); z (index 2) is up and unused here.
_AXIS_MAPPING: Dict[str, Tuple[int, float, int, float]] = {
    "+Y": (0, 1.0, 1, 1.0),
    "-Y": (0, -1.0, 1, -1.0),
    "+X": (1, -1.0, 0, 1.0),
    "-X": (1, 1.0, 0, -1.0),
}


def scene_offset_to_east_north_m(
    scene_xyz: np.ndarray, anchor: AnchorPoint
) -> Tuple[float, float]:
    """Convert a scene-space point to (east_m, north_m) offset from the anchor.

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
    return float(east_m), float(north_m)


def latlon_to_east_north_m(
    lat: float, lon: float, anchor: AnchorPoint
) -> Tuple[float, float]:
    """Inverse of the geographic half of `scene_offset_to_latlon`.

    Converts a plain (lat, lon) — e.g. a `TerrainGrid` cell's position —
    into (east_m, north_m) offset from the anchor, the same frame
    `footprint_extraction.py`'s `BuildingFootprint.footprint_polygon`
    already uses. Needed so T2.4 can test terrain cells against building
    footprints in one consistent coordinate frame (`TerrainGrid` is
    natively in lat/lon; footprints are natively in anchor-relative
    meters) — this function is the reconciliation between them.
    """
    delta_lat = lat - anchor.real_world_lat
    delta_lon = lon - anchor.real_world_lon
    north_m = delta_lat * METERS_PER_DEGREE_LAT
    east_m = delta_lon * METERS_PER_DEGREE_LAT * math.cos(
        math.radians(anchor.real_world_lat)
    )
    return east_m, north_m


def scene_offset_to_latlon(
    scene_xyz: np.ndarray, anchor: AnchorPoint
) -> Tuple[float, float]:
    """Convert a scene-space point to (lat, lon) via the anchor point."""
    east_m, north_m = scene_offset_to_east_north_m(scene_xyz, anchor)
    delta_lat = north_m / METERS_PER_DEGREE_LAT
    delta_lon = east_m / (
        METERS_PER_DEGREE_LAT * math.cos(math.radians(anchor.real_world_lat))
    )
    return anchor.real_world_lat + delta_lat, anchor.real_world_lon + delta_lon
