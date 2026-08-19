"""GEFS forecast client — IMPLEMENTATION SEAM, not yet built.

See `gefs/__init__.py` for why this exists as an explicit stub rather than
being omitted from the fallback chain.

ANTI-HALLUCINATION NOTE: no GEFS API shape is assumed or written here. When
this is implemented for real, the same rule that governed T1A.2/T1A.6
applies — confirm NOAA's actual GEFS access method (NOMADS, AWS Open Data,
or another route) against its real documentation in-session before writing
any request code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from stage1a.config import Stage1ASettings
from stage1a.gefs.errors import GEFSUnavailableError
from stage1a.gencast.provenance import RegionalForecastResult
from stage1a.shared.contracts import BoundingBox


def fetch_gefs_forecast(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
) -> RegionalForecastResult:
    """Always raises. GEFS integration has not been built.

    Present so `get_regional_forecast`'s fallback chain has the shape the
    human specified (GEFS first, WN2 Mini second), without pretending GEFS
    support exists.
    """
    raise GEFSUnavailableError(
        "GEFS integration is not implemented in this deployment. Falling "
        "through to WeatherNext 2 Mini."
    )
