"""Tests for the precompute pipeline's real, load-bearing guards.

Focused on the two pieces of `precompute.py` that decide what the rest of
the system is allowed to believe:

  * `scale_forecast_to_heavy` — how hypothetical the heavy-rain scenario
    actually is, and that it stays a rescaling of the REAL ensemble
    rather than a synthetic curve.
  * `mass_conservation_ratio` — the physical admissibility check that
    caught the GNN emulator's rollout inventing ~7x the water that fell.

Both are pure functions over real contract objects, so none of this needs
the GLB, the DEM, a database or a trained model.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stage2.precompute import (
    HEAVY_TARGET_MM_PER_24H,
    MASS_CONSERVATION_LIMIT,
    mass_conservation_ratio,
    scale_forecast_to_heavy,
    total_rainfall_m,
)
from stage2.shared.contracts import (
    DownscaledForecastField,
    NodeState,
    SimulationResult,
)

# Stage 2's own `shared/contracts.py` re-exports only what Stage 2 itself
# uses; the member/timestep types live in the canonical shared module.
from backend.shared.contracts import (  # noqa: E402
    DownscaledEnsembleMember,
    DownscaledTimestepValue,
)


def _forecast(members_mm: list[list[float]]) -> DownscaledForecastField:
    """A real-shaped forecast: 6-hourly steps, one trajectory per member."""
    return DownscaledForecastField(
        site_id="test-site",
        site_lat=12.969223,
        site_lon=79.155934,
        resolution_km=2.0,
        calibration_source="test",
        calibration_confidence="uncalibrated",
        source_forecast_id="test-forecast",
        generated_at=datetime.now(timezone.utc),
        members=[
            DownscaledEnsembleMember(
                member_id=i,
                trajectory=[
                    DownscaledTimestepValue(hour=(j + 1) * 6, inflow_mm=mm)
                    for j, mm in enumerate(mms)
                ],
            )
            for i, mms in enumerate(members_mm)
        ],
    )


def _result(depths_by_hour: dict[int, list[float]]) -> SimulationResult:
    node_states = [
        NodeState(
            node_id=f"n_0_{i}",
            hour=hour,
            depth_mean_m=d,
            depth_min_m=d,
            depth_max_m=d,
            velocity_mean_mps=0.0,
            velocity_min_mps=0.0,
            velocity_max_mps=0.0,
            rate_of_rise=0.0,
            ensemble_agreement_fraction=0.0,
        )
        for hour, depths in depths_by_hour.items()
        for i, d in enumerate(depths)
    ]
    return SimulationResult(
        simulation_id="test",
        site_id="test-site",
        source_forecast_id="test-forecast",
        generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=0.3,
        validation_error_m=0.0,
        node_states=node_states,
        envelope={},
    )


class TestScaleForecastToHeavy:
    def test_wettest_member_reaches_the_real_imd_category(self):
        # 4 steps = 24h at this project's real 6-hourly cadence.
        forecast, _factor = scale_forecast_to_heavy(_forecast([[1.0, 1.0, 1.0, 1.0]]))
        peak_24h = sum(tv.inflow_mm for tv in forecast.members[0].trajectory)
        assert peak_24h == pytest.approx(HEAVY_TARGET_MM_PER_24H)

    def test_preserves_real_inter_member_spread(self):
        # The whole reason this rescales the real ensemble rather than
        # substituting a flat synthetic curve: ensemble_agreement_fraction
        # has to keep measuring REAL forecast disagreement.
        original = _forecast([[1.0, 1.0, 1.0, 1.0], [2.0, 2.0, 2.0, 2.0]])
        scaled, factor = scale_forecast_to_heavy(original)
        ratio_before = (
            original.members[1].trajectory[0].inflow_mm
            / original.members[0].trajectory[0].inflow_mm
        )
        ratio_after = (
            scaled.members[1].trajectory[0].inflow_mm
            / scaled.members[0].trajectory[0].inflow_mm
        )
        assert ratio_after == pytest.approx(ratio_before)
        assert factor > 1

    def test_reports_the_real_factor_it_applied(self):
        _scaled, factor = scale_forecast_to_heavy(_forecast([[1.0, 1.0, 1.0, 1.0]]))
        # 4mm per 24h scaled to the real target.
        assert factor == pytest.approx(HEAVY_TARGET_MM_PER_24H / 4.0)

    def test_refuses_a_bone_dry_forecast_rather_than_dividing_by_zero(self):
        from stage2.precompute import PrecomputeUnavailableError

        with pytest.raises(PrecomputeUnavailableError):
            scale_forecast_to_heavy(_forecast([[0.0, 0.0, 0.0, 0.0]]))


class TestMassConservation:
    def test_water_that_stays_put_is_admissible(self):
        # 100mm fell; the site holds 100mm. Ratio 1.0 -- the physical
        # ceiling, and allowed.
        rainfall_m = total_rainfall_m([(6, 100.0)])
        ratio = mass_conservation_ratio(_result({6: [0.1, 0.1, 0.1]}), rainfall_m)
        assert ratio == pytest.approx(1.0)
        assert ratio <= MASS_CONSERVATION_LIMIT

    def test_water_draining_away_is_admissible(self):
        rainfall_m = total_rainfall_m([(6, 100.0)])
        ratio = mass_conservation_ratio(_result({6: [0.02, 0.02, 0.02]}), rainfall_m)
        assert ratio < 1.0

    def test_manufactured_water_is_caught(self):
        # The real failure this guard exists for: the emulator reporting
        # far more water than ever fell.
        rainfall_m = total_rainfall_m([(6, 100.0)])
        ratio = mass_conservation_ratio(_result({6: [7.0, 7.0, 7.0]}), rainfall_m)
        assert ratio > MASS_CONSERVATION_LIMIT

    def test_one_deep_puddle_is_not_a_violation(self):
        # Water really does concentrate in hollows, so a single deep node
        # must NOT trip the guard -- only the site-wide total is bounded.
        rainfall_m = total_rainfall_m([(6, 100.0)])
        depths = [2.0] + [0.0] * 199  # one deep cell, mean well under 0.1m
        ratio = mass_conservation_ratio(_result({6: depths}), rainfall_m)
        assert ratio <= MASS_CONSERVATION_LIMIT

    def test_uses_the_worst_hour_not_just_the_last(self):
        rainfall_m = total_rainfall_m([(6, 100.0)])
        ratio = mass_conservation_ratio(
            _result({6: [0.01, 0.01], 12: [9.0, 9.0], 18: [0.01, 0.01]}), rainfall_m
        )
        assert ratio > MASS_CONSERVATION_LIMIT

    def test_no_rainfall_is_reported_as_zero_not_infinity(self):
        assert mass_conservation_ratio(_result({6: [0.5]}), 0.0) == 0.0
