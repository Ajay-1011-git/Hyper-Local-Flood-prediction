"""Stage 1B data contracts.

Per T1B.0: `RegionalEnsembleForecast` (Stage 1A's output, which this stage
consumes) is imported byte-identical from the single shared location at
`backend/shared/contracts.py` rather than redefined here, since Stage 1A's
module already exists in this repo (`backend/stage1a/`, built independently
on its own branch). `DownscaledForecastField` and `SensorReading` are
Stage 1B's own outputs, defined there too so both stages have exactly one
place to import from.

This module re-exports everything Stage 1B code needs so internal imports
can consistently say `from stage1b.shared.contracts import ...`.
"""

from backend.shared.contracts import (
    BoundingBox,
    RegionalEnsembleForecast,
    DownscaledTimestepValue,
    DownscaledEnsembleMember,
    DownscaledForecastField,
    SensorReading,
)

__all__ = [
    "BoundingBox",
    "RegionalEnsembleForecast",
    "DownscaledTimestepValue",
    "DownscaledEnsembleMember",
    "DownscaledForecastField",
    "SensorReading",
]
