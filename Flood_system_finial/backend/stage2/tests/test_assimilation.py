"""Tests for live sensor assimilation via local ghost-cell nudging (T2.8)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Tuple

import pytest

if TYPE_CHECKING:
    from backend.shared.contracts import SensorReading

from stage2.assimilation.errors import SensorAtWallNodeError
from stage2.assimilation.ghost_cell_update import (
    assimilate_reading,
    distance_cm_to_depth_m,
    find_nearest_node,
)
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge, NodeState, SimulationResult


def _grid_mesh(
    size: int = 9, resolution_m: float = 2.0
) -> Tuple[List[ComputationalMeshNode], List[MeshEdge]]:
    nodes, edges = [], []
    grid = [[f"n_{r}_{c}" for c in range(size)] for r in range(size)]
    for r in range(size):
        for c in range(size):
            nodes.append(
                ComputationalMeshNode(
                    node_id=grid[r][c],
                    x_m=c * resolution_m,
                    y_m=r * resolution_m,
                    elevation_m=100.0,
                    is_wall_node=(r == 0 and c == 0),  # one wall node, for the wall-node test
                    building_id=("Building_01" if (r == 0 and c == 0) else None),
                )
            )
    for r in range(size):
        for c in range(size):
            for dr, dc in ((0, 1), (1, 0)):
                nr, nc = r + dr, c + dc
                if nr >= size or nc >= size:
                    continue
                edges.append(
                    MeshEdge(
                        node_id_a=grid[r][c],
                        node_id_b=grid[nr][nc],
                        distance_m=resolution_m,
                        slope=0.0,
                    )
                )
    return nodes, edges


def _flat_state(
    nodes: List[ComputationalMeshNode], hour: int = 3, baseline_depth_m: float = 0.02
) -> SimulationResult:
    node_states = [
        NodeState(
            node_id=n.node_id,
            hour=hour,
            depth_mean_m=baseline_depth_m,
            depth_min_m=max(0.0, baseline_depth_m - 0.01),
            depth_max_m=baseline_depth_m + 0.01,
            velocity_mean_mps=0.05,
            velocity_min_mps=0.02,
            velocity_max_mps=0.08,
            rate_of_rise=0.01,
            ensemble_agreement_fraction=0.3,
            building_id=n.building_id,
        )
        for n in nodes
    ]
    return SimulationResult(
        simulation_id="sim-test",
        site_id="test-site",
        source_forecast_id="forecast-test",
        generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=0.05,
        validation_error_m=0.02,
        node_states=node_states,
        envelope={},
    )


def _reading(distance_cm: float) -> "SensorReading":
    from backend.shared.contracts import SensorReading

    return SensorReading(
        sensor_id="sensor-1",
        site_id="test-site",
        distance_cm=distance_cm,
        timestamp=datetime.now(timezone.utc),
    )


def test_distance_cm_to_depth_m_conversion() -> None:
    assert distance_cm_to_depth_m(distance_cm=30.0, sensor_mount_height_m=0.5) == pytest.approx(0.2)
    # measured distance exceeds mount height -- clamp to 0, never negative
    assert distance_cm_to_depth_m(distance_cm=80.0, sensor_mount_height_m=0.5) == 0.0


def test_find_nearest_node_picks_the_real_closest() -> None:
    nodes, _ = _grid_mesh(size=5, resolution_m=2.0)
    nearest = find_nearest_node(nodes, target_x_m=4.1, target_y_m=6.2)
    assert nearest.node_id == "n_3_2"  # x=2*2=4, y=3*2=6 -- closest real grid point


def test_assimilate_reading_sets_target_node_to_the_real_measured_depth() -> None:
    """At the sensor's own nearest node (distance 0), the nudge weight is
    1.0 -- the real observation should fully replace the model's estimate,
    collapsing min=mean=max (no ensemble spread left to report)."""
    nodes, edges = _grid_mesh(size=9, resolution_m=2.0)
    state = _flat_state(nodes, hour=3, baseline_depth_m=0.02)
    reading = _reading(distance_cm=30.0)  # depth = 0.5 - 0.3 = 0.2m

    updated = assimilate_reading(
        reading, state, nodes, edges,
        target_x_m=8.0, target_y_m=8.0,  # n_4_4, mesh center
        sensor_mount_height_m=0.5, propagation_radius_m=6.0,
    )

    target_state = next(ns for ns in updated.node_states if ns.node_id == "n_4_4" and ns.hour == 3)
    assert target_state.depth_mean_m == pytest.approx(0.2)
    assert target_state.depth_min_m == target_state.depth_mean_m == target_state.depth_max_m
    assert target_state.ensemble_agreement_fraction == 1.0  # 0.2m > hazard_threshold_m (0.05m)


def test_assimilate_reading_decays_with_real_distance() -> None:
    """A node halfway to the radius edge should land roughly halfway
    between the observation and the model's background estimate (linear
    decay, per the module's stated nudging weight)."""
    nodes, edges = _grid_mesh(size=9, resolution_m=2.0)
    baseline_depth_m = 0.02
    state = _flat_state(nodes, hour=3, baseline_depth_m=baseline_depth_m)
    measured_depth_m = 0.2  # distance_cm=30, mount=0.5
    reading = _reading(distance_cm=30.0)

    updated = assimilate_reading(
        reading, state, nodes, edges,
        target_x_m=8.0, target_y_m=8.0,  # n_4_4
        sensor_mount_height_m=0.5, propagation_radius_m=6.0,
    )

    # n_4_6 is 4m (2 hops) from n_4_4 -- weight = 1 - 4/6 = 1/3
    neighbor_state = next(ns for ns in updated.node_states if ns.node_id == "n_4_6" and ns.hour == 3)
    expected = (1 / 3) * measured_depth_m + (2 / 3) * baseline_depth_m
    assert neighbor_state.depth_mean_m == pytest.approx(expected, rel=1e-6)
    # a nudge (convex combination) can never overshoot beyond the two inputs
    assert baseline_depth_m <= neighbor_state.depth_mean_m <= measured_depth_m


