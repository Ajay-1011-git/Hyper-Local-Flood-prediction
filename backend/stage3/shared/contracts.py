"""Stage 3's view of the shared data contracts.

Re-exports, byte-identical, from the single canonical source at
`backend/shared/contracts.py` — never redefine these. See that file's own
module docstring for the full rationale (this project already caught and
fixed a real duplicate-contracts bug once, during the Stage 1A/1B merge).

Uses the same `sys.path`-insertion approach as `backend/stage1a/shared/
contracts.py` rather than a plain `from backend.shared.contracts import
...`: this project's two existing stages use two different invocation
conventions (Stage 1A: `cd backend && python -m uvicorn stage1a.
routes:app`; Stage 1B: repo-root-on-path), and this stage's own eventual
run convention isn't fixed yet — inserting the repo root onto `sys.path`
before importing normally works under either, and (importantly, verified
during the Stage 1A fix) goes through Python's real module cache, so
classes stay `is`-identical with every other importer rather than being
silently duplicated.

IMPORTANT — see backend/stage3/CLAUDE.md's "STOP" section: `NodeState`
and `SimulationResult` re-exported here are a RECONSTRUCTED, UNCONFIRMED
draft (no authoritative spec for them exists anywhere in this project's
docs as of 2026-08-20) — check `backend/shared/contracts.py`'s own
per-field comments before depending on any field marked UNCONFIRMED
there.
"""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parents[3])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from backend.shared.contracts import (  # noqa: E402
    AnchorPoint,
    BuildingFootprint,
    DamageRankEntry,
    DownscaledForecastField,
    NodeState,
    RoadSegment,
    SensorReading,
    SimulationResult,
    TerrainGrid,
)

__all__ = [
    "AnchorPoint",
    "BuildingFootprint",
    "DamageRankEntry",
    "DownscaledForecastField",
    "NodeState",
    "RoadSegment",
    "SensorReading",
    "SimulationResult",
    "TerrainGrid",
]
