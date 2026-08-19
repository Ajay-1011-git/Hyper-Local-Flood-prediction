"""Tests for T1B.6 (calibration fitting) and T1B.7 (downscaling model core).

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

from datetime import datetime, timezone

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.shared.contracts import (
    BoundingBox,
    EnsembleMember,
    RegionalEnsembleForecast,
    TimestepValue,
)
from backend.stage1b.downscaling.calibration import (
    IDENTITY_COEFFICIENTS,
    MIN_CALIBRATION_SAMPLES,
    fit_calibration,
)
from backend.stage1b.downscaling.model import downscale_rainfall
from backend.stage1b.downscaling.orchestrator import (
    SiteOutsideTerrainGridError,
    generate_downscaled_field,
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


# ---------------------------------------------------------------------------
# T1B.7 — downscale_rainfall
# ---------------------------------------------------------------------------

_FIXED_COEFFS = {
    "elevation_factor_per_1000m": 0.2,
    "slope_factor_per_45deg": 0.05,
    "aspect_cos_factor": -0.02,
    "aspect_sin_factor": 0.03,
    "intercept_mm": 0.3,
    "reference_elevation_m": 300.0,
}


def test_downscale_rainfall_is_deterministic():
    r1 = downscale_rainfall(12.5, 450.0, 8.0, 120.0, _FIXED_COEFFS)
    r2 = downscale_rainfall(12.5, 450.0, 8.0, 120.0, _FIXED_COEFFS)
    assert r1 == r2  # exact equality, not approx — same inputs, same float ops


def test_downscale_rainfall_matches_hand_computed_value():
    # coarse=12.5, elevation=450 (300 above reference), slope=8deg, aspect=120deg
    import math

    coarse = 12.5
    expected_factor = (
        1.0
        + 0.2 * (450.0 - 300.0) / 1000.0
        + 0.05 * 8.0 / 45.0
        + (-0.02) * math.cos(math.radians(120.0))
        + 0.03 * math.sin(math.radians(120.0))
    )
    expected = coarse * expected_factor + 0.3
    result = downscale_rainfall(coarse, 450.0, 8.0, 120.0, _FIXED_COEFFS)
    assert result == pytest.approx(expected)


def test_downscale_rainfall_is_passthrough_under_identity_coefficients():
    result = downscale_rainfall(12.5, 450.0, 8.0, 120.0, IDENTITY_COEFFICIENTS)
    assert result == 12.5


def test_downscale_rainfall_clamps_negative_result_to_zero():
    coeffs = dict(_FIXED_COEFFS)
    coeffs["intercept_mm"] = -1000.0  # forces a physically-impossible negative result
    result = downscale_rainfall(12.5, 450.0, 8.0, 120.0, coeffs)
    assert result == 0.0


def test_downscale_rainfall_never_negative_across_random_inputs():
    rng = np.random.default_rng(3)
    for _ in range(200):
        coarse = rng.uniform(0, 50)
        elevation = rng.uniform(-50, 2000)
        slope = rng.uniform(0, 45)
        aspect = rng.uniform(0, 360)
        coeffs = {
            "elevation_factor_per_1000m": rng.uniform(-1, 1),
            "slope_factor_per_45deg": rng.uniform(-1, 1),
            "aspect_cos_factor": rng.uniform(-1, 1),
            "aspect_sin_factor": rng.uniform(-1, 1),
            "intercept_mm": rng.uniform(-20, 20),
            "reference_elevation_m": rng.uniform(0, 500),
        }
        result = downscale_rainfall(coarse, elevation, slope, aspect, coeffs)
        assert result >= 0.0


# ---------------------------------------------------------------------------
# T1B.8 — generate_downscaled_field
# ---------------------------------------------------------------------------


def _write_synthetic_terrain_geotiff(path, elevation=200.0, slope=5.0, aspect=90.0):
    """A tiny 3-band GeoTIFF matching T1B.3's write_terrain_grids_geotiff
    output shape, centered on a small patch near Vellore, in the same UTM
    zone (32644) T1B.3 actually reprojects into."""
    height, width = 10, 10
    transform = from_origin(150000, 1440000, 2000, 2000)  # 2km cells, UTM 44N-ish
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype="float32",
        crs="EPSG:32644",
        transform=transform,
        nodata=float("nan"),
    ) as dst:
        dst.write(np.full((height, width), elevation, dtype="float32"), 1)
        dst.write(np.full((height, width), slope, dtype="float32"), 2)
        dst.write(np.full((height, width), aspect, dtype="float32"), 3)
    return transform


def _mock_regional_forecast(forecast_id="mock-forecast-test"):
    """Explicitly a MOCK RegionalEnsembleForecast — Stage 1A has no live
    endpoint in this repo yet (see orchestrator.py's module docstring).
    Not presented anywhere as a real Stage 1A call."""
    return RegionalEnsembleForecast(
        forecast_id=forecast_id,
        region_bbox=BoundingBox(min_lat=12.7, max_lat=13.1, min_lon=79.0, max_lon=79.3),
        generated_at=datetime.now(timezone.utc),
        members=[
            EnsembleMember(
                member_id=0,
                trajectory=[
                    TimestepValue(hour=0, rainfall_mm=2.0),
                    TimestepValue(hour=1, rainfall_mm=5.5),
                ],
            ),
            EnsembleMember(
                member_id=1,
                trajectory=[
                    TimestepValue(hour=0, rainfall_mm=1.0),
                    TimestepValue(hour=1, rainfall_mm=8.2),
                ],
            ),
        ],
    )


def _site_lat_lon_for_transform(transform, row=5, col=5):
    """Real coordinates that land inside the synthetic terrain grid above,
    computed the same way orchestrator.py samples terrain (just inverted)."""
    import rasterio.warp

    x, y = transform * (col, row)
    lons, lats = rasterio.warp.transform("EPSG:32644", "EPSG:4326", [x], [y])
    return lats[0], lons[0]


def test_generate_downscaled_field_member_ids_and_source_forecast_id_trace(tmp_path):
    terrain_path = tmp_path / "terrain.tif"
    transform = _write_synthetic_terrain_geotiff(terrain_path)
    lat, lon = _site_lat_lon_for_transform(transform)
    mock_forecast = _mock_regional_forecast(forecast_id="mock-forecast-abc")

    field = generate_downscaled_field(
        regional_forecast=mock_forecast,
        site_id="test_site",
        site_lat=lat,
        site_lon=lon,
        terrain_grid_path=str(terrain_path),
        calibration_coeffs=IDENTITY_COEFFICIENTS,
        calibration_confidence="calibrated_nearby_station",
    )

    assert [m.member_id for m in field.members] == [
        m.member_id for m in mock_forecast.members
    ]
    assert field.source_forecast_id == "mock-forecast-abc"
    assert field.site_id == "test_site"
    assert field.calibration_confidence == "calibrated_nearby_station"


def test_generate_downscaled_field_identity_coeffs_passthrough_every_value(tmp_path):
    terrain_path = tmp_path / "terrain.tif"
    transform = _write_synthetic_terrain_geotiff(terrain_path)
    lat, lon = _site_lat_lon_for_transform(transform)
    mock_forecast = _mock_regional_forecast()

    field = generate_downscaled_field(
        mock_forecast, "s", lat, lon, str(terrain_path), IDENTITY_COEFFICIENTS,
        "calibrated_nearby_station",
    )

    for in_member, out_member in zip(mock_forecast.members, field.members):
        for in_ts, out_ts in zip(in_member.trajectory, out_member.trajectory):
            assert out_ts.hour == in_ts.hour
            assert out_ts.inflow_mm == in_ts.rainfall_mm


def test_generate_downscaled_field_applies_real_terrain_adjustment(tmp_path):
    terrain_path = tmp_path / "terrain.tif"
    transform = _write_synthetic_terrain_geotiff(
        terrain_path, elevation=800.0, slope=10.0, aspect=45.0
    )
    lat, lon = _site_lat_lon_for_transform(transform)
    mock_forecast = _mock_regional_forecast()

    coeffs = {
        "elevation_factor_per_1000m": 0.1,
        "slope_factor_per_45deg": 0.0,
        "aspect_cos_factor": 0.0,
        "aspect_sin_factor": 0.0,
        "intercept_mm": 0.0,
        "reference_elevation_m": 300.0,
    }
    field = generate_downscaled_field(
        mock_forecast, "s", lat, lon, str(terrain_path), coeffs,
        "calibrated_nearby_station",
    )
    # elevation=800, ref=300 -> factor = 1 + 0.1*(800-300)/1000 = 1.05
    first_rainfall = mock_forecast.members[0].trajectory[0].rainfall_mm
    expected = first_rainfall * 1.05
    assert field.members[0].trajectory[0].inflow_mm == pytest.approx(expected)


def test_generate_downscaled_field_raises_when_site_outside_terrain_grid(tmp_path):
    terrain_path = tmp_path / "terrain.tif"
    _write_synthetic_terrain_geotiff(terrain_path)
    mock_forecast = _mock_regional_forecast()

    with pytest.raises(SiteOutsideTerrainGridError):
        generate_downscaled_field(
            mock_forecast, "s", 0.0, 0.0, str(terrain_path), IDENTITY_COEFFICIENTS,
            "calibrated_nearby_station",
        )
