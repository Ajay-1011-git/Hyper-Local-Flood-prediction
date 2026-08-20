"""Tests for `downscaling/calibration_data.py` (2026-08-20 addition).

Real integration tests against the actual local Postgres (same philosophy
as `test_db.py`/`test_routes.py`: this module genuinely reads Stage 1A's
`regional_ensemble_forecast` table, and that's local infrastructure, not
a third-party network call). The archive rows each test needs are
inserted and cleaned up by the test itself, so these never depend on
whatever the shared dev DB happens to hold.

See the module's own docstring for why this exists at all: `fit_calibration`
was fully built but never called in production, and this is the piece that
makes a real fit reachable.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import text

from backend.stage1b.db import get_db_session
from backend.stage1b.downscaling.calibration_data import (
    _ensemble_mean_by_valid_time,
    build_matched_samples,
)

_TEST_FORECAST_PREFIX = "test-calibdata-"


def _telemetry(station_id: str, times_and_mm: list[tuple[datetime, float]]) -> pd.DataFrame:
    """A real-shaped normalized telemetry frame (same columns
    `tnwrd/client.py` really produces)."""
    return pd.DataFrame(
        [
            {
                "station_id": station_id,
                "station_name": station_id,
                "district": "Vellore",
                "latitude": 12.948611,
                "longitude": 79.138889,
                "timestamp": pd.Timestamp(ts),
                "rainfall_mm": mm,
            }
            for ts, mm in times_and_mm
        ]
    )


async def _insert_archive(forecast_id: str, generated_at: datetime, members: list[dict]) -> None:
    async with get_db_session() as session:
        await session.execute(
            text(
                "INSERT INTO regional_ensemble_forecast "
                "(forecast_id, source, min_lat, max_lat, min_lon, max_lon, "
                " generated_at, resolution_km, members, stored_at) "
                "VALUES (:fid, 'TEST', 12.7, 13.1, 79.0, 79.3, :gen, 27.75, "
                " CAST(:members AS jsonb), :gen) "
                "ON CONFLICT (forecast_id) DO NOTHING"
            ),
            {"fid": forecast_id, "gen": generated_at, "members": json.dumps(members)},
        )
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean_test_archive_rows():
    yield
    async with get_db_session() as session:
        await session.execute(
            text(
                "DELETE FROM regional_ensemble_forecast "
                "WHERE forecast_id LIKE :prefix"
            ),
            {"prefix": f"{_TEST_FORECAST_PREFIX}%"},
        )
        await session.commit()


# ------------------------------------------------- pure ensemble-mean helper


def test_ensemble_mean_averages_across_members_per_valid_time():
    generated_at = datetime(2026, 8, 20, 0, tzinfo=timezone.utc)
    members = [
        {"member_id": 0, "trajectory": [{"hour": 6, "rainfall_mm": 4.0}]},
        {"member_id": 1, "trajectory": [{"hour": 6, "rainfall_mm": 6.0}]},
    ]
    result = _ensemble_mean_by_valid_time(members, generated_at)
    assert result == {generated_at + timedelta(hours=6): 5.0}


def test_ensemble_mean_maps_each_lead_hour_to_its_real_valid_time():
    generated_at = datetime(2026, 8, 20, 0, tzinfo=timezone.utc)
    members = [
        {
            "member_id": 0,
            "trajectory": [
                {"hour": 6, "rainfall_mm": 1.0},
                {"hour": 12, "rainfall_mm": 2.0},
            ],
        }
    ]
    result = _ensemble_mean_by_valid_time(members, generated_at)
    assert result[generated_at + timedelta(hours=6)] == 1.0
    assert result[generated_at + timedelta(hours=12)] == 2.0


def test_ensemble_mean_skips_malformed_steps_rather_than_zero_filling():
    """A corrupt archived row must not be silently averaged in as 0.0 --
    that would quietly bias a real calibration fit downward."""
    generated_at = datetime(2026, 8, 20, 0, tzinfo=timezone.utc)
    members = [
        {"member_id": 0, "trajectory": [{"hour": 6, "rainfall_mm": 4.0}]},
        {"member_id": 1, "trajectory": [{"hour": 6}]},  # missing rainfall_mm
    ]
    result = _ensemble_mean_by_valid_time(members, generated_at)
    assert result == {generated_at + timedelta(hours=6): 4.0}


# ---------------------------------------------------- real matching, real DB


async def test_matches_a_real_reading_to_its_real_forecast_valid_time():
    generated_at = datetime(2026, 8, 20, 0, tzinfo=timezone.utc)
    await _insert_archive(
        f"{_TEST_FORECAST_PREFIX}match",
        generated_at,
        [{"member_id": 0, "trajectory": [{"hour": 6, "rainfall_mm": 8.0}]}],
    )
    # A real reading exactly at the forecast's valid time (06:00 UTC).
    telemetry = _telemetry("Vellore", [(datetime(2026, 8, 20, 6, 0), 3.5)])

    samples = await build_matched_samples(
        telemetry, "Vellore", elevation_m=119.6, slope_deg=0.3, aspect_deg=152.0
    )

    assert len(samples) == 1
    assert samples.observed_mm == [3.5]
    assert samples.coarse_mm == [8.0]
    # Terrain is constant per site -- one identical triple per sample.
    assert samples.elevation_m == [119.6]


async def test_reading_outside_the_tolerance_is_not_matched():
    generated_at = datetime(2026, 8, 20, 0, tzinfo=timezone.utc)
    await _insert_archive(
        f"{_TEST_FORECAST_PREFIX}far",
        generated_at,
        [{"member_id": 0, "trajectory": [{"hour": 6, "rainfall_mm": 8.0}]}],
    )
    # 4 hours away from the 06:00 valid time -- far outside MATCH_TOLERANCE.
    telemetry = _telemetry("Vellore", [(datetime(2026, 8, 20, 10, 0), 3.5)])

    samples = await build_matched_samples(
        telemetry, "Vellore", elevation_m=119.6, slope_deg=0.3, aspect_deg=152.0
    )
    assert len(samples) == 0


async def test_counts_are_reported_even_when_nothing_matches():
    """The real production case as of 2026-08-20: a real archive and real
    readings both exist, but don't overlap in time. The counts must make
    that distinguishable from "no data at all" in a log line."""
    generated_at = datetime(2026, 8, 20, 0, tzinfo=timezone.utc)
    await _insert_archive(
        f"{_TEST_FORECAST_PREFIX}nooverlap",
        generated_at,
        [{"member_id": 0, "trajectory": [{"hour": 6, "rainfall_mm": 8.0}]}],
    )
    telemetry = _telemetry("Vellore", [(datetime(2022, 1, 5, 12, 20), 1.0)])

    samples = await build_matched_samples(
        telemetry, "Vellore", elevation_m=119.6, slope_deg=0.3, aspect_deg=152.0
    )
    assert len(samples) == 0
    assert samples.n_station_readings == 1
    assert samples.n_archived_forecasts >= 1


async def test_only_the_requested_station_is_used():
    """A different station's readings must never leak into this site's
    calibration -- they're a different physical place."""
    generated_at = datetime(2026, 8, 20, 0, tzinfo=timezone.utc)
    await _insert_archive(
        f"{_TEST_FORECAST_PREFIX}station",
        generated_at,
        [{"member_id": 0, "trajectory": [{"hour": 6, "rainfall_mm": 8.0}]}],
    )
    telemetry = pd.concat(
        [
            _telemetry("Vellore", [(datetime(2026, 8, 20, 6, 0), 3.5)]),
            _telemetry("Anaikidangu", [(datetime(2026, 8, 20, 6, 0), 99.0)]),
        ],
        ignore_index=True,
    )

    samples = await build_matched_samples(
        telemetry, "Vellore", elevation_m=119.6, slope_deg=0.3, aspect_deg=152.0
    )
    assert samples.observed_mm == [3.5]  # never 99.0
    assert samples.n_station_readings == 1
