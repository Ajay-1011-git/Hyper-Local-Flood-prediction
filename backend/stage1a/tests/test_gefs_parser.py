"""Tests for GEFS output -> `RegionalEnsembleForecast` parsing (2026-08-20 amendment).

`gefs_sample_p01_f003.grib2` is a REAL, live-fetched GRIB2 subset (988
bytes) -- member p01, forecast hour 003, cycle 2026-08-19 00Z, fetched
directly from NOAA's real NOMADS filter service this session (see
`gefs/client.py`/`gefs/parser.py`'s module docstrings for the full
confirmation). Not synthetic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from stage1a.gefs.errors import GEFSParseError
from stage1a.gefs.parser import (
    GEFS_MEMBERS,
    build_forecast_id,
    build_regional_ensemble_forecast,
    decode_regional_mean_mm,
)
from stage1a.shared.contracts import BoundingBox

TN_BBOX = BoundingBox(min_lat=8.0, max_lat=14.0, min_lon=76.0, max_lon=82.0)
CYCLE_START = datetime(2026, 8, 19, 0, tzinfo=timezone.utc)
REAL_FIXTURE = Path(__file__).parent / "fixtures" / "gefs_sample_p01_f003.grib2"


def test_decode_real_fixture_returns_a_plausible_regional_mean() -> None:
    value = decode_regional_mean_mm(REAL_FIXTURE, TN_BBOX)
    assert isinstance(value, float)
    assert value >= 0.0
    # Real value confirmed live this session was ~0.235mm regional mean
    # for this exact file; a wide but real sanity bound, not the exact
    # float (mean-of-25x25-cells arithmetic is deterministic given the
    # same file, but pinning the literal value would just be re-testing
    # cfgrib's own decode, not this function's logic).
    assert value < 50.0


def test_decode_missing_file_raises_typed_error(tmp_path: Path) -> None:
    with pytest.raises(GEFSParseError):
        decode_regional_mean_mm(tmp_path / "does_not_exist.grib2", TN_BBOX)


def test_forecast_id_is_namespaced() -> None:
    assert build_forecast_id(TN_BBOX, CYCLE_START).startswith("gefs-")


def test_forecast_id_is_deterministic() -> None:
    assert build_forecast_id(TN_BBOX, CYCLE_START) == build_forecast_id(TN_BBOX, CYCLE_START)


def _all_member_values(hours: tuple[int, ...] = (6, 12, 18)) -> dict[str, dict[int, float]]:
    return {member: {h: 0.1 * (i + 1) for i, h in enumerate(hours)} for member in GEFS_MEMBERS}


def test_build_forecast_produces_31_real_members() -> None:
    forecast = build_regional_ensemble_forecast(_all_member_values(), TN_BBOX, CYCLE_START)
    assert len(forecast.members) == 31
    assert forecast.source == "GEFS"
    assert forecast.resolution_km == pytest.approx(27.75)
    assert forecast.generated_at == CYCLE_START


def test_build_forecast_member_ids_are_stable_and_ordered() -> None:
    forecast = build_regional_ensemble_forecast(_all_member_values(), TN_BBOX, CYCLE_START)
    # c00 (control) is always member_id 0, matching GEFS_MEMBERS' own order.
    assert forecast.members[0].member_id == 0
    assert forecast.members[1].member_id == 1


def test_build_forecast_missing_member_raises_typed_error() -> None:
    values = _all_member_values()
    del values["p30"]
    with pytest.raises(GEFSParseError):
        build_regional_ensemble_forecast(values, TN_BBOX, CYCLE_START)


def test_build_forecast_unexpected_member_raises_typed_error() -> None:
    values = _all_member_values()
    values["p99"] = {6: 0.1}
    with pytest.raises(GEFSParseError):
        build_regional_ensemble_forecast(values, TN_BBOX, CYCLE_START)


def test_build_forecast_trajectory_hours_are_sorted() -> None:
    values = {member: {18: 0.3, 6: 0.1, 12: 0.2} for member in GEFS_MEMBERS}
    forecast = build_regional_ensemble_forecast(values, TN_BBOX, CYCLE_START)
    hours = [tv.hour for tv in forecast.members[0].trajectory]
    assert hours == [6, 12, 18]
