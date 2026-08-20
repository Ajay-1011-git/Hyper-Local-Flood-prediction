"""Stage 4's data contracts: cross-stage types imported, `Alert` (new,
Stage-4-owned) defined here.

Re-exported byte-identical from the single canonical
`backend/shared/contracts.py`, using the same `sys.path`-insertion
approach Stage 1A's `shared/contracts.py` established during the Stage
1A/1B merge (and Stage 2/3 both reuse): a second load under a synthetic
module name would produce a second, distinct class object for the same
model — `is` comparisons and pydantic's per-class schema caching would
then silently see two different types. Going through Python's real
module cache instead keeps every importer's classes `is`-identical.

Per §B.2: "Consumed, unchanged, imported verbatim: SimulationResult,
NodeState, TerrainGrid, BuildingFootprint, AnchorPoint (Stage 2);
DamageRankEntry, RoadSegment (Stage 3); SensorReading (Stage 1B)."
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel

_repo_root = str(Path(__file__).resolve().parents[3])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from backend.shared.contracts import (  # noqa: E402
    AnchorPoint,
    BuildingFootprint,
    DamageRankEntry,
    NodeState,
    RoadSegment,
    SensorReading,
    SimulationResult,
    TerrainGrid,
)


class Alert(BaseModel):
    """New, Stage-4-owned contract (§B.2, verbatim)."""

    id: str
    site_id: str
    generated_at: datetime
    severity: str  # real CAP severity enum value, confirmed in T4A.1
    certainty: float  # from ensemble agreement -- never a placeholder
    urgency: str  # real CAP urgency enum value, confirmed in T4A.1
    area_polygon: List[List[float]]  # [[lat, lon], ...]
    effective_time: datetime
    expiry_time: datetime
    cap_xml: str
    text_by_language: Dict[str, str]  # {"en": "...", "ta": "..."}


class TerrainHeightmap(BaseModel):
    """One rectangular elevation patch, ready to render as a 3D surface (T4B.3).

    Stage-4-internal: this is a RENDERING view of terrain, not a second
    definition of Stage 2's `TerrainGrid` (which stays the canonical
    simulation contract and is untouched, per this stage's rule 7). The
    difference is deliberate — a renderer needs explicit bounds and
    row/col counts to build a mesh, and needs to know where data is
    genuinely missing.

    `elevation_grid` cells are `None` where the real DEM has nodata
    (CartoDEM voids, plus values Stage 1B masked as physically
    implausible). JSON cannot carry NaN, and filling them with a number
    here would make missing data indistinguishable from measured data.
    """

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    rows: int
    cols: int
    resolution_m: float  # real ground spacing of THIS grid, post-decimation
    elevation_grid: List[List[Optional[float]]]  # rows x cols, metres; None = nodata
    min_elevation_m: float  # over finite cells only
    max_elevation_m: float
    nodata_cell_count: int  # surfaced, not hidden -- the renderer reports it


class SiteTerrainResponse(BaseModel):
    """`GET /api/terrain/{site_id}` — the 3D scene's terrain (T4B.3)."""

    site_id: str
    site_lat: float
    site_lon: float
    #: Always True: this surface is derived from Stage 1B's regional DEM,
    #: never a photogrammetry survey. Matches Stage 2's `TerrainGrid` flag
    #: of the same name; T4C.6's About page must state the limitation.
    interpolated_from_regional_dem: bool
    source_raster: str
    regional: TerrainHeightmap  # decimated wide surround (TRD 6, point 3)
    site: TerrainHeightmap  # finer patch, same raster -> seamless by construction


__all__ = [
    "AnchorPoint",
    "BuildingFootprint",
    "DamageRankEntry",
    "NodeState",
    "RoadSegment",
    "SensorReading",
    "SimulationResult",
    "TerrainGrid",
    "Alert",
    "TerrainHeightmap",
    "SiteTerrainResponse",
]
