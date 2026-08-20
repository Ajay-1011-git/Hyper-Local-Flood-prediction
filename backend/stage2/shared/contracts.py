"""Stage 2's data contracts: §B.2's new types, plus what's consumed/produced.

CONSUMED FROM STAGE 1B — imported, not redefined
--------------------------------------------------
`DownscaledForecastField` and `SensorReading`, re-exported byte-identical
from the single canonical `backend/shared/contracts.py`, using the same
sys.path approach Stage 1A's `shared/contracts.py` established during the
Stage 1A/1B merge (see that file's docstring for the full reasoning: a
second load under a synthetic module name would produce a second, distinct
class object for the same model — `is` comparisons and pydantic's
per-class schema caching would then silently see two different types).

NEW FOR THIS PIVOT — §B.2, copied from the doc
-------------------------------------------------
`AnchorPoint`, `BuildingFootprint`, `TerrainGrid`, `ComputationalMeshNode`.

NodeState / SimulationResult — AUTHORED HERE, NOT A VERBATIM IMPORT
-----------------------------------------------------------------------
The build doc (`stage2_build_instructions_glb (1).md`, T2.0) says to
import these "from wherever they're currently defined... specified in an
earlier combined Stage 2/3/4 document." **That document does not exist
anywhere in this repository** — searched exhaustively (2026-08-20) across
every `.md` file and every stage's code. Stage 3's build doc confirms
Stage 2 is the actual owner ("Import `SimulationResult`, `NodeState` from
Stage 2 verbatim"), so they are defined here, for the first time, assembled
from every confirmed field-level usage found across the Stage 2/3/4 docs
rather than guessed from nothing:

- `NodeState.depth_mean_m` — confirmed verbatim, `stage4_build_instructions.md`
  T4B.5 ("Vertex heights driven directly from the scene store's current
  `NodeState.depth_mean_m` per timestep").
- Per-node peak depth/velocity/rate-of-rise, and `ensemble_agreement_fraction`
  at a given timestep — confirmed by `stage3_build_instructions.md` T3.1
  (`extract_peak_hazard`) and T3.5 (confidence "from the corresponding
  `ensemble_agreement_fraction`").
- Aggregated-only, no raw per-member arrays — confirmed by this doc's own
  T2.7 ("Do not persist or return raw per-member arrays — only the
  aggregated `NodeState` fields") and TRD §6.2 ("computes ensemble
  statistics (mean, min/max envelope, agreement fraction)").
- `SimulationResult.validation_error_m` — confirmed verbatim, T2.6's VERIFY
  step ("this becomes `SimulationResult.validation_error_m`").
- `TRD §5.3`'s `SimulationNode` (`node_id, site_id, lat, lon, elevation,
  is_wall_node, states: [{t, depth_m, velocity_mps, rate_of_rise}]`) is the
  closest existing precedent, but is explicitly the PRE-aggregation,
  per-member shape (TRD §6.2 says raw per-member data is never sent to the
  client) — `NodeState` here is its aggregated counterpart, not a copy of it.

Everything else on these two models (field names beyond what's cited above,
`source_forecast_id` tracing convention, `site_id`/`generated_at` on
`SimulationResult`) is a reasonable, explicitly-labelled inference by this
session, mirroring the same traceability convention Stage 1B's
`DownscaledForecastField.source_forecast_id` already uses for
`RegionalEnsembleForecast`. If this is wrong, it needs to be corrected
before Stage 3/4 build against it — flag this to the human rather than
treating it as settled.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

_repo_root = str(Path(__file__).resolve().parents[3])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from backend.shared.contracts import (  # noqa: E402
    DownscaledForecastField,
    SensorReading,
)


# ---------------------------------------------------------------------------
# §B.2 — new for this GLB-based pivot
# ---------------------------------------------------------------------------


class AnchorPoint(BaseModel):
    scene_object_name: str
    scene_local_position: List[float]  # [x, y, z] in Blender scene units
    real_world_lat: float
    real_world_lon: float
    real_world_elevation_m: Optional[float]
    scene_to_real_scale_factor: float
    north_axis: str  # e.g. "+Y", confirmed from Blender task output


class BuildingFootprint(BaseModel):
    building_id: str  # "Building_01" etc.
    footprint_polygon: List[List[float]]  # [[x, y], ...] real-world meters, site-local frame
    height_m: Optional[float]


class TerrainGrid(BaseModel):
    site_id: str
    resolution_m: float
    origin_lat: float
    origin_lon: float
    elevation_grid: List[List[float]]  # 2D array, meters
    interpolated_from_regional_dem: bool  # honesty flag — see CLAUDE.md rule 1


class ComputationalMeshNode(BaseModel):
    node_id: str
    x_m: float
    y_m: float
    elevation_m: float
    is_wall_node: bool
    building_id: Optional[str]  # set if is_wall_node is True


# ---------------------------------------------------------------------------
# NodeState / SimulationResult — authored here; see module docstring
# ---------------------------------------------------------------------------


class NodeHazardTimestep(BaseModel):
    """One node's ensemble-aggregated hydraulic state at one forecast hour.

    Field names/units confirmed: `depth_mean_m` (stage4 T4B.5).
    min/max envelope and velocity/rate-of-rise follow TRD §6.2's stated
    aggregation ("mean, min/max envelope, agreement fraction") applied
    uniformly across the three hydraulic quantities this project tracks
    (TRD §5.3's `SimulationNode.states`: depth, velocity, rate_of_rise).
    """

    hour: int
    depth_mean_m: float
    depth_min_m: float
    depth_max_m: float
    velocity_mean_mps: float
    velocity_min_mps: float
    velocity_max_mps: float
    rate_of_rise_mean_m_per_hr: float
    ensemble_agreement_fraction: float  # fraction of members exceeding a hazard threshold at this timestep


class NodeState(BaseModel):
    """A computational mesh node's full aggregated trajectory."""

    node_id: str  # matches ComputationalMeshNode.node_id
    is_wall_node: bool
    building_id: Optional[str]
    states: List[NodeHazardTimestep]


class SimulationResult(BaseModel):
    """Stage 2's output: what Stage 3 (damage ranking) and Stage 4 (viz) consume."""

    simulation_id: str
    site_id: str
    source_forecast_id: str  # traces back to DownscaledForecastField.source_forecast_id
    generated_at: datetime
    nodes: List[NodeState]
    #: mean absolute error against the numerical solver on held-out
    #: scenarios (T2.6's VERIFY, confirmed field name).
    validation_error_m: Optional[float] = None


__all__ = [
    "DownscaledForecastField",
    "SensorReading",
    "AnchorPoint",
    "BuildingFootprint",
    "TerrainGrid",
    "ComputationalMeshNode",
    "NodeHazardTimestep",
    "NodeState",
    "SimulationResult",
]
