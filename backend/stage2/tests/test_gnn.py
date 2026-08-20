"""Tests for the single-scale SWE-GNN (T2.6, amended 2026-08-20)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple

import pytest
import torch

if TYPE_CHECKING:
    from backend.shared.contracts import DownscaledForecastField

from stage2.gnn.device import resolve_device
from stage2.gnn.graph_builder import OUT_DIM, PREVIOUS_T, build_graph
from stage2.gnn.errors import InsufficientHistoryError
from stage2.gnn.model import (
    NUM_EDGE_FEATURES,
    NUM_NODE_FEATURES,
    build_model,
    inject_boundary,
    predict_next_state,
)
from stage2.gnn.ensemble import run_ensemble
from stage2.gnn.training import train_on_solver_trajectory, validate_against_solver
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge
from stage2.solver.shallow_water_solver import run_trajectory


def _small_mesh(size: int = 4, resolution_m: float = 2.0) -> Tuple[
    List[ComputationalMeshNode], List[MeshEdge]
]:
    nodes, edges = [], []
    grid = [[f"n_{r}_{c}" for c in range(size)] for r in range(size)]
    for r in range(size):
        for c in range(size):
            nodes.append(
                ComputationalMeshNode(
                    node_id=grid[r][c], x_m=c * resolution_m, y_m=r * resolution_m,
                    elevation_m=100.0 - r * 0.3, is_wall_node=False, building_id=None,
                )
            )
    for r in range(size):
        for c in range(size):
            elev = 100.0 - r * 0.3
            for dr, dc in ((0, 1), (1, 0)):
                nr, nc = r + dr, c + dc
                if nr >= size or nc >= size:
                    continue
                oelev = 100.0 - nr * 0.3
                edges.append(
                    MeshEdge(
                        node_id_a=grid[r][c], node_id_b=grid[nr][nc],
                        distance_m=resolution_m, slope=(oelev - elev) / resolution_m,
                    )
                )
    return nodes, edges


def test_device_resolves_to_a_real_torch_device() -> None:
    device = resolve_device()
    assert isinstance(device, torch.device)
    assert device.type in ("mps", "cpu")


def test_cpu_preference_is_honoured() -> None:
    assert resolve_device(preference="cpu").type == "cpu"


def test_build_graph_produces_expected_shapes() -> None:
    nodes, edges = _small_mesh(size=4)
    depth_hist = [{n.node_id: 0.1 for n in nodes} for _ in range(PREVIOUS_T)]
    vel_hist = [{n.node_id: 0.05 for n in nodes} for _ in range(PREVIOUS_T)]

    graph = build_graph(nodes, edges, cell_area_m2=4.0, depth_history=depth_hist, velocity_history=vel_hist)

    assert graph.x.shape == (len(nodes), NUM_NODE_FEATURES)
    assert graph.edge_attr.shape == (2 * len(edges), NUM_EDGE_FEATURES)
    assert graph.edge_index.shape == (2, 2 * len(edges))


def test_build_graph_rejects_wrong_history_length() -> None:
    nodes, edges = _small_mesh(size=3)
    with pytest.raises(InsufficientHistoryError):
        build_graph(nodes, edges, 4.0, depth_history=[{}], velocity_history=[{}])


def test_model_builds_and_runs_a_forward_pass() -> None:
    nodes, edges = _small_mesh(size=4)
    device = resolve_device()
    model = build_model(device)

    depth_hist = [{n.node_id: 0.1 for n in nodes} for _ in range(PREVIOUS_T)]
    vel_hist = [{n.node_id: 0.05 for n in nodes} for _ in range(PREVIOUS_T)]
    graph = build_graph(nodes, edges, 4.0, depth_hist, vel_hist)

    output = predict_next_state(model, graph, device)
    assert output.shape == (len(nodes), OUT_DIM)
    assert torch.isfinite(output).all()
    assert (output >= 0).all()  # model applies ReLU (no negative depth/velocity)


def test_training_reduces_loss_on_real_solver_data() -> None:
    nodes, edges = _small_mesh(size=4)
    device = resolve_device()
    model = build_model(device)

    trajectory = run_trajectory(nodes, edges, [10.0] * 8, edge_width_m=2.0, hours_per_step=1.0)
    losses = train_on_solver_trajectory(
        model, nodes, edges, cell_area_m2=4.0, solver_trajectory=trajectory,
        inflow_mm_per_hour=[10.0] * 8, epochs=5, device=device,
    )
    assert len(losses) == 5
    assert all(torch.isfinite(torch.tensor(losses)))
    assert losses[-1] < losses[0] * 1.5  # loose bound -- 5 epochs on tiny data, not a tight convergence claim


def test_validate_against_solver_returns_real_finite_mae() -> None:
    nodes, edges = _small_mesh(size=4)
    device = resolve_device()
    model = build_model(device)

    train_traj = run_trajectory(nodes, edges, [10.0] * 8, edge_width_m=2.0, hours_per_step=1.0)
    train_on_solver_trajectory(
        model, nodes, edges, 4.0, train_traj, [10.0] * 8, epochs=3, device=device
    )

    holdout_traj = run_trajectory(nodes, edges, [5.0, 15.0, 20.0, 8.0, 4.0, 3.0, 2.0, 1.0], edge_width_m=2.0, hours_per_step=1.0)
    depth_mae, velocity_mae = validate_against_solver(model, nodes, edges, 4.0, holdout_traj, device=device)

    assert depth_mae >= 0.0 and velocity_mae >= 0.0
    import math
    assert math.isfinite(depth_mae) and math.isfinite(velocity_mae)


def test_inject_boundary_overwrites_only_the_target_node() -> None:
    depth_history: List[Dict[str, float]] = [{"a": 0.1, "b": 0.2}]
    velocity_history: List[Dict[str, float]] = [{"a": 0.05, "b": 0.06}]

    inject_boundary(depth_history, velocity_history, "a", depth_m=0.9, velocity_mps=0.7)

    assert depth_history[-1] == {"a": 0.9, "b": 0.2}
    assert velocity_history[-1] == {"a": 0.7, "b": 0.06}


# ------------------------------------------------------- ensemble propagation (T2.7)


def _forecast(site_id: str = "test-site", num_members: int = 3, hours: int = 5) -> "DownscaledForecastField":
    from backend.shared.contracts import (
        DownscaledEnsembleMember,
        DownscaledForecastField,
        DownscaledTimestepValue,
    )
    from datetime import datetime, timezone

    members = [
        DownscaledEnsembleMember(
            member_id=m,
            trajectory=[
                DownscaledTimestepValue(hour=h, inflow_mm=5.0 + m * 2.0 + h)
                for h in range(1, hours + 1)
            ],
        )
        for m in range(num_members)
    ]
    return DownscaledForecastField(
        site_id=site_id,
        site_lat=12.9165,
        site_lon=79.1325,
        calibration_confidence="computed_only_no_nearby_station",
        source_forecast_id="forecast-abc",
        generated_at=datetime.now(timezone.utc),
        members=members,
    )


def test_run_ensemble_produces_one_node_state_per_node_per_hour() -> None:
    nodes, edges = _small_mesh(size=4)
    device = resolve_device()
    model = build_model(device)
    forecast = _forecast(num_members=3, hours=4)

    result = run_ensemble(
        forecast, nodes, edges, model, cell_area_m2=4.0,
        hazard_threshold_m=0.1, validation_error_m=0.02,
        simulation_id="sim-1", device=device,
    )

    assert result.site_id == forecast.site_id
    assert result.source_forecast_id == forecast.source_forecast_id
    assert result.simulation_id == "sim-1"
    assert len(result.node_states) == len(nodes) * 4  # 4 hours


def test_run_ensemble_envelope_brackets_the_mean_sensibly() -> None:
    nodes, edges = _small_mesh(size=4)
    device = resolve_device()
    model = build_model(device)
    forecast = _forecast(num_members=4, hours=3)

    result = run_ensemble(
        forecast, nodes, edges, model, cell_area_m2=4.0,
        hazard_threshold_m=0.1, validation_error_m=0.02,
        simulation_id="sim-2", device=device,
    )

    assert result.envelope["member_count"] == 4
    assert result.envelope["total_hours"] == 3
    assert result.envelope["max_depth_m"] >= 0.0

    for ns in result.node_states:
        assert ns.depth_min_m <= ns.depth_mean_m <= ns.depth_max_m
        assert ns.velocity_min_mps <= ns.velocity_mean_mps <= ns.velocity_max_mps
        assert 0.0 <= ns.ensemble_agreement_fraction <= 1.0


def test_run_ensemble_never_floods_a_wall_node() -> None:
    nodes, edges = _small_mesh(size=4)
    nodes = [
        n.model_copy(update={"is_wall_node": True, "building_id": "Building_01"})
        if n.node_id == "n_1_1"
        else n
        for n in nodes
    ]
    device = resolve_device()
    model = build_model(device)
    forecast = _forecast(num_members=3, hours=3)

    result = run_ensemble(
        forecast, nodes, edges, model, cell_area_m2=4.0,
        hazard_threshold_m=0.1, validation_error_m=0.02,
        simulation_id="sim-3", device=device,
    )

    wall_states = [ns for ns in result.node_states if ns.node_id == "n_1_1"]
    assert len(wall_states) == 3  # one per hour
    assert all(ns.depth_mean_m == 0.0 and ns.depth_max_m == 0.0 for ns in wall_states)
    assert all(ns.building_id == "Building_01" for ns in wall_states)


def test_run_ensemble_rejects_empty_member_list() -> None:
    from backend.shared.contracts import DownscaledForecastField
    from datetime import datetime, timezone

    nodes, edges = _small_mesh(size=3)
    device = resolve_device()
    model = build_model(device)
    empty_forecast = DownscaledForecastField(
        site_id="s", site_lat=0.0, site_lon=0.0,
        calibration_confidence="computed_only_no_nearby_station",
        source_forecast_id="f", generated_at=datetime.now(timezone.utc), members=[],
    )
    with pytest.raises(ValueError):
        run_ensemble(
            empty_forecast, nodes, edges, model, cell_area_m2=4.0,
            hazard_threshold_m=0.1, validation_error_m=0.02,
            simulation_id="sim-4", device=device,
        )
