"""Tests for the numerical shallow-water solver (T2.5)."""

from __future__ import annotations

import pytest

from stage2.shared.contracts import ComputationalMeshNode, MeshEdge
from typing import Tuple, List, Dict
from stage2.solver.shallow_water_solver import run_trajectory, total_volume_m3


def _grid_mesh(
    size: int, resolution_m: float = 2.0, elevation_slope: float = 0.0
) -> Tuple[List[ComputationalMeshNode], List[MeshEdge], List[List[str]]]:
    """A flat (or gently sloped) size x size 4-connected grid, no walls."""
    nodes = []
    node_id_grid = [[""] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            node_id = f"n_{row}_{col}"
            node_id_grid[row][col] = node_id
            nodes.append(
                ComputationalMeshNode(
                    node_id=node_id,
                    x_m=col * resolution_m,
                    y_m=row * resolution_m,
                    elevation_m=100.0 - row * elevation_slope,
                    is_wall_node=False,
                    building_id=None,
                )
            )
    edges = []
    for row in range(size):
        for col in range(size):
            this_id = node_id_grid[row][col]
            this_elev = 100.0 - row * elevation_slope
            for dr, dc in ((0, 1), (1, 0)):
                nr, nc = row + dr, col + dc
                if nr >= size or nc >= size:
                    continue
                other_id = node_id_grid[nr][nc]
                other_elev = 100.0 - nr * elevation_slope
                edges.append(
                    MeshEdge(
                        node_id_a=this_id,
                        node_id_b=other_id,
                        distance_m=resolution_m,
                        slope=(other_elev - this_elev) / resolution_m,
                    )
                )
    return nodes, edges, node_id_grid


def test_flat_grid_mass_is_conserved_after_rainfall() -> None:
    """Closed domain, no outflow: total volume must equal total rainfall input."""
    nodes, edges, _ = _grid_mesh(size=5, resolution_m=2.0)
    resolution_m = 2.0
    inflow_mm_per_hour = [10.0, 10.0, 5.0]  # 3 one-hour steps

    result = run_trajectory(
        nodes, edges, inflow_mm_per_hour, edge_width_m=resolution_m, hours_per_step=1.0
    )

    final_depths = {node_id: points[-1].depth_m for node_id, points in result.items()}
    actual_volume = total_volume_m3(nodes, final_depths, resolution_m)

    cell_area = resolution_m**2
    expected_volume = sum(
        (rate / 1000.0) * cell_area for rate in inflow_mm_per_hour
    ) * len(nodes)

    assert actual_volume == pytest.approx(expected_volume, rel=1e-6)


def test_wall_nodes_never_accumulate_water() -> None:
    nodes, edges, grid = _grid_mesh(size=5, resolution_m=2.0)
    # Tag the center node as a wall.
    center_id = grid[2][2]
    nodes = [
        n.model_copy(update={"is_wall_node": True, "building_id": "Building_01"})
        if n.node_id == center_id
        else n
        for n in nodes
    ]

    result = run_trajectory(
        nodes, edges, [20.0, 20.0, 20.0], edge_width_m=2.0, hours_per_step=1.0
    )

    for point in result[center_id]:
        assert point.depth_m == 0.0
        assert point.velocity_mps == 0.0


def test_water_flows_downhill_from_higher_elevation() -> None:
    """A sloped grid should show more accumulated depth at the low end."""
    nodes, edges, grid = _grid_mesh(size=5, resolution_m=2.0, elevation_slope=1.0)

    result = run_trajectory(
        nodes, edges, [15.0] * 5, edge_width_m=2.0, hours_per_step=1.0,
        output_node_ids=[grid[0][2], grid[4][2]],
    )
    high_end_depth = result[grid[0][2]][-1].depth_m
    low_end_depth = result[grid[4][2]][-1].depth_m
    assert low_end_depth > high_end_depth


def test_no_rainfall_produces_no_depth_change() -> None:
    nodes, edges, _ = _grid_mesh(size=3, resolution_m=2.0)
    result = run_trajectory(nodes, edges, [0.0, 0.0], edge_width_m=2.0, hours_per_step=1.0)
    for points in result.values():
        for point in points:
            assert point.depth_m == pytest.approx(0.0, abs=1e-9)
            assert point.rate_of_rise_m_per_hr == pytest.approx(0.0, abs=1e-9)


def test_rate_of_rise_matches_depth_change_between_steps() -> None:
    nodes, edges, grid = _grid_mesh(size=3, resolution_m=2.0)
    node_id = grid[1][1]
    result = run_trajectory(
        nodes, edges, [10.0, 20.0], edge_width_m=2.0, hours_per_step=1.0,
        output_node_ids=[node_id],
    )
    points = result[node_id]
    implied_rate = (points[1].depth_m - points[0].depth_m) / 1.0
    assert points[1].rate_of_rise_m_per_hr == pytest.approx(implied_rate, rel=1e-6)


def test_output_node_ids_limits_returned_trajectories() -> None:
    nodes, edges, grid = _grid_mesh(size=4, resolution_m=2.0)
    result = run_trajectory(
        nodes, edges, [5.0], edge_width_m=2.0, hours_per_step=1.0,
        output_node_ids=[grid[0][0], grid[3][3]],
    )
    assert set(result.keys()) == {grid[0][0], grid[3][3]}
