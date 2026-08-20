"""Build PyG `Data` graphs from this project's mesh + trajectory history (T2.6).

FEATURE SHAPES — CONFIRMED AGAINST THE REAL REPO, NOT ASSUMED
---------------------------------------------------------------------
`config.yaml` (fetched in-session): node features enabled are `area` and
`DEM` (elevation); `previous_t=3` (three previous timesteps as dynamic
input); edge features enabled are `edge_length` only. `BaseFloodModel`
(vendored `models.py`) confirms `NUM_WATER_VARS = 2` (`out_dim = 2` —
depth and velocity, this project's two tracked hazard quantities).

Cross-checked against the real downloaded checkpoint's actual tensor
shapes (`K4_F64.h5`, inspected directly with `torch.load` this session):
`dynamic_node_encoder.0.weight` is `(64, 6)` — matches `previous_t(3) *
out_dim(2) = 6` exactly; `static_node_encoder.0.weight` is `(64, 3)` —
matches 2 declared static features (area, DEM) plus 1 auto-added by
`GNN`'s own `with_WL` handling (confirmed in `gnn.py`'s `forward`: it
appends a water-level column to `x_s` when `with_WL=True`).

So `graph.x`'s columns, per node, are exactly:
    [elevation_m, area_m2,
     depth_t-3, velocity_t-3, depth_t-2, velocity_t-2, depth_t-1, velocity_t-1]
(2 static + 6 dynamic = 8 total; `GNN(num_node_features=8, ...)` derives
static_node_features = 8 - 6 + 1(with_WL) = 3 internally, matching the
checkpoint exactly.) `edge_attr` is `[distance_m]` only, matching the real
confirmed config (`edge_length` was the only edge feature enabled) — this
project's `MeshEdge.slope` is NOT fed to the GNN (elevation is already a
node feature; the model learns slope-like effects from node-pair
differences itself, matching how the real architecture is actually used).
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import torch
from torch_geometric.data import Data

from stage2.gnn.errors import InsufficientHistoryError
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge

PREVIOUS_T = 3  # confirmed real value, config.yaml
OUT_DIM = 2  # confirmed real value, BaseFloodModel.NUM_WATER_VARS (depth, velocity)
STATIC_FEATURES_DECLARED = 2  # elevation_m, area_m2 (with_WL adds a 3rd internally)


def build_edge_tensors(
    edges: List[MeshEdge], index_of: Dict[str, int]
) -> tuple[torch.Tensor, torch.Tensor]:
    """Build `(edge_index, edge_attr)` for PyG, both directions per `MeshEdge`.

    PyG message passing needs both (a->b) and (b->a) for symmetric
    exchange (`SWEGNN.forward` scatters onto `col` in one direction per
    row of `edge_index`) — each undirected `MeshEdge` becomes two directed
    PyG edges, both carrying the same real `distance_m`.
    """
    src: List[int] = []
    dst: List[int] = []
    attr: List[List[float]] = []
    for edge in edges:
        a, b = index_of[edge.node_id_a], index_of[edge.node_id_b]
        src += [a, b]
        dst += [b, a]
        attr += [[edge.distance_m], [edge.distance_m]]
    edge_index = torch.tensor([src, dst], dtype=torch.long)
    edge_attr = torch.tensor(attr, dtype=torch.float32)
    return edge_index, edge_attr


def build_graph(
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    cell_area_m2: float,
    depth_history: Sequence[Dict[str, float]],
    velocity_history: Sequence[Dict[str, float]],
) -> Data:
    """Build one input `Data` graph from `PREVIOUS_T` timesteps of history.

    Args:
        depth_history, velocity_history: each a sequence of exactly
            `PREVIOUS_T` `{node_id: value}` dicts, oldest first (index 0 =
            t-3, ..., index -1 = t-1) — the model predicts state at t.

    Raises:
        InsufficientHistoryError: if fewer than `PREVIOUS_T` timesteps are
            given. Never zero-pads missing history.
    """
    if len(depth_history) != PREVIOUS_T or len(velocity_history) != PREVIOUS_T:
        raise InsufficientHistoryError(
            f"build_graph needs exactly {PREVIOUS_T} previous timesteps of "
            f"depth/velocity history; got {len(depth_history)}/"
            f"{len(velocity_history)}."
        )

    node_ids = [n.node_id for n in nodes]
    index_of = {node_id: i for i, node_id in enumerate(node_ids)}

    static = np.array(
        [[n.elevation_m, cell_area_m2] for n in nodes], dtype=np.float32
    )
    dynamic_cols = []
    for depth_t, velocity_t in zip(depth_history, velocity_history):
        dynamic_cols.append([depth_t.get(nid, 0.0) for nid in node_ids])
        dynamic_cols.append([velocity_t.get(nid, 0.0) for nid in node_ids])
    dynamic = np.array(dynamic_cols, dtype=np.float32).T  # (num_nodes, PREVIOUS_T*OUT_DIM)

    x = torch.tensor(np.concatenate([static, dynamic], axis=1), dtype=torch.float32)
    edge_index, edge_attr = build_edge_tensors(edges, index_of)

    return Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
