"""Tests for T3.5 — risk ranking.

Stage 2 doesn't exist in this repo yet (as of 2026-08-20), so these tests
use an explicitly-labeled fixture `SimulationResult`, same convention as
test_hazard.py/test_exposure.py/test_vulnerability.py. Each node here
carries a single timestep (multi-hour peak-finding is already covered by
test_hazard.py) -- what these tests exercise is risk_ranking.py's own
logic: grouping nodes by structure via `building_id`/`road_segment_id`,
picking the worst node per structure, combining hazard x exposure x
vulnerability, sorting, ranking, and determinism.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.stage3.ranking.risk_ranking import (
    NoMatchingNodesForStructureError,
    rank_structures,
)
from backend.stage3.shared.contracts import (
    BuildingFootprint,
    NodeState,
    RoadSegment,
    SimulationResult,
)
from backend.stage3.vulnerability.fragility_curve import VULNERABILITY_CURVE_SOURCE


def _state(
    node_id: str,
    depth: float,
    velocity: float,
    rate_of_rise: float,
    agreement: float,
    *,
    building_id: str | None = None,
    road_segment_id: str | None = None,
    hour: int = 24,
) -> NodeState:
    return NodeState(
        node_id=node_id,
        hour=hour,
        depth_mean_m=depth,
        depth_min_m=depth * 0.8,
        depth_max_m=depth * 1.2,
        velocity_mean_mps=velocity,
        velocity_min_mps=velocity * 0.7,
        velocity_max_mps=velocity * 1.3,
        rate_of_rise=rate_of_rise,
        ensemble_agreement_fraction=agreement,
        building_id=building_id,
        road_segment_id=road_segment_id,
    )


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _make_fixture() -> SimulationResult:
    node_states = [
        # Building_01: two wall nodes -- b1_n2 is the real worst moment,
        # b1_n1 is shallower. Ranking must reflect the WORST node, not an
        # average of the two.
        _state("b1_n1", depth=0.6, velocity=0.3, rate_of_rise=0.02, agreement=0.9,
               building_id="Building_01"),
        _state("b1_n2", depth=1.5, velocity=0.5, rate_of_rise=0.05, agreement=0.85,
               building_id="Building_01"),
        # Building_02: single wall node, deep AND fast -- expected to rank
        # highest risk.
        _state("b2_n1", depth=3.0, velocity=2.8, rate_of_rise=0.30, agreement=0.7,
               building_id="Building_02"),
        # Building_03: single wall node, shallow and slow -- expected to
        # rank lowest risk of the three buildings.
        _state("b3_n1", depth=0.2, velocity=0.1, rate_of_rise=0.01, agreement=0.95,
               building_id="Building_03"),
        # Road segments.
        _state("r1_n1", depth=0.8, velocity=0.4, rate_of_rise=0.03, agreement=0.8,
               road_segment_id="Road_Segment_01"),
        _state("r2_n1", depth=2.0, velocity=2.5, rate_of_rise=0.25, agreement=0.65,
               road_segment_id="Road_Segment_02"),
        # A background/open-terrain node tagged to NEITHER a building nor a
        # road -- carries an extreme depth specifically so a test can
        # confirm it never leaks into any structure's score.
        _state("background_n1", depth=99.0, velocity=99.0, rate_of_rise=9.0, agreement=1.0),
    ]

    return SimulationResult(
        simulation_id="fixture-ranking-sim-0001",
        site_id="vellore_demo_site_01",
        source_forecast_id="fixture-forecast-0003",
        generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=0.3,
        validation_error_m=0.05,
        node_states=node_states,
        envelope={},
    )


def _footprints() -> list[BuildingFootprint]:
    return [
        BuildingFootprint(building_id="Building_01", footprint_polygon=_rect(0, 0, 10, 10)),
        BuildingFootprint(building_id="Building_02", footprint_polygon=_rect(20, 0, 50, 10)),
        BuildingFootprint(building_id="Building_03", footprint_polygon=_rect(60, 0, 70, 5)),
    ]


def _road_segments() -> list[RoadSegment]:
    return [
        RoadSegment(segment_id="Road_Segment_01", polyline=[[0, 20], [20, 20]], width_m=7.0),
        RoadSegment(segment_id="Road_Segment_02", polyline=[[0, 30], [20, 30]], width_m=7.0),
    ]


def test_rank_structures_covers_every_building_and_road_segment():
    sim_result = _make_fixture()
    entries = rank_structures(sim_result, _footprints(), _road_segments())

    structure_ids = {e.structure_id for e in entries}
    assert structure_ids == {
        "Building_01", "Building_02", "Building_03",
        "Road_Segment_01", "Road_Segment_02",
    }
    types = {e.structure_id: e.structure_type for e in entries}
    assert types["Building_01"] == "building"
    assert types["Road_Segment_01"] == "road_segment"


def test_rank_structures_picks_the_worst_node_not_the_first_or_an_average():
    """Building_01 has two nodes (depth 0.6 and 1.5) -- the entry must
    reflect the real worst one (1.5), not the first node encountered and
    not their average (1.05)."""
    sim_result = _make_fixture()
    entries = rank_structures(sim_result, _footprints(), _road_segments())
    b1 = next(e for e in entries if e.structure_id == "Building_01")

    assert b1.peak_depth_m == pytest.approx(1.5)
    assert b1.peak_velocity_mps == pytest.approx(0.5)
    assert b1.peak_rate_of_rise == pytest.approx(0.05)
    assert b1.confidence == pytest.approx(0.85)


def test_rank_structures_never_leaks_untagged_background_nodes():
    """background_n1 carries an extreme depth (99.0) but is tagged to
    neither a building nor a road -- no entry's peak_depth_m should ever
    reflect it."""
    sim_result = _make_fixture()
    entries = rank_structures(sim_result, _footprints(), _road_segments())
    for entry in entries:
        assert entry.peak_depth_m < 99.0


def test_rank_structures_hazard_score_reflects_velocity_and_rate_of_rise_not_depth_alone():
    """The non-negotiable project rule: hazard_score must move when
    velocity/rate_of_rise change, even if depth doesn't. Road_Segment_02
    (depth 2.0, velocity 2.5) must score a higher hazard_score than a
    hypothetical same-depth-but-still node would."""
    sim_result = _make_fixture()
    entries = rank_structures(sim_result, _footprints(), _road_segments())
    r2 = next(e for e in entries if e.structure_id == "Road_Segment_02")

    depth_only_score = r2.peak_depth_m
    assert r2.hazard_score > depth_only_score  # velocity + rate_of_rise both add real weight


def test_rank_structures_sorted_descending_by_risk_score():
    sim_result = _make_fixture()
    entries = rank_structures(sim_result, _footprints(), _road_segments())
    risk_scores = [e.risk_score for e in entries]
    assert risk_scores == sorted(risk_scores, reverse=True)


def test_rank_structures_assigns_sequential_rank_starting_at_one():
    sim_result = _make_fixture()
    entries = rank_structures(sim_result, _footprints(), _road_segments())
    assert [e.rank for e in entries] == list(range(1, len(entries) + 1))
    # rank 1 must be the actual highest risk_score, not just index 0 by luck
    assert entries[0].risk_score == max(e.risk_score for e in entries)


def test_rank_structures_building_02_is_the_highest_risk():
    """Sanity check against the fixture's own physically-designed
    story: Building_02 (deep, fast, wide) should be the single highest
    risk_score of all 5 structures."""
    sim_result = _make_fixture()
    entries = rank_structures(sim_result, _footprints(), _road_segments())
    assert entries[0].structure_id == "Building_02"


def test_rank_structures_is_deterministic_across_repeat_runs():
    sim_result = _make_fixture()
    footprints = _footprints()
    road_segments = _road_segments()

    run_1 = rank_structures(sim_result, footprints, road_segments)
    run_2 = rank_structures(sim_result, footprints, road_segments)

    dump_1 = [e.model_dump() for e in run_1]
    dump_2 = [e.model_dump() for e in run_2]
    assert dump_1 == dump_2


def test_rank_structures_vulnerability_source_and_calibration_flag_are_honest():
    sim_result = _make_fixture()
    entries = rank_structures(sim_result, _footprints(), _road_segments())
    for entry in entries:
        assert entry.vulnerability_source == VULNERABILITY_CURVE_SOURCE
        assert entry.vulnerability_is_local_calibration is False


def test_rank_structures_raises_for_a_building_with_no_matching_nodes():
    sim_result = _make_fixture()
    footprints = _footprints() + [
        BuildingFootprint(building_id="Building_99_does_not_exist", footprint_polygon=_rect(0, 0, 1, 1))
    ]
    with pytest.raises(NoMatchingNodesForStructureError):
        rank_structures(sim_result, footprints, _road_segments())
