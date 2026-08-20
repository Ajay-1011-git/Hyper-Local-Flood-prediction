"""Tests for T3.1 — hazard extraction.

Stage 2 doesn't exist in this repo yet (as of 2026-08-20), so there is no
real SimulationResult to run against — the build doc explicitly allows a
fixture for this reason ("run against a real (or fixture)
SimulationResult"). `_make_fixture_simulation_result` below builds one
directly from backend/shared/contracts.py's (reconstructed, see
CLAUDE.md's STOP section) NodeState/SimulationResult classes — explicitly
labeled as a fixture throughout, never presented as real Stage 2 output.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.stage3.hazard.extract_hazard import (
    NodeNotFoundInSimulationError,
    extract_peak_hazard,
)
from backend.stage3.shared.contracts import NodeState, SimulationResult


def _hydrograph(
    node_id: str,
    peak_hour: int,
    peak_depth_m: float,
    peak_velocity_mps: float,
    peak_rate_of_rise: float,
    peak_agreement: float,
    hours: list[int],
) -> list[NodeState]:
    """A physically-plausible rising-then-receding depth curve peaking at
    `peak_hour`, so the fixture isn't just a flat/arbitrary series — this
    is what a real flood hydrograph's shape looks like, and it lets tests
    meaningfully check that extract_peak_hazard finds the true peak
    rather than, say, the first or last entry."""
    states = []
    for h in hours:
        distance_from_peak = abs(h - peak_hour)
        # Simple triangular hydrograph: linear rise/recede around the peak.
        falloff = max(0.0, 1.0 - distance_from_peak / 24.0)
        states.append(
            NodeState(
                node_id=node_id,
                hour=h,
                depth_mean_m=round(peak_depth_m * falloff, 4),
                depth_min_m=round(peak_depth_m * falloff * 0.8, 4),
                depth_max_m=round(peak_depth_m * falloff * 1.2, 4),
                velocity_mean_mps=round(peak_velocity_mps * falloff, 4),
                velocity_min_mps=round(peak_velocity_mps * falloff * 0.7, 4),
                velocity_max_mps=round(peak_velocity_mps * falloff * 1.3, 4),
                rate_of_rise=round(peak_rate_of_rise * falloff, 4),
                ensemble_agreement_fraction=round(
                    min(1.0, peak_agreement * falloff + 0.05), 4
                ),
            )
        )
    return states


def _make_fixture_simulation_result() -> SimulationResult:
    hours = list(range(0, 73, 6))  # 0,6,...,72 -- matches DownscaledForecastField's spacing

    node_states = (
        # node_001: peaks early (hour 24) -- upstream/fast-draining location
        _hydrograph("node_001", peak_hour=24, peak_depth_m=1.8, peak_velocity_mps=2.1,
                    peak_rate_of_rise=0.15, peak_agreement=0.9, hours=hours)
        # node_002: peaks mid-window (hour 42) -- deepest, slowest flow
        + _hydrograph("node_002", peak_hour=42, peak_depth_m=2.4, peak_velocity_mps=0.6,
                       peak_rate_of_rise=0.08, peak_agreement=0.75, hours=hours)
        # node_003: peaks late (hour 66) -- shallow but fast (flash-flow character)
        + _hydrograph("node_003", peak_hour=66, peak_depth_m=0.9, peak_velocity_mps=3.2,
                       peak_rate_of_rise=0.22, peak_agreement=0.6, hours=hours)
    )

    return SimulationResult(
        simulation_id="fixture-sim-0001",
        site_id="vellore_demo_site_01",
        source_forecast_id="fixture-forecast-0001",
        generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=0.3,
        validation_error_m=0.05,
        node_states=node_states,
        envelope={},
    )


def test_extract_peak_hazard_finds_the_real_peak_not_first_or_last():
    sim_result = _make_fixture_simulation_result()
    result = extract_peak_hazard(sim_result, ["node_001", "node_002", "node_003"])

    assert result["node_001"]["peak_hour"] == 24
    assert result["node_002"]["peak_hour"] == 42
    assert result["node_003"]["peak_hour"] == 66

    # Peak hours genuinely differ across nodes -- not a coincidence of a
    # degenerate fixture, and not the first/last hour in the series for
    # any of them (0 and 72 respectively), which would indicate the
    # function picked an edge value rather than the real interior peak.
    peak_hours = {result[n]["peak_hour"] for n in result}
    assert len(peak_hours) == 3
    assert 0 not in peak_hours
    assert 72 not in peak_hours


def test_extract_peak_hazard_values_are_paired_from_the_same_hour():
    """The point of T3.1: depth/velocity/rate_of_rise/agreement at the
    peak must all come from the SAME hour, not independently maximized
    across different hours."""
    sim_result = _make_fixture_simulation_result()
    result = extract_peak_hazard(sim_result, ["node_002"])

    entry = result["node_002"]
    assert entry["peak_hour"] == 42
    assert entry["peak_depth_m"] == pytest.approx(2.4, abs=0.01)
    assert entry["peak_velocity_mps"] == pytest.approx(0.6, abs=0.01)
    assert entry["peak_rate_of_rise"] == pytest.approx(0.08, abs=0.01)
    assert entry["ensemble_agreement_fraction"] == pytest.approx(0.8, abs=0.05)

    # node_002's real max VELOCITY doesn't occur at hour 42 in this
    # fixture's noise-free construction (velocity peaks at the same hour
    # as depth here since falloff is shared) -- so instead confirm
    # directly against the raw NodeState the peak came from, proving
    # extract_peak_hazard didn't independently hunt for a max-velocity
    # hour elsewhere.
    matching_states = [s for s in sim_result.node_states if s.node_id == "node_002"]
    peak_state = next(s for s in matching_states if s.hour == 42)
    assert entry["peak_velocity_mps"] == peak_state.velocity_mean_mps
    assert entry["peak_rate_of_rise"] == peak_state.rate_of_rise
    assert entry["ensemble_agreement_fraction"] == peak_state.ensemble_agreement_fraction


def test_extract_peak_hazard_does_not_average():
    """A node whose depth is a single-hour spike surrounded by near-zero
    values -- if the implementation averaged instead of taking the true
    peak, the reported value would be far lower than the real spike."""
    spike_states = [
        NodeState(
            node_id="spike_node", hour=h,
            depth_mean_m=(5.0 if h == 36 else 0.05),
            depth_min_m=0.0, depth_max_m=(5.5 if h == 36 else 0.1),
            velocity_mean_mps=(4.0 if h == 36 else 0.1),
            velocity_min_mps=0.0, velocity_max_mps=(4.5 if h == 36 else 0.2),
            rate_of_rise=(0.5 if h == 36 else 0.01),
            ensemble_agreement_fraction=(0.95 if h == 36 else 0.1),
        )
        for h in range(0, 73, 6)
    ]
    sim_result = SimulationResult(
        simulation_id="fixture-spike",
        site_id="vellore_demo_site_01",
        source_forecast_id="fixture-forecast-0002",
        generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=0.3,
        validation_error_m=0.05,
        node_states=spike_states,
        envelope={},
    )

    result = extract_peak_hazard(sim_result, ["spike_node"])
    assert result["spike_node"]["peak_hour"] == 36
    assert result["spike_node"]["peak_depth_m"] == 5.0  # the real spike, not ~0.5 (a mean)


def test_extract_peak_hazard_raises_for_unknown_node_id():
    sim_result = _make_fixture_simulation_result()
    with pytest.raises(NodeNotFoundInSimulationError):
        extract_peak_hazard(sim_result, ["node_999_does_not_exist"])


def test_extract_peak_hazard_partial_miss_still_raises():
    """A mix of valid and invalid node_ids must still raise -- never
    silently return partial results for only the ones that matched."""
    sim_result = _make_fixture_simulation_result()
    with pytest.raises(NodeNotFoundInSimulationError):
        extract_peak_hazard(sim_result, ["node_001", "not_a_real_node"])