def test_assimilate_reading_never_touches_velocity_or_rate_of_rise() -> None:
    """The sensor measures depth only -- velocity/rate_of_rise are the
    model's own unaltered estimates at every node, including the target."""
    nodes, edges = _grid_mesh(size=9, resolution_m=2.0)
    state = _flat_state(nodes, hour=3)
    reading = _reading(distance_cm=30.0)

    updated = assimilate_reading(
        reading, state, nodes, edges,
        target_x_m=8.0, target_y_m=8.0,
        sensor_mount_height_m=0.5, propagation_radius_m=6.0,
    )

    for ns in updated.node_states:
        if ns.hour != 3:
            continue
        original = next(o for o in state.node_states if o.node_id == ns.node_id and o.hour == 3)
        assert ns.velocity_mean_mps == original.velocity_mean_mps
        assert ns.velocity_min_mps == original.velocity_min_mps
        assert ns.velocity_max_mps == original.velocity_max_mps
        assert ns.rate_of_rise == original.rate_of_rise


def test_assimilate_reading_leaves_far_nodes_untouched() -> None:
    nodes, edges = _grid_mesh(size=9, resolution_m=2.0)
    state = _flat_state(nodes, hour=3)
    reading = _reading(distance_cm=30.0)

    updated = assimilate_reading(
        reading, state, nodes, edges,
        target_x_m=8.0, target_y_m=8.0,
        sensor_mount_height_m=0.5,
        propagation_radius_m=4.0,  # small radius -- far corner must be untouched
    )

    original_far = next(ns for ns in state.node_states if ns.node_id == "n_8_1" and ns.hour == 3)
    updated_far = next(ns for ns in updated.node_states if ns.node_id == "n_8_1" and ns.hour == 3)
    assert updated_far is original_far  # same object -- proves it was never touched
    assert updated_far.depth_mean_m == pytest.approx(0.02)


def test_assimilate_reading_only_touches_the_latest_hour() -> None:
    nodes, edges = _grid_mesh(size=5, resolution_m=2.0)
    state = _flat_state(nodes, hour=3)
    earlier_states = [ns.model_copy(update={"hour": 1}) for ns in state.node_states]
    state = state.model_copy(update={"node_states": earlier_states + state.node_states})
    reading = _reading(distance_cm=20.0)

    updated = assimilate_reading(
        reading, state, nodes, edges,
        target_x_m=4.0, target_y_m=4.0,
        sensor_mount_height_m=0.5,
    )

    hour_1_states = [ns for ns in updated.node_states if ns.hour == 1]
    original_hour_1 = [ns for ns in state.node_states if ns.hour == 1]
    assert hour_1_states == original_hour_1  # every earlier-hour NodeState is byte-identical


def test_assimilate_reading_rejects_wall_node_target() -> None:
    nodes, edges = _grid_mesh(size=5, resolution_m=2.0)
    state = _flat_state(nodes, hour=3)
    reading = _reading(distance_cm=20.0)

    with pytest.raises(SensorAtWallNodeError):
        assimilate_reading(
            reading, state, nodes, edges,
            target_x_m=0.0, target_y_m=0.0,  # n_0_0, the wall node
            sensor_mount_height_m=0.5,
        )


def test_assimilate_reading_is_fast() -> None:
    nodes, edges = _grid_mesh(size=15, resolution_m=2.0)
    state = _flat_state(nodes, hour=3)
    reading = _reading(distance_cm=30.0)

    t0 = time.time()
    assimilate_reading(
        reading, state, nodes, edges,
        target_x_m=14.0, target_y_m=14.0,
        sensor_mount_height_m=0.5,
        propagation_radius_m=8.0,
    )
    elapsed = time.time() - t0
    assert elapsed < 5.0  # generous bound for CI variance; real number pasted in CLAUDE.md's VERIFY
