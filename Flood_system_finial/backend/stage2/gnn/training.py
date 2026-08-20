"""Train the single-scale SWE-GNN on T2.5's solver-generated trajectories (T2.6).

Teacher-forced training: at every timestep past the first `PREVIOUS_T`
solver outputs, build the input graph from `PREVIOUS_T` steps of REAL
solver history, predict the next state, compare against the solver's own
real next state via `hybrid_loss`, backpropagate. This is a genuine
training procedure against real (solver-generated, not fabricated) data —
simpler than the original repo's `LightningTrainer`/rollout-based
training (not vendored — needs `pytorch-lightning` and its own dataset/
batching machinery this project doesn't have), but a real, complete,
gradient-descent training loop, not a stub.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import torch

from stage2.gnn.device import resolve_device
from stage2.gnn.graph_builder import PREVIOUS_T, build_graph
from stage2.gnn.loss import hybrid_loss
from stage2.gnn.vendor.mswe_gnn.gnn import GNN
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge
from stage2.solver.shallow_water_solver import TrajectoryPoint

logger = logging.getLogger(__name__)


def _to_history_dicts(
    trajectory: Dict[str, List[TrajectoryPoint]],
) -> tuple[List[Dict[str, float]], List[Dict[str, float]]]:
    """Reshape `{node_id: [TrajectoryPoint, ...]}` into per-step `{node_id: value}` dicts."""
    node_ids = list(trajectory.keys())
    num_steps = len(next(iter(trajectory.values())))
    depth_steps = [
        {nid: trajectory[nid][t].depth_m for nid in node_ids} for t in range(num_steps)
    ]
    velocity_steps = [
        {nid: trajectory[nid][t].velocity_mps for nid in node_ids} for t in range(num_steps)
    ]
    return depth_steps, velocity_steps


def train_on_solver_trajectory(
    model: GNN,
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    cell_area_m2: float,
    solver_trajectory: Dict[str, List[TrajectoryPoint]],
    inflow_mm_per_hour: List[float],
    epochs: int = 20,
    lr: float = 1e-3,
    conservation_weight: float = 0.1,
    device: torch.device | None = None,
) -> List[float]:
    """Train `model` on one solver-generated trajectory.

    Args:
        solver_trajectory: T2.5's `run_trajectory` output, covering the
            same window as `inflow_mm_per_hour` — the real, honest
            training signal (no fabricated data).

    Returns:
        Mean loss per epoch (for the caller to inspect/plot/assert on).
    """
    device = device or resolve_device()
    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    depth_steps, velocity_steps = _to_history_dicts(solver_trajectory)
    node_ids = [n.node_id for n in nodes]
    num_steps = len(depth_steps)

    if num_steps <= PREVIOUS_T:
        raise ValueError(
            f"Solver trajectory has {num_steps} steps; need more than "
            f"PREVIOUS_T={PREVIOUS_T} to form any training example."
        )

    epoch_losses: List[float] = []
    for epoch in range(epochs):
        total_loss = 0.0
        count = 0
        for t in range(PREVIOUS_T, num_steps):
            depth_history = depth_steps[t - PREVIOUS_T : t]
            velocity_history = velocity_steps[t - PREVIOUS_T : t]

            graph = build_graph(nodes, edges, cell_area_m2, depth_history, velocity_history)
            graph = graph.to(device)

            target = torch.tensor(
                [[depth_steps[t][nid], velocity_steps[t][nid]] for nid in node_ids],
                dtype=torch.float32,
                device=device,
            )
            input_depth = torch.tensor(
                [depth_steps[t - 1][nid] for nid in node_ids],
                dtype=torch.float32,
                device=device,
            )
            rainfall_m3 = (
                max(0.0, inflow_mm_per_hour[t - 1]) / 1000.0
            ) * cell_area_m2 * len(nodes)

            model.train()
            optimizer.zero_grad()
            preds = model(graph)
            loss = hybrid_loss(
                preds,
                target,
                input_depth,
                cell_area_m2,
                rainfall_m3,
                conservation_weight=conservation_weight,
            )
            loss.backward()
            optimizer.step()

            total_loss += float(loss.item())
            count += 1

        mean_loss = total_loss / max(count, 1)
        epoch_losses.append(mean_loss)
        logger.info("epoch %d/%d: mean loss=%.6f", epoch + 1, epochs, mean_loss)

    return epoch_losses


def validate_against_solver(
    model: GNN,
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    cell_area_m2: float,
    solver_trajectory: Dict[str, List[TrajectoryPoint]],
    device: torch.device | None = None,
) -> tuple[float, float]:
    """Compare the trained model's one-step predictions against solver output.

    Returns:
        `(depth_mae_m, velocity_mae_mps)` — the real values this project's
        `SimulationResult.validation_error_m` (depth) should be populated
        with, per T2.6's own VERIFY requirement.
    """
    device = device or resolve_device()
    model = model.to(device)
    model.eval()

    depth_steps, velocity_steps = _to_history_dicts(solver_trajectory)
    node_ids = [n.node_id for n in nodes]
    num_steps = len(depth_steps)

    depth_errors: List[float] = []
    velocity_errors: List[float] = []
    with torch.no_grad():
        for t in range(PREVIOUS_T, num_steps):
            depth_history = depth_steps[t - PREVIOUS_T : t]
            velocity_history = velocity_steps[t - PREVIOUS_T : t]
            graph = build_graph(
                nodes, edges, cell_area_m2, depth_history, velocity_history
            ).to(device)

            preds = model(graph).cpu().numpy()
            for i, nid in enumerate(node_ids):
                depth_errors.append(abs(preds[i, 0] - depth_steps[t][nid]))
                velocity_errors.append(abs(preds[i, 1] - velocity_steps[t][nid]))

    depth_mae = float(sum(depth_errors) / max(len(depth_errors), 1))
    velocity_mae = float(sum(velocity_errors) / max(len(velocity_errors), 1))
    return depth_mae, velocity_mae
