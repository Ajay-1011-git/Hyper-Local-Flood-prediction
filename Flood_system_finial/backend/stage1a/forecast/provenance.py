"""Provenance of a regional forecast.

§B.2's `RegionalEnsembleForecast` must stay byte-aligned with Stage 1B's
copy, so "which path produced this?" cannot become a field on it. It lives
here instead, as a Stage-1A-local model returned alongside the contract
object and surfaced on the HTTP response as a header (T1A.8) — additive,
and invisible to any consumer that only knows the shared contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ForecastPath(str, Enum):
    """Which acquisition path produced a forecast.

    Ordered as `get_regional_forecast`'s chain tries them (see
    `fallback.py`): GEFS first (not yet implemented), then WeatherNext 2
    Mini. There is no further fallback — the legacy GenCast live-inference
    path was removed (no TPU/JAX credentials available for it, ever; see
    `fallback.py`'s module docstring).
    """

    GEFS = "gefs"
    WN2_MINI = "wn2_mini_precomputed"


class ForecastProvenance(BaseModel):
    """Where a `RegionalEnsembleForecast` actually came from."""

    path: ForecastPath
    retrieved_at: datetime
    source_file: Optional[str] = None
    #: True when the underlying dataset is a development fixture, not a
    #: real model forecast. Surfaced so a placeholder can never be mistaken
    #: for real output downstream.
    synthetic: bool = False
    #: Why the previous source(s) in the chain were skipped, if any.
    fallback_reason: Optional[str] = None


class RegionalForecastResult(BaseModel):
    """A forecast together with its provenance."""

    forecast: "RegionalEnsembleForecast"
    provenance: ForecastProvenance


from stage1a.shared.contracts import RegionalEnsembleForecast  # noqa: E402

RegionalForecastResult.model_rebuild()
