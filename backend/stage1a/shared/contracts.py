"""Stage 1A's view of the shared data contract.

Re-exports, byte-identical, from the single canonical source at
`backend/shared/contracts.py` — not a second definition of the same
models. (An earlier version of this file *did* redefine them; fixed
during the Stage 1A/1B merge, since two independently-maintained copies
of the same contract is exactly the drift risk the build docs for both
stages warn against.)

Stage 1A and Stage 1B each have their own, different `sys.path`
convention (this stage's own README documents running via
`cd backend && python -m uvicorn stage1a.routes:app`, which puts
`backend/` — not the repo root — on `sys.path`; Stage 1B's is the
reverse, repo-root-on-path), so a plain `from backend.shared.contracts
import ...` doesn't resolve under Stage 1A's own documented invocation.
Fixed here by ensuring the repo root is on `sys.path` before importing
normally — NOT by loading the file a second time under a synthetic
module name (`importlib.util.spec_from_file_location` with a made-up
name), which was tried first and rejected: it produces a second,
distinct class object for e.g. `RegionalEnsembleForecast` that is
structurally identical but NOT the same class as the one
`backend.shared.contracts` (and anything importing it normally, like
Stage 1B) actually uses — `is` comparisons and pydantic's per-class
schema caching would silently see two different types. The `sys.path`
approach here goes through Python's normal module cache
(`sys.modules["backend.shared.contracts"]`), so every importer — however
it got there — ends up with the exact same class objects. Verified: `from
backend.stage1a.shared.contracts import RegionalEnsembleForecast` and
`from backend.shared.contracts import RegionalEnsembleForecast` return
`is`-identical classes.
"""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parents[3])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from backend.shared.contracts import (  # noqa: E402
    BoundingBox,
    EnsembleMember,
    RegionalEnsembleForecast,
    RiverStageForecast,
    StageTimestepValue,
    TimestepValue,
)

__all__ = [
    "BoundingBox",
    "TimestepValue",
    "EnsembleMember",
    "RegionalEnsembleForecast",
    "StageTimestepValue",
    "RiverStageForecast",
]
