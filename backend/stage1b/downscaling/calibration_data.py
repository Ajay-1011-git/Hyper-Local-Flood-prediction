"""Build real matched calibration samples — 2026-08-20 addition.

WHY THIS EXISTS (a real, permanently-dead code path, found by audit)
---------------------------------------------------------------------
`downscaling/calibration.py`'s `fit_calibration` (T1B.6) was fully built
and tested, but **nothing in production ever called it** — confirmed by
grep: only tests referenced it. `routes.py` hardcoded
`IDENTITY_COEFFICIENTS` instead, with a comment explaining that real
matched (TN WRD reading, coarse regional estimate) pairs "isn't possible
yet without Stage 1A's historical archive."

That reasoning was correct when written, but it left the path *dead
forever*: Stage 1A now really does persist every forecast it serves
(`regional_ensemble_forecast`, confirmed: real rows accumulating since
2026-08-19), so the archive this depends on is now genuinely filling up
— yet no code would ever have started using it. This module builds the
matched samples, so `routes.py` can attempt a REAL fit and fall back to
identity honestly (and loudly) when the data still isn't sufficient,
instead of never trying at all.

WHY IT READS STAGE 1A'S TABLE DIRECTLY
----------------------------------------
Stage 1A exposes only `/api/forecast/regional` (the CURRENT forecast) and
`/api/forecast/river-stage` — there is no endpoint for its historical
archive (confirmed by reading `stage1a/routes.py`'s actual route list).
A direct read of its table is therefore the only route to this data, and
it matches the precedent already established in this project: Stage 2
reads Stage 1B's own `dem_metadata` table directly, for exactly the same
reason (no HTTP API exists for it). This module only ever READS; it never
writes to or migrates Stage 1A's table.

WHAT "MATCHED" MEANS HERE, PRECISELY
--------------------------------------
An archived `RegionalEnsembleForecast` generated at time G carries, per
member, a rainfall value for each lead hour h — i.e. a coarse prediction
valid at `G + h hours`. A TN WRD station reading has an observed rainfall
at its own timestamp T. A matched sample pairs the ensemble-MEAN coarse
value valid at time V with the station's real observed value at the same
time, within `MATCH_TOLERANCE`. The ensemble mean is used (not a single
member) because the coefficients being fitted correct the field as a
whole, not one member's noise.

SINGLE-STATION LIMITATION, INHERITED AND HANDLED (not hidden)
---------------------------------------------------------------
With one nearby station, every matched sample shares one identical
elevation/slope/aspect triple, so the terrain regressors have zero
variance and are mathematically unidentifiable — only the intercept
(a real bias correction) can be fitted. `fit_calibration` already
detects exactly this and reports it via
`unidentifiable_terrain_parameters` rather than returning a fabricated
terrain coefficient (this was a real bug caught and fixed earlier in
this module's history). Nothing here works around that; the honest,
partial result is the correct output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import text

from backend.stage1b.db import get_db_session

logger = logging.getLogger(__name__)

#: How close an archived forecast's valid time and a real station reading's
#: timestamp must be to count as the same observation. The upstream TN WRD
#: data is HOURLY and regional forecasts here are 6-hourly, so half an hour
#: keeps a match unambiguous (no reading can match two different lead
#: hours). Flagged as a reasonable, not independently-tuned, default.
MATCH_TOLERANCE = timedelta(minutes=30)


@dataclass(frozen=True)
class MatchedCalibrationSamples:
    """Real matched samples, in the exact shape `fit_calibration` expects.

    `n_archived_forecasts` / `n_station_readings` are carried alongside so
    a caller can log *why* a fit was skipped (no archive at all vs. an
    archive that simply doesn't overlap the station's readings in time) —
    the two are very different situations and shouldn't look identical in
    a log line.
    """

    observed_mm: list[float]
    coarse_mm: list[float]
    elevation_m: list[float]
    slope_deg: list[float]
    aspect_deg: list[float]
    n_archived_forecasts: int
    n_station_readings: int

    def __len__(self) -> int:
        return len(self.observed_mm)


def _ensemble_mean_by_valid_time(
    members: Sequence[dict[str, Any]], generated_at: datetime
) -> dict[datetime, float]:
    """Ensemble-mean rainfall per real valid time for one archived forecast.

    `members` is the JSONB shape Stage 1A persists: a list of
    `{"member_id": int, "trajectory": [{"hour": int, "rainfall_mm": float}]}`
    (confirmed against `stage1a/db.py`'s real column definition and the
    shared `RegionalEnsembleForecast` contract).
    """
    totals: dict[datetime, list[float]] = {}
    for member in members:
        for step in member.get("trajectory", []):
            try:
                hour = int(step["hour"])
                value = float(step["rainfall_mm"])
            except (KeyError, TypeError, ValueError):
                # A malformed archived row is real data corruption, not
                # something to silently average in as zero.
                continue
            totals.setdefault(generated_at + timedelta(hours=hour), []).append(value)
    return {valid: sum(vals) / len(vals) for valid, vals in totals.items() if vals}


async def build_matched_samples(
    telemetry: pd.DataFrame,
    station_id: str,
    elevation_m: float,
    slope_deg: float,
    aspect_deg: float,
) -> MatchedCalibrationSamples:
    """Pair real archived coarse estimates with this station's real readings.

    Reads Stage 1A's `regional_ensemble_forecast` archive (see module
    docstring for why directly). Returns however many real matched samples
    exist — possibly zero. Never fabricates a sample to reach
    `MIN_CALIBRATION_SAMPLES`.
    """
    station_rows = telemetry[telemetry["station_id"] == station_id]
    readings = (
        station_rows[["timestamp", "rainfall_mm"]]
        .dropna()
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    async with get_db_session() as session:
        result = await session.execute(
            text(
                "SELECT generated_at, members FROM regional_ensemble_forecast "
                "ORDER BY generated_at"
            )
        )
        archived = result.fetchall()

    if not archived or readings.empty:
        return MatchedCalibrationSamples(
            [], [], [], [], [], len(archived), len(readings)
        )

    # Index the real readings by timestamp once, so matching is a lookup
    # per valid-time rather than a scan per (forecast x lead hour).
    reading_times = pd.to_datetime(readings["timestamp"])

    observed: list[float] = []
    coarse: list[float] = []
    for generated_at, members in archived:
        for valid_time, coarse_mm in _ensemble_mean_by_valid_time(
            members or [], generated_at
        ).items():
            target = pd.Timestamp(valid_time)
            if target.tzinfo is not None and reading_times.dt.tz is None:
                # Archived timestamps are tz-aware (Postgres timestamptz);
                # the TN WRD CSVs carry naive local timestamps. Compare in
                # the same frame rather than letting pandas raise -- the
                # portal's own times are IST, matching this deployment's
                # DB timezone, confirmed against real rows.
                target = target.tz_localize(None)
            deltas = (reading_times - target).abs()
            # `readings` was `reset_index(drop=True)`'d above, so its index
            # is a real positional RangeIndex -- idxmin's declared
            # `int | str` return narrows to int here by construction.
            nearest_idx = int(np.asarray(deltas).argmin())
            if deltas.iloc[nearest_idx] <= MATCH_TOLERANCE:
                observed.append(float(readings["rainfall_mm"].iloc[nearest_idx]))
                coarse.append(float(coarse_mm))

    n = len(observed)
    return MatchedCalibrationSamples(
        observed_mm=observed,
        coarse_mm=coarse,
        elevation_m=[elevation_m] * n,
        slope_deg=[slope_deg] * n,
        aspect_deg=[aspect_deg] * n,
        n_archived_forecasts=len(archived),
        n_station_readings=len(readings),
    )
