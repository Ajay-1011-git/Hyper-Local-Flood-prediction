"""Tests for the CWC nearest-station lookup and parser (T1A.7)."""

from __future__ import annotations

import pytest

from stage1a.cwc.errors import CWCParseError
from stage1a.cwc.parser import (
    find_nearest_station,
    haversine_km,
    latest_reading_time,
    parse_station_forecast,
)

VELLORE = (12.9165, 79.1325)


def _station(station_id: str, lat: float, lon: float) -> dict:
    return {
        "station_id": station_id,
        "station_name": station_id,
        "lat": lat,
        "lon": lon,
        "river": "TestRiver",
        "district": "TestDistrict",
        "state": "Tamil Nadu",
        "resource_id": "test-resource",
        "resource_label": "test",
        "agency": "CWC",
    }


def _record(hour_label: str, level: str) -> dict:
    return {
        "Station": "s",
        "Data Acquisition Time": hour_label,
        "River Water Level Telemetry Hourly (meter)": level,
    }


# ------------------------------------------------------------- haversine


def test_haversine_zero_distance_for_identical_points() -> None:
    assert haversine_km(12.9, 79.1, 12.9, 79.1) == pytest.approx(0.0, abs=1e-9)


def test_haversine_known_distance() -> None:
    # Chennai (13.0827N, 80.2707E) to Bengaluru (12.9716N, 77.5946E),
    # real-world distance is roughly 290km.
    distance = haversine_km(13.0827, 80.2707, 12.9716, 77.5946)
    assert 280 <= distance <= 300


# ------------------------------------------------------- find_nearest_station


def test_finds_the_genuinely_closest_station() -> None:
    stations = [
        _station("far", 20.0, 80.0),
        _station("near", 12.92, 79.14),
        _station("mid", 15.0, 79.0),
    ]
    nearest = find_nearest_station(*VELLORE, stations)
    assert nearest["station_id"] == "near"
    assert nearest["_distance_km"] < 5


def test_raises_on_empty_station_list() -> None:
    with pytest.raises(CWCParseError):
        find_nearest_station(*VELLORE, [])


# ---------------------------------------------------------- parse_station_forecast


def test_trajectory_is_newest_first_hour_zero_and_negative() -> None:
    station = _station("s1", 12.92, 79.14)
    raw = [
        _record("19-08-2026 12:00", "1.5"),
        _record("19-08-2026 11:00", "1.4"),
        _record("19-08-2026 10:00", "1.3"),
    ]
    forecast = parse_station_forecast(raw, station, *VELLORE, proximity_threshold_km=25.0)
    hours = [t.hour for t in forecast.trajectory]
    assert hours == [0, -1, -2]
    assert forecast.forecast_horizon_hours == 0


def test_proximity_verified_true_within_threshold() -> None:
    station = _station("close", 12.92, 79.14)  # ~0.5km from Vellore
    raw = [_record("19-08-2026 12:00", "1.0")]
    forecast = parse_station_forecast(raw, station, *VELLORE, proximity_threshold_km=25.0)
    assert forecast.station_proximity_verified is True


def test_proximity_verified_false_beyond_threshold() -> None:
    station = _station("far", 15.0, 79.0)  # well beyond 25km
    raw = [_record("19-08-2026 12:00", "1.0")]
    forecast = parse_station_forecast(raw, station, *VELLORE, proximity_threshold_km=25.0)
    assert forecast.station_proximity_verified is False
    # still returns a real forecast from the nearest available station,
    # never fails silently and never invents a closer one
    assert len(forecast.trajectory) == 1


def test_placeholder_readings_are_skipped_not_fabricated() -> None:
    station = _station("s1", 12.92, 79.14)
    raw = [
        _record("19-08-2026 12:00", "-"),
        _record("19-08-2026 11:00", "1.4"),
        _record("19-08-2026 10:00", "-"),
    ]
    forecast = parse_station_forecast(raw, station, *VELLORE, proximity_threshold_km=25.0)
    assert len(forecast.trajectory) == 1
    assert forecast.trajectory[0].water_level_m == 1.4


def test_all_unusable_readings_is_an_error() -> None:
    station = _station("s1", 12.92, 79.14)
    raw = [_record("19-08-2026 12:00", "-"), _record("19-08-2026 11:00", "-")]
    with pytest.raises(CWCParseError, match="none had a usable"):
        parse_station_forecast(raw, station, *VELLORE, proximity_threshold_km=25.0)


def test_breach_fields_are_never_fabricated() -> None:
    station = _station("s1", 12.92, 79.14)
    raw = [_record("19-08-2026 12:00", "1.0")]
    forecast = parse_station_forecast(raw, station, *VELLORE, proximity_threshold_km=25.0)
    assert forecast.breach_threshold_m is None
    assert forecast.breach_probability is None


def test_validates_against_shared_contract() -> None:
    from stage1a.shared.contracts import RiverStageForecast

    station = _station("s1", 12.92, 79.14)
    raw = [_record("19-08-2026 12:00", "1.0")]
    forecast = parse_station_forecast(raw, station, *VELLORE, proximity_threshold_km=25.0)
    assert isinstance(RiverStageForecast.model_validate(forecast.model_dump()), RiverStageForecast)


# ---------------------------------------------------------- latest_reading_time


def test_latest_reading_time_parses_the_confirmed_format() -> None:
    from datetime import datetime, timezone

    raw = [_record("19-08-2026 14:00", "1.0")]
    assert latest_reading_time(raw) == datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc)


def test_latest_reading_time_none_for_empty_input() -> None:
    assert latest_reading_time([]) is None
