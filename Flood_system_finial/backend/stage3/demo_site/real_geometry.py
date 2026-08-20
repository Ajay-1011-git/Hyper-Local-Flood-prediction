"""Real demo-site geometry (2026-08-20 addition, found during a full-
system wiring audit).

WHY THIS EXISTS
----------------
`routes.py`'s `_demo_site_geometry()` (T3.6) previously returned a
hand-authored PLACEHOLDER: 3 fake rectangular buildings
(Building_01/02/03) and 1 fake road segment, none matching Stage 2's real
site at all. That was a real, flagged gap (Stage 2 has no endpoint
serving footprint/road geometry) — but by the time this module was
written, the real GLB (`vit_vellore_site.glb`) and its anchor data were
already present locally (uploaded by the project owner), and Stage 2's
own real extraction functions (T2.1/T2.3, and the new road_segmentation.py
from this same audit) already produce real geometry from them. So rather
than keep the placeholder, this module calls those functions directly.

WHY A DIRECT CROSS-IMPORT (not an HTTP call) IS THE RIGHT SHAPE HERE
--------------------------------------------------------------------------
This mirrors an already-established pattern in this project — Stage 2
reads Stage 1B's `dem_metadata` table directly (a DB read, not an HTTP
call), because there's no live endpoint for that data either, and
Stage 2 is legitimately downstream of Stage 1B. The same reasoning
applies here: Stage 3 is downstream of Stage 2 (never the reverse, per
this project's stage-ordering rule), and geometry extraction is Stage
2's own real, tested logic — reusing it directly avoids re-deriving (and
risking silently diverging from) that logic a second time in Stage 3.
Unlike editing Stage 2's own files, importing its already-published
functions from a downstream stage needs no special authorization.

CLASS IDENTITY, CONFIRMED SAFE
--------------------------------
`stage2.shared.contracts.BuildingFootprint`/`RoadSegment` are themselves
re-exports of the SAME canonical `backend/shared/contracts.py` classes
Stage 3 already uses (both modules reach it via the same `sys.path`-
insertion-to-repo-root mechanism, through Python's real module cache) —
so the `BuildingFootprint`/`RoadSegment` instances this module returns
are genuinely `is`-identical to Stage 3's own, not a second incompatible
copy. Confirmed directly, not assumed (see this module's own real VERIFY
in the commit that introduced it).

FALLBACK, EXPLICITLY LABELED
------------------------------
If the real GLB/anchor files aren't present locally (e.g. a fresh clone
without the gitignored `blender_prep/output/` data, or Stage 2's own code
raising for some other real reason), this falls back to a small,
explicitly-labeled placeholder — never silently substitutes fabricated
"real-looking" data. `X-Geometry-Source` (set by `routes.py`) surfaces
which path was used, mirroring `X-Simulation-Source`'s pattern.

CACHING
--------
GLB parsing + geometry extraction is real work (loading an 11MB mesh,
point-in-polygon/grid-binning over thousands of vertices) — wasteful to
redo on every request for data that doesn't change within a running
process. Cached via `functools.lru_cache` (process-lifetime, single
demo site) rather than per-request recomputation.
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

from backend.stage3.shared.contracts import BuildingFootprint, RoadSegment

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _REPO_ROOT / "backend"
_GLB_PATH = _BACKEND_ROOT / "stage2" / "blender_prep" / "output" / "vit_vellore_site.glb"
_ANCHOR_PATH = _BACKEND_ROOT / "stage2" / "blender_prep" / "output" / "anchor_point.json"

if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def placeholder_demo_site_geometry() -> Tuple[List[BuildingFootprint], List[RoadSegment]]:
    """Small, explicitly-labeled fallback -- matches Stage 2's REAL
    building ids (Building_01/02, Building_03 no longer exists per
    Stage 2's own confirmed 2026-08-20 ground truth) even in the
    fallback case, so a downstream consumer doesn't see a set of ids
    that could never appear once real data is available. Coordinates
    are illustrative, not surveyed."""
    footprints = [
        BuildingFootprint(
            building_id="Building_01",
            footprint_polygon=[[0, 0], [10, 0], [10, 10], [0, 10]],
        ),
        BuildingFootprint(
            building_id="Building_02",
            footprint_polygon=[[20, 0], [35, 0], [35, 12], [20, 12]],
        ),
    ]
    road_segments = [
        RoadSegment(
            segment_id="Road_Segment_000",
            polyline=[[0, 20], [40, 20]],
            width_m=7.0,
        ),
    ]
    return footprints, road_segments


@lru_cache(maxsize=1)
def load_real_demo_site_geometry() -> Tuple[Tuple[List[BuildingFootprint], List[RoadSegment]], str]:
    """Returns `((footprints, road_segments), source)` where `source` is
    `"real_glb"` or `"placeholder_fallback"`. Cached for the process's
    lifetime (see module docstring)."""
    if not _GLB_PATH.is_file() or not _ANCHOR_PATH.is_file():
        logger.warning(
            "Real GLB/anchor data not found at %s / %s -- using placeholder geometry.",
            _GLB_PATH,
            _ANCHOR_PATH,
        )
        return placeholder_demo_site_geometry(), "placeholder_fallback"

    try:
        # mypy checks backend/stage3/ in isolation and has no visibility
        # into backend/stage2/'s types from that invocation -- these
        # imports are real and resolve fine at runtime (both stages
        # share the same repo, backend/ is on sys.path per this module's
        # own setup above), confirmed by this module's own real VERIFY.
        from stage2.ingestion.glb_loader import load_site_model  # type: ignore[import-not-found]
        from stage2.terrain.footprint_extraction import (  # type: ignore[import-not-found]
            extract_building_footprints,
        )
        from stage2.terrain.road_segmentation import (  # type: ignore[import-not-found]
            extract_road_segments,
        )

        objects, site_transform = load_site_model(_GLB_PATH, _ANCHOR_PATH)
        buildings = {name: mesh for name, mesh in objects.items() if name.startswith("Building_")}
        footprints = extract_building_footprints(buildings, site_transform)
        road_segments = extract_road_segments(objects["Road_Network"], site_transform)
        return (footprints, road_segments), "real_glb"
    except Exception as exc:
        logger.error(
            "Failed to load real demo-site geometry from %s: %s -- falling back to placeholder.",
            _GLB_PATH,
            exc,
        )
        return placeholder_demo_site_geometry(), "placeholder_fallback"
