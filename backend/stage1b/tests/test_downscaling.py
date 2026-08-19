"""Tests for T1B.6 — calibration fitting.

The real single-station VERIFY run (T1B.4/T1B.5's actual "Vellore" TN WRD
station, 1167 real historical readings, paired with a clearly-labeled
synthetic coarse-estimate fixture — see calibration.py's module docstring
for why a real GenCast historical archive isn't available yet) found the
intercept term (a real, genuinely-fit bias) but correctly flagged all four
terrain coefficients as unidentifiable, since single-station calibration
data has no elevation/slope/aspect variation to fit against. See this
task's commit message for that full output. These tests use small
synthetic fixtures (per the task's own instruction: "synthetic test
fixtures if none exists" for the identity-path check) to isolate and
verify each piece of that behavior fast and deterministically.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.stage1b.downscaling.calibration import (
    IDENTITY_COEFFICIENTS,
    MIN_CALIBRATION_SAMPLES,
    fit_calibration,
)


def _synthetic_multi_station_fixture(n=200, seed=1, true_elev_factor=0.2):
    rng = np.random.default_rng(seed)
    elevation = rng.uniform(50, 800, n)
    slope = rng.uniform(0, 20, n)
    aspect = rng.uniform(0, 360, n)
    coarse = rng.uniform(0, 20, n)
    observed = coarse * (1 + true_elev_factor * (elevation - 300) / 1000.0)
    observed += rng.normal(scale=0.05, size=n)  # small real-world-like noise
    return observed, coarse, elevation, slope, aspect


def test_fit_calibration_returns_identity_when_confidence_not_nearby():
    observed, coarse, elev, slope, aspect = _synthetic_multi_station_fixture()
    result = fit_calibration(
        observed, coarse, elev, slope, aspect, "computed_only_no_nearby_station"
    )
    assert result == IDENTITY_COEFFICIENTS


def test_fit_calibration_returns_identity_when_too_few_samples():
    n = MIN_CALIBRATION_SAMPLES - 1
    observed, coarse, elev, slope, aspect = _synthetic_multi_station_fixture(n=n)
    result = fit_calibration(
        observed, coarse, elev, slope, aspect, "calibrated_nearby_station"
    )
    assert result == IDENTITY_COEFFICIENTS


def test_fit_calibration_raises_on_mismatched_lengths():
    observed, coarse, elev, slope, aspect = _synthetic_multi_station_fixture()
    with pytest.raises(ValueError):
        fit_calibration(
            observed, coarse[:-1], elev, slope, aspect, "calibrated_nearby_station"
        )


def test_fit_calibration_marks_single_station_terrain_as_unidentifiable():
    # Mirrors the real VERIFY case: one physical location (constant
    # elevation/slope/aspect) sampled many times.
    n = 100
    rng = np.random.default_rng(2)
    coarse = rng.uniform(0, 15, n)
    observed = coarse + 0.3 + rng.normal(scale=0.2, size=n)
    elevation = np.full(n, 117.7)
    slope = np.full(n, 0.16)
    aspect = np.full(n, 63.9)

    result = fit_calibration(
        observed, coarse, elevation, slope, aspect, "calibrated_nearby_station"
    )

    assert set(result["unidentifiable_terrain_parameters"]) == {
        "elevation_factor_per_1000m",
        "slope_factor_per_45deg",
        "aspect_cos_factor",
        "aspect_sin_factor",
    }
    for name in result["unidentifiable_terrain_parameters"]:
        assert result[name] == 0.0
    # The intercept (systematic bias) IS identifiable even from a single
    # station and should recover the real ~0.3mm bias injected above.
    assert result["intercept_mm"] == pytest.approx(0.3, abs=0.1)
    assert result["n_samples"] == n


def test_fit_calibration_recovers_known_elevation_factor_from_multi_station_data():
    true_elev_factor = 0.2
    observed, coarse, elev, slope, aspect = _synthetic_multi_station_fixture(
        true_elev_factor=true_elev_factor
    )
    result = fit_calibration(
        observed, coarse, elev, slope, aspect, "calibrated_nearby_station"
    )
    assert result["unidentifiable_terrain_parameters"] == []
    assert result["elevation_factor_per_1000m"] == pytest.approx(
        true_elev_factor, abs=0.02
    )
    # No true slope/aspect effect was injected -> fitted factors should be
    # small, not spuriously large.
    assert abs(result["slope_factor_per_45deg"]) < 0.1
    assert abs(result["aspect_cos_factor"]) < 0.1
    assert abs(result["aspect_sin_factor"]) < 0.1
