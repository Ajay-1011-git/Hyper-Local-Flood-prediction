"""Single-scale SWE-GNN: build, train, and run inference (T2.6, amended 2026-08-20).

DECISION LOCKED (per the amendment): single-scale `GNN(type_GNN="SWEGNN")`,
randomly initialized, trained from scratch on T2.5's solver-generated
trajectories — no pretrained checkpoint exists for this architecture (the
only downloadable weights, `results/Pareto_front/models/K4_F64.h5`,
confirmed by directly loading and inspecting its `state_dict` this
session, are for the multiscale `MSGNN` variant: it has an `intra_scale_gnn`
submodule and a 7-layer `gnn_processor`, both multiscale-only structures
this project's mesh doesn't build). Not attempted here, per the amendment.

HYPERPARAMETERS — the real published defaults, confirmed from `config.yaml`
---------------------------------------------------------------------------
`hid_features=64`, `K=4` (both fetched directly from the real repo's
`config.yaml` this session). `n_GNN_layers` is left at `GNN.__init__`'s
own published default (2) — `config.yaml`'s value describes the multiscale
Pareto-front sweep specifically and doesn't state a single-scale
`n_GNN_layers`, so the class's own default is used rather than guessed.

GHOST-CELL EQUIVALENT FOR THIS ARCHITECTURE
------------------------------------------------
The vendored `GNN`/`SWEGNN` classes (single-scale) have no separate
ghost-cell array like `MSGNN`'s `data.node_BC`/`data.BC` — boundary
conditions are real input, injected by overwriting specific nodes'
dynamic (depth/velocity) history columns before the forward pass, then
letting message-passing propagate their influence. `inject_boundary`
below implements this: it's this architecture's real equivalent
mechanism, not an assumption that MSGNN's mechanism transfers unchanged.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Sequence

import torch
from torch_geometric.data import Data

from stage2.gnn.device import resolve_device
from stage2.gnn.graph_builder import OUT_DIM, PREVIOUS_T, STATIC_FEATURES_DECLARED, build_graph
from stage2.gnn.vendor.mswe_gnn.gnn import GNN
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge

logger = logging.getLogger(__name__)

HID_FEATURES = 64  # confirmed real value, config.yaml
K_HOPS = 4  # confirmed real value, config.yaml
NUM_NODE_FEATURES = STATIC_FEATURES_DECLARED + PREVIOUS_T * OUT_DIM  # 2 + 6 = 8
NUM_EDGE_FEATURES = 1  # distance_m only, matches config.yaml's "edge_length only"


def build_model(device: torch.device | None = None) -> GNN:
    """Construct a randomly-initialized single-scale SWE-GNN.

    No pretrained weights are loaded — see module docstring for why.
    """
    device = device or resolve_device()
    model = GNN(
        num_node_features=NUM_NODE_FEATURES,
        num_edge_features=NUM_EDGE_FEATURES,
        hid_features=HID_FEATURES,
        K=K_HOPS,
        type_GNN="SWEGNN",
        with_WL=True,
        device=str(device),
    )
    return model.to(device)


def predict_next_state(
    model: GNN, graph: Data, device: torch.device
) -> torch.Tensor:
    """One forward pass: returns `[num_nodes, 2]` (depth_m, velocity_mps)."""
    model.eval()
    with torch.no_grad():
        output: torch.Tensor = model(graph.to(device))
    return output


def inject_boundary(
    depth_history: List[Dict[str, float]],
    velocity_history: List[Dict[str, float]],
    node_id: str,
    depth_m: float,
    velocity_mps: float,
) -> None:
    """Overwrite the most recent history entry for `node_id` (in place).

    This architecture's real equivalent of a ghost-cell boundary update
    (see module docstring): forces one node's most recent input state to
    a known value (from a `DownscaledForecastField` member or a live
    `SensorReading`) before the next `build_graph`/forward call, letting
    message-passing propagate its influence to neighbors on the next step.
    """
    depth_history[-1][node_id] = depth_m
    velocity_history[-1][node_id] = velocity_mps
