"""Tests for Stage 2's data contracts (T2.0)."""

from __future__ import annotations

from datetime import datetime, timezone

from stage2.shared.contracts import (
    AnchorPoint,
    BuildingFootprint,
    ComputationalMeshNode,
    NodeState,
    SimulationResult,
    TerrainGrid,
)


def test_imports_stage1b_contracts_as_identical_classes() -> None:
    """Must be the SAME class object Stage 1B uses, not a structural copy."""
    from backend.shared.contracts import DownscaledForecastField as Canonical
    from stage2.shared.contracts import DownscaledForecastField as ViaStage2

    assert ViaStage2 is Canonical


def test_anchor_point_round_trips() -> None:
    anchor = AnchorPoint(
        scene_object_name="Anchor",
        scene_local_position=[0.0, 0.0, 0.0],
        real_world_lat=12.9165,
        real_world_lon=79.1325,
        real_world_elevation_m=216.0,
        scene_to_real_scale_factor=1.0,
        north_axis="+Y",
    )
    assert AnchorPoint.model_validate(anchor.model_dump()) == anchor


def test_building_footprint_round_trips() -> None:
    fp = BuildingFootprint(
        building_id="Building_01",
        footprint_polygon=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        height_m=12.5,
    )
    assert BuildingFootprint.model_validate(fp.model_dump()) == fp


def test_terrain_grid_honesty_flag_is_required() -> None:
    grid = TerrainGrid(
        site_id="vellore_demo_site_01",
        resolution_m=1.0,
        origin_lat=12.9165,
        origin_lon=79.1325,
        elevation_grid=[[216.0, 216.1], [216.2, 216.3]],
        interpolated_from_regional_dem=True,
    )
    assert grid.interpolated_from_regional_dem is True


def test_computational_mesh_node_round_trips() -> None:
    node = ComputationalMeshNode(
        node_id="n0",
        x_m=1.0,
        y_m=2.0,
        elevation_m=216.0,
        is_wall_node=False,
        building_id=None,
    )
    assert ComputationalMeshNode.model_validate(node.model_dump()) == node


def test_simulation_result_round_trips() -> None:
    """Uses Stage 3's already-built NodeState/SimulationResult shape (flat,
    one NodeState per node-hour) -- adopted 2026-08-20 to reconcile with
    Stage 3's independently-built version; see shared/contracts.py's
    module docstring."""
    result = SimulationResult(
        simulation_id="sim-1",
        site_id="vellore_demo_site_01",
        source_forecast_id="downscaled-abc123",
        generated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        hazard_threshold_m=0.3,
        validation_error_m=0.12,
        node_states=[
            NodeState(
                node_id="n0",
                hour=6,
                depth_mean_m=0.1,
                depth_min_m=0.05,
                depth_max_m=0.2,
                velocity_mean_mps=0.3,
                velocity_min_mps=0.1,
                velocity_max_mps=0.5,
                rate_of_rise=0.02,
                ensemble_agreement_fraction=0.8,
                building_id=None,
                road_segment_id=None,
            )
        ],
        envelope={},
    )
    assert SimulationResult.model_validate(result.model_dump()) == result
