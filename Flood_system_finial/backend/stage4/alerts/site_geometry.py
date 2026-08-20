"""Real site boundary polygon — T4A.3 support.

`generate_cap_xml`'s `site_polygon` parameter needs a real
`[[lat, lon], ...]` boundary. Mirrors Stage 3's own
`demo_site/real_geometry.py` pattern exactly (same reasoning: a direct
cross-import of Stage 2's real functions, not an HTTP call, since Stage 2
exposes no endpoint for this and Stage 4 is legitimately downstream of
Stage 2, same as Stage 3) — derives the real site's overall bounding
polygon from the real GLB (buildings + Road_Network) via Stage 2's own
already-real `compute_site_bbox_latlon`, rather than re-deriving or
guessing site boundary logic a third time in this project.

Falls back to a small, explicitly-labeled placeholder polygon if the real
GLB isn't present locally (e.g. a fresh clone without the gitignored
`blender_prep/output/` data) — never silently substitutes fabricated
"real-looking" coordinates.
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _REPO_ROOT / "backend"
_GLB_PATH = _BACKEND_ROOT / "stage2" / "blender_prep" / "output" / "vit_vellore_site.glb"
_ANCHOR_PATH = _BACKEND_ROOT / "stage2" / "blender_prep" / "output" / "anchor_point.json"

if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def _placeholder_polygon() -> List[List[float]]:
    """Illustrative, NOT surveyed -- see module docstring."""
    return [[12.9685, 79.1555], [12.9700, 79.1555], [12.9700, 79.1565], [12.9685, 79.1565]]


@lru_cache(maxsize=1)
def load_real_site_polygon() -> Tuple[List[List[float]], str]:
    """Returns `(polygon, source)` where `source` is `"real_glb"` or
    `"placeholder_fallback"`. Cached for the process's lifetime (parsing
    the real 11MB GLB on every request would be wasteful)."""
    if not _GLB_PATH.is_file() or not _ANCHOR_PATH.is_file():
        logger.warning(
            "Real GLB/anchor data not found at %s / %s -- using placeholder site polygon.",
            _GLB_PATH,
            _ANCHOR_PATH,
        )
        return _placeholder_polygon(), "placeholder_fallback"

    try:
        from stage2.ingestion.glb_loader import load_site_model  # type: ignore[import-not-found]
        from stage2.terrain.dem_interpolation import (  # type: ignore[import-not-found]
            compute_site_bbox_latlon,
        )

        objects, site_transform = load_site_model(_GLB_PATH, _ANCHOR_PATH)
        min_lat, max_lat, min_lon, max_lon = compute_site_bbox_latlon(objects, site_transform)
        # A closed 4-corner ring around the real bbox -- (lat, lon) order,
        # matching the confirmed real SACHET/CAP convention.
        polygon = [
            [min_lat, min_lon],
            [max_lat, min_lon],
            [max_lat, max_lon],
            [min_lat, max_lon],
            [min_lat, min_lon],
        ]
        return polygon, "real_glb"
    except Exception as exc:
        logger.error(
            "Failed to derive real site polygon from %s: %s -- falling back to placeholder.",
            _GLB_PATH,
            exc,
        )
        return _placeholder_polygon(), "placeholder_fallback"
