"""Stage 2's data contracts: cross-stage types imported, Stage-2-internal types defined here.

RECONCILED WITH STAGE 3, 2026-08-20
----------------------------------------
`NodeState`/`SimulationResult` were originally authored independently in
this file (no canonical spec existed for either — see git history for
that version's reasoning). Stage 3 (built on a separate branch by a
teammate, also finding no canonical spec) independently authored its OWN
version and added it to the single canonical `backend/shared/
contracts.py`, already built into working Stage 3 code. The two drafts
disagreed on structure (this file's version nested a timestep list inside
each `NodeState`; Stage 3's is flat — one `NodeState` per (node, hour),
matching the real WebSocket payload cited in `stage4_build_instructions.md`
more directly: `{"node_states": [...], "envelope": {...}}`).

Resolved by adopting Stage 3's version wholesale (it's citation-grounded
and already load-bearing for finished code) rather than keeping this
file's now-superseded draft. `AnchorPoint`/`BuildingFootprint`/
`TerrainGrid` are also re-exported from the same canonical source now,
for the same reason `DownscaledForecastField`/`SensorReading` already
were — see the `sys.path` mechanics note below, copied from that
original reasoning (still accurate, unchanged).

SYS.PATH MECHANICS (unchanged from the original version of this file)
---------------------------------------------------------------------------
Re-exported byte-identical from the single canonical
`backend/shared/contracts.py`, using the same sys.path approach Stage 1A's
`shared/contracts.py` established during the Stage 1A/1B merge: a second
load under a synthetic module name would produce a second, distinct class
object for the same model — `is` comparisons and pydantic's per-class
schema caching would then silently see two different types. Going through
Python's real module cache instead keeps every importer's classes
`is`-identical.

STAGE-2-INTERNAL, NOT RE-EXPORTED FROM THE CANONICAL FILE
---------------------------------------------------------------
`ComputationalMeshNode` and `MeshEdge`: no downstream stage doc lists
either as a cross-stage import (confirmed by the same teammate's note in
the canonical file) — they're `mesh/computational_mesh.py`'s own working
representation, feeding the solver/GNN, never passed to Stage 3/4.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

_repo_root = str(Path(__file__).resolve().parents[3])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from backend.shared.contracts import (  # noqa: E402
    AnchorPoint,
    BuildingFootprint,
    DownscaledForecastField,
    NodeState,
    SensorReading,
    SimulationResult,
    TerrainGrid,
)


# ---------------------------------------------------------------------------
# Stage-2-internal only (see module docstring for why these aren't in the
# canonical cross-stage file)
# ---------------------------------------------------------------------------


class ComputationalMeshNode(BaseModel):
    node_id: str
    x_m: float
    y_m: float
    elevation_m: float
    is_wall_node: bool
    building_id: Optional[str]  # set if is_wall_node is True


class MeshEdge(BaseModel):
    """One adjacency edge between two `ComputationalMeshNode`s (T2.4).

    AUTHORED HERE, modeled directly on RBTV1/mSWE-GNN's real confirmed
    graph-edge structure (`database/graph_creation.py`'s
    `convert_mesh_to_pyg`, fetched and read this session): the model's
    real `edge_index` connects neighboring mesh CELLS (not triangle
    vertices), and its `edge_attr` carries `face_distance` (distance
    between cell centers) and `edge_slope` (`DEM_diff / face_distance`).
    `distance_m`/`slope` below are named to make that mapping obvious for
    T2.6, not independently invented field names.
    """

    node_id_a: str
    node_id_b: str
    distance_m: float
    slope: float  # (elevation_b - elevation_a) / distance_m


__all__ = [
    "DownscaledForecastField",
    "SensorReading",
    "AnchorPoint",
    "BuildingFootprint",
    "TerrainGrid",
    "ComputationalMeshNode",
    "NodeState",
    "SimulationResult",
    "MeshEdge",
]
