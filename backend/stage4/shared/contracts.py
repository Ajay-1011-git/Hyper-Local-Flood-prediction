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
from typing import Dict, List

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
]
