"""Provenance of a regional forecast (T1A.4).

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

    Ordered as `get_regional_forecast`'s chain tries them (amendment,
    2026-08-19): GEFS first (not yet implemented), then WeatherNext 2 Mini,
    then the legacy GenCast live-inference/synthetic-fallback path kept as
    the last resort.
    """

    GEFS = "gefs"
    WN2_MINI = "wn2_mini_precomputed"
    LIVE = "live_inference"  # legacy GenCast path
    FALLBACK = "precomputed_fallback"  # legacy GenCast synthetic fallback


class ForecastProvenance(BaseModel):
    """Where a `RegionalEnsembleForecast` actually came from."""

    path: ForecastPath
    retrieved_at: datetime
    source_file: Optional[str] = None
    #: True when the underlying dataset is stamped `synthetic` — a
    #: development fixture, not a real GenCast forecast. Surfaced so a
    #: placeholder can never be mistaken for model output downstream.
    synthetic: bool = False
    #: Why the fallback was taken, when it was.
    fallback_reason: Optional[str] = None


class RegionalForecastResult(BaseModel):
    """A forecast together with its provenance."""

    forecast: "RegionalEnsembleForecast"
    provenance: ForecastProvenance


from stage1a.shared.contracts import RegionalEnsembleForecast  # noqa: E402

RegionalForecastResult.model_rebuild()
