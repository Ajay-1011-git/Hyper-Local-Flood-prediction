"""Tests for T1B.5 — nearest TN WRD station lookup.

The real live run (T1B.4's actual fetched 174,311-row telemetry, real
Vellore target coordinates) found a station literally named "Vellore" at
(12.948611, 79.138889), 3.64km from the target site — well inside the
default 25km threshold. See this task's commit message for that full
VERIFY output. These tests cover the math (haversine, threshold logic,
dedup) with small synthetic fixtures so they're fast and don't depend on
network access.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backend.stage1b.tnwrd.nearest_station import (
    DEFAULT_PROXIMITY_THRESHOLD_KM,
    _haversine_km,
    find_nearest_tnwrd_station,
    get_calibration_confidence,
)


def test_haversine_known_distance_london_paris():
    # Well-known reference distance: London <-> Paris is ~344km great-circle.
    d = _haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert d == pytest.approx(344, abs=5)


def test_haversine_zero_distance_for_identical_points():
    assert _haversine_km(12.9, 79.1, 12.9, 79.1) == pytest.approx(0.0, abs=1e-9)


def test_find_nearest_station_picks_the_closest_not_the_first():
    # Far station listed first, close one listed second/third -> function
    # must not just return row order.
    stations = pd.DataFrame(
        [
            {
                "station_id": "Far",
                "station_name": "Far",
                "latitude": 20.0,
                "longitude": 85.0,
                "rainfall_mm": 1.0,
            },
            {
                "station_id": "Near",
                "station_name": "Near",
                "latitude": 12.92,
                "longitude": 79.14,
                "rainfall_mm": 2.0,
            },
            {
                "station_id": "Mid",
                "station_name": "Mid",
                "latitude": 13.5,
                "longitude": 80.0,
                "rainfall_mm": 3.0,
            },
        ]
    )
    station, distance_km = find_nearest_tnwrd_station(12.9165, 79.1325, stations)
    assert station["station_id"] == "Near"
    assert distance_km < 5.0


def test_find_nearest_station_deduplicates_per_reading_rows():
    # Same station repeated across many hourly readings (T1B.4's real
    # output shape) must not be treated as multiple distinct stations, and
    # must not distort which one is nearest.
    rows = []
    for hour in range(5):
        rows.append(
            {
                "station_id": "Vellore",
                "station_name": "Vellore",
                "latitude": 12.948611,
                "longitude": 79.138889,
                "rainfall_mm": float(hour),
            }
        )
    rows.append(
        {
            "station_id": "FarAway",
            "station_name": "FarAway",
            "latitude": 8.0,
            "longitude": 77.0,
            "rainfall_mm": 0.5,
        }
    )
    stations = pd.DataFrame(rows)

    station, distance_km = find_nearest_tnwrd_station(12.9165, 79.1325, stations)
    assert station["station_id"] == "Vellore"
    assert distance_km == pytest.approx(3.64, abs=0.1)


def test_find_nearest_station_raises_on_empty_input():
    with pytest.raises(ValueError):
        find_nearest_tnwrd_station(12.9, 79.1, pd.DataFrame())


def test_get_calibration_confidence_within_threshold():
    assert get_calibration_confidence(3.64) == "calibrated_nearby_station"
    assert get_calibration_confidence(24.99, threshold_km=25.0) == (
        "calibrated_nearby_station"
    )


def test_get_calibration_confidence_outside_threshold():
    assert get_calibration_confidence(25.01, threshold_km=25.0) == (
        "computed_only_no_nearby_station"
    )
    assert get_calibration_confidence(200.0) == "computed_only_no_nearby_station"


def test_get_calibration_confidence_default_threshold_is_25km():
    assert DEFAULT_PROXIMITY_THRESHOLD_KM == 25.0
