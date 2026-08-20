"""Ensemble propagation (T2.7): run every `DownscaledForecastField` member
through T2.6's trained GNN, returning only aggregated `NodeState` statistics.

WHY THE GNN, NOT T2.5'S SOLVER, DRIVES PRODUCTION ENSEMBLE RUNS
---------------------------------------------------------------------
`SimulationResult.validation_error_m` exists specifically to record "the
fine-tuned GNN's depth/velocity MAE against the solver" (see
`backend/shared/contracts.py`'s comment on that field) -- a field that
would be meaningless if `SimulationResult` were itself solver-produced.
T2.5's solver remains the real fallback ("capable of producing full
SimulationResult output if the neural model isn't ready" -- T2.5's own
doc) and the training-data generator (T2.6), but T2.7's actual production
path is GNN inference: it's the fast surrogate this project needs to run
50-150 members in real time on a single laptop (TRD §6), which repeatedly
re-running the numerical solver could not do.

HOW RAINFALL FORCING REACHES THE GNN -- A STATED ASSUMPTION, NOT CONFIRMED
---------------------------------------------------------------------------
The vendored single-scale `GNN`/`SWEGNN` has no rainfall/inflow input
feature (confirmed in `graph_builder.py`'s docstring: node features are
only elevation/area (static) + previous depth/velocity (dynamic); edge
features are distance only). `gnn/model.py`'s `inject_boundary` is this
architecture's real equivalent mechanism for injecting external forcing:
overwrite a node's most recent dynamic-history entry before the next
forward pass, letting message-passing propagate its effect. This module
applies that SAME mechanism to EVERY non-wall node each step, adding the
step's real rainfall depth (`inflow_mm / 1000`, matching T2.5's own
uniform-recharge convention: "rainfall... applied as direct recharge onto
every non-wall cell each step") to that node's most recent depth-history
entry before predicting the next state. This is a reasonable, physically
motivated interpretation consistent with `inject_boundary`'s stated
purpose and T2.5's own rainfall-application convention -- but the real
`RBTV1/mSWE-GNN` repo's own production inference pipeline's rainfall-
forcing convention was NOT independently confirmed this session (only its
training-time feature/edge shapes were, per `graph_builder.py`). FLAG FOR
HUMAN REVIEW if a different convention is later confirmed against the
real repo's inference code.

ROLLOUT IS AUTOREGRESSIVE, SEEDED FROM A DRY START
---------------------------------------------------------------------
Each member's trajectory is rolled out starting from `PREVIOUS_T` all-zero
depth/velocity timesteps (a physically valid initial condition for this
project's site -- no baseline standing water before a rainfall event
begins). Each step's prediction becomes part of the input history for the
next step (the model's own predictions feed forward), not re-seeded from
solver ground truth -- this is the real, honest inference-time behaviour
this project needs (ground-truth history won't exist at inference time).
Wall nodes are forced to zero depth/velocity after every prediction
(buildings are genuine no-flow obstacles, structurally enforced here the
same way T2.5's solver enforces it, rather than trusting the model to
have learned it perfectly).

AGGREGATION: MEAN/MIN/MAX EVERYTHING EXCEPT `rate_of_rise`
---------------------------------------------------------------------
`NodeState.rate_of_rise` is a single field, not split into
mean/min/max (per that field's own contract comment, citing stage3's
singular `DamageRankEntry.peak_rate_of_rise`) -- computed here as the
change in MEAN depth from the previous hour to this hour (the
ensemble's typical/expected rate, not the fastest-rising member's).
`ensemble_agreement_fraction` is the real fraction of members whose
predicted depth at this node/hour exceeds `hazard_threshold_m` --
never a placeholder (CLAUDE.md/stage4 ground truth on that field).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import torch

from stage2.gnn.device import resolve_device
from stage2.gnn.graph_builder import PREVIOUS_T, build_graph
from stage2.gnn.model import predict_next_state
from stage2.gnn.vendor.mswe_gnn.gnn import GNN
from stage2.shared.contracts import (
    ComputationalMeshNode,
    DownscaledForecastField,
    MeshEdge,
    NodeState,
    SimulationResult,
)


def _rollout_member(
    model: GNN,
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    cell_area_m2: float,
    trajectory: List[tuple[int, float]],  # (hour, inflow_mm), sorted by hour
    device: torch.device,
) -> tuple[Dict[str, Dict[int, float]], Dict[str, Dict[int, float]]]:
    """Autoregressively roll out one ensemble member's real inflow trajectory.

    Returns `(depth_by_node_by_hour, velocity_by_node_by_hour)`.
    """
    node_ids = [n.node_id for n in nodes]
    is_wall = [n.is_wall_node for n in nodes]

    depth_history: List[Dict[str, float]] = [
        {nid: 0.0 for nid in node_ids} for _ in range(PREVIOUS_T)
    ]
    velocity_history: List[Dict[str, float]] = [
        {nid: 0.0 for nid in node_ids} for _ in range(PREVIOUS_T)
    ]

    depth_out: Dict[str, Dict[int, float]] = {nid: {} for nid in node_ids}
    velocity_out: Dict[str, Dict[int, float]] = {nid: {} for nid in node_ids}

    for hour, inflow_mm in trajectory:
        recharge_m = max(0.0, inflow_mm) / 1000.0
        latest_depth = depth_history[-1]
        depth_history[-1] = {
            nid: (0.0 if is_wall[i] else latest_depth[nid] + recharge_m)
            for i, nid in enumerate(node_ids)
        }

        graph = build_graph(
            nodes, edges, cell_area_m2, depth_history, velocity_history
        ).to(device)
        preds = predict_next_state(model, graph, device)
        pred_depth = preds[:, 0].clamp(min=0.0)
        pred_velocity = preds[:, 1]

        new_depth: Dict[str, float] = {}
        new_velocity: Dict[str, float] = {}
        for i, nid in enumerate(node_ids):
            d = 0.0 if is_wall[i] else float(pred_depth[i])
            v = 0.0 if is_wall[i] else float(pred_velocity[i])
            new_depth[nid] = d
            new_velocity[nid] = v
            depth_out[nid][hour] = d
            velocity_out[nid][hour] = v

        depth_history = depth_history[1:] + [new_depth]
        velocity_history = velocity_history[1:] + [new_velocity]

    return depth_out, velocity_out


def run_ensemble(
    forecast: DownscaledForecastField,
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    model: GNN,
    cell_area_m2: float,
    hazard_threshold_m: float,
    validation_error_m: float,
    simulation_id: str,
    device: Optional[torch.device] = None,
) -> SimulationResult:
    """Run every member of `forecast` through `model`, returning aggregated `NodeState`s.

    Args:
        hazard_threshold_m: real depth (m) `ensemble_agreement_fraction` is
            computed against -- caller-supplied, never a silently
            fabricated default (see module docstring).
        validation_error_m: the model's own already-computed accuracy
            (T2.6's `validate_against_solver` depth MAE against the
            solver on held-out data) -- NOT recomputed per ensemble run.
        simulation_id: caller-assigned identifier (T2.9's route owns
            idempotency/ID generation; this function never invents one).

    Raises:
        ValueError: if `forecast.members` is empty (nothing to aggregate).
    """
    if not forecast.members:
        raise ValueError("forecast.members is empty -- nothing to run an ensemble over.")

    device = device or resolve_device()
    node_ids = [n.node_id for n in nodes]
    building_id_by_node = {n.node_id: n.building_id for n in nodes}

    per_member_depth: Dict[int, Dict[str, Dict[int, float]]] = {}
    per_member_velocity: Dict[int, Dict[str, Dict[int, float]]] = {}
    for member in forecast.members:
        traj = sorted((tv.hour, tv.inflow_mm) for tv in member.trajectory)
        depth_by_node, velocity_by_node = _rollout_member(
            model, nodes, edges, cell_area_m2, traj, device
        )
        per_member_depth[member.member_id] = depth_by_node
        per_member_velocity[member.member_id] = velocity_by_node

    member_ids = list(per_member_depth.keys())
    hours = sorted({h for tv in forecast.members[0].trajectory for h in [tv.hour]})

    node_states: List[NodeState] = []
    prev_mean_depth: Dict[str, float] = {nid: 0.0 for nid in node_ids}
    max_depth_overall = 0.0
    hours_any_exceed_threshold = 0

    for hour in hours:
        hour_any_exceed = False
        for nid in node_ids:
            depths = [per_member_depth[m][nid][hour] for m in member_ids]
            velocities = [per_member_velocity[m][nid][hour] for m in member_ids]

            depth_mean = sum(depths) / len(depths)
            velocity_mean = sum(velocities) / len(velocities)
            rate_of_rise = (depth_mean - prev_mean_depth[nid]) / 1.0  # 1 hour per step
            exceed_count = sum(1 for d in depths if d > hazard_threshold_m)
            if exceed_count > 0:
                hour_any_exceed = True
            max_depth_overall = max(max_depth_overall, max(depths))

            node_states.append(
                NodeState(
                    node_id=nid,
                    hour=hour,
                    depth_mean_m=depth_mean,
                    depth_min_m=min(depths),
                    depth_max_m=max(depths),
                    velocity_mean_mps=velocity_mean,
                    velocity_min_mps=min(velocities),
                    velocity_max_mps=max(velocities),
                    rate_of_rise=rate_of_rise,
                    ensemble_agreement_fraction=exceed_count / len(depths),
                    building_id=building_id_by_node[nid],
                )
            )
            prev_mean_depth[nid] = depth_mean

        if hour_any_exceed:
            hours_any_exceed_threshold += 1

    envelope = {
        "max_depth_m": max_depth_overall,
        "hours_any_node_exceeds_threshold": hours_any_exceed_threshold,
        "total_hours": len(hours),
        "member_count": len(member_ids),
    }

    return SimulationResult(
        simulation_id=simulation_id,
        site_id=forecast.site_id,
        source_forecast_id=forecast.source_forecast_id,
        generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=hazard_threshold_m,
        validation_error_m=validation_error_m,
        node_states=node_states,
        envelope=envelope,
    )
