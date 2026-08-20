"""Numerical 2D shallow-water solver (T2.5) — training-data generator + fallback.

METHOD: LOCAL INERTIAL APPROXIMATION, A DELIBERATE, DOCUMENTED CHOICE
---------------------------------------------------------------------------
Implements the local inertial (diffusive-wave) formulation of the 2D
shallow-water / Saint-Venant equations — Bates, Horritt & Fewtrell (2010),
"A simple inertial formulation of the shallow water equations for
efficient two-dimensional flood inundation modelling", Journal of
Hydrology 387(1-2). This is a real, published, widely-used method (the
basis of LISFLOOD-FP and similar operational urban flood models), not an
invented simplification: it drops the advective momentum terms from full
dynamic SWE (valid for the sub-critical, gently-varying flows typical of
urban pluvial flooding) in exchange for much larger stable timesteps and
guaranteed mass conservation — directly matching this project's own
stated real-time/single-laptop performance requirement (TRD §6) far
better than a full 2D Godunov/Riemann-solver scheme would, at the cost of
not resolving hydraulic jumps or supercritical flow. Flagged here as an
engineering decision, not silently substituted for "the" Saint-Venant
solver the task prompt names generically.

DISCRETIZATION — ON THIS PROJECT'S GRAPH, NOT A REGULAR STENCIL
---------------------------------------------------------------------
Cells are `ComputationalMeshNode`s (T2.4), edges are `MeshEdge`s carrying
real `distance_m` and `slope`. For each edge (i, j) not touching a wall
node, the discharge update (Bates et al. 2010, eq. 11, explicit-in-time
form used here for a plain Python/NumPy implementation, no implicit solve):

    Q_new = (Q_old - g*A*dt*Sw) / (1 + g*dt*n^2*|Q_old| / (A * R^(4/3)))

  where Sw = water-surface slope = ((h_i+z_i) - (h_j+z_j)) / distance_m,
  A = flow cross-section = h_flow * edge_width_m (h_flow = the larger of
  the two cells' depths, the standard upwind convention — flow can't
  exceed what's actually available upstream), R = hydraulic radius,
  approximated as h_flow (valid for flow much wider than it is deep, true
  for sheet flow over a grid cell face).

`edge_width_m` = the grid resolution (cell face width for a regular grid)
— passed in explicitly, not re-derived from geometry the mesh doesn't
carry.

MANNING'S N — A STATED DEFAULT, NOT A VERIFIED VALUE FOR THIS SITE
---------------------------------------------------------------------
`DEFAULT_MANNINGS_N = 0.035` (a standard textbook value for mixed
urban/paved surfaces) is a conservative placeholder, same convention as
this project's other unverified thresholds (e.g. T1A.7's station-proximity
default) — FLAG FOR HUMAN REVIEW, not independently verified for this
specific site.

RAINFALL FORCING
---------------------
`inflow_mm_per_hour` (from a `DownscaledForecastField` member's
trajectory) is applied as direct recharge onto every non-wall cell each
step — matches how rainfall actually reaches an urban flood domain (falls
uniformly across open ground), not a single point-source inflow. Wall
cells (buildings) never accumulate depth — real buildings shed rainfall,
and they are the no-flow obstacles this project's mesh already marks them
as (CLAUDE.md ground truth).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

from stage2.shared.contracts import ComputationalMeshNode, MeshEdge
from stage2.solver.errors import SolverInstabilityError

GRAVITY_M_S2 = 9.81
DEFAULT_MANNINGS_N = 0.035  # FLAG FOR HUMAN REVIEW -- see module docstring
_MIN_FLOW_DEPTH_M = 1e-4  # below this, an edge is treated as dry (no flux)


@dataclass
class TrajectoryPoint:
    """One node's hydraulic state at one output timestep."""

    hour: float
    depth_m: float
    velocity_mps: float
    rate_of_rise_m_per_hr: float


def _cfl_stable_dt(
    edge_distances_m: np.ndarray, max_depth_m: float, alpha: float = 0.4
) -> float:
    """A conservative explicit stability bound for the local inertial scheme.

    Bates et al. (2010) note the scheme is stable for much larger
    timesteps than a full dynamic solver, but an explicit update still
    needs a real CFL-type bound to stay stable: dt <= alpha * dx / sqrt(g*h).
    `alpha=0.4` is a conservative safety factor (the paper's own
    experiments use values up to ~0.7-1.0); kept smaller here since this
    is a first, unvalidated implementation. FLAG FOR HUMAN REVIEW if this
    proves too conservative (slow) or insufficiently stable in practice.
    """
    if max_depth_m <= _MIN_FLOW_DEPTH_M or edge_distances_m.size == 0:
        return 1.0  # nothing flowing yet; timestep is unconstrained
    min_dx = float(edge_distances_m.min())
    return alpha * min_dx / math.sqrt(GRAVITY_M_S2 * max_depth_m)


def run_trajectory(
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    inflow_mm_per_hour: Sequence[float],
    edge_width_m: float,
    hours_per_step: float = 1.0,
    mannings_n: float = DEFAULT_MANNINGS_N,
    output_node_ids: Sequence[str] | None = None,
) -> Dict[str, List[TrajectoryPoint]]:
    """Run one shallow-water trajectory over `nodes`/`edges`.

    Args:
        inflow_mm_per_hour: one rainfall-recharge rate per output step
            (e.g. from one `DownscaledForecastField` member's trajectory).
        edge_width_m: flow cross-section width per edge — the grid
            resolution for this project's regular-grid mesh.
        hours_per_step: real time each entry of `inflow_mm_per_hour`
            covers; the solver subdivides this into stable internal
            sub-steps (see `_cfl_stable_dt`) and reports output only at
            each full step boundary.
        output_node_ids: which nodes to return trajectories for (default:
            all). Internal computation always covers every node/edge —
            this only limits what's returned, for callers that only need
            a few nodes (e.g. tests).

    Returns:
        `{node_id: [TrajectoryPoint, ...]}` for every requested node,
        covering hours `hours_per_step, 2*hours_per_step, ...`.

    Raises:
        SolverInstabilityError: if depth ever goes negative or non-finite
            — never silently clamped and continued.
    """
    node_ids = [n.node_id for n in nodes]
    index_of = {node_id: i for i, node_id in enumerate(node_ids)}
    n_nodes = len(nodes)

    elevation = np.array([n.elevation_m for n in nodes], dtype=float)
    is_wall = np.array([n.is_wall_node for n in nodes], dtype=bool)
    cell_area_m2 = edge_width_m**2

    edge_a = np.array([index_of[e.node_id_a] for e in edges], dtype=int)
    edge_b = np.array([index_of[e.node_id_b] for e in edges], dtype=int)
    edge_distance = np.array([e.distance_m for e in edges], dtype=float)
    # An edge is open only if neither endpoint is a wall node -- buildings
    # are genuine no-flow obstacles (CLAUDE.md ground truth), not just
    # cells that happen to stay dry.
    edge_open = ~(is_wall[edge_a] | is_wall[edge_b])

    depth = np.zeros(n_nodes, dtype=float)
    discharge = np.zeros(len(edges), dtype=float)
    prev_depth_for_rate = depth.copy()

    requested = list(output_node_ids) if output_node_ids is not None else node_ids
    output: Dict[str, List[TrajectoryPoint]] = {node_id: [] for node_id in requested}

    elapsed_hours = 0.0
    for step_hour_rate in inflow_mm_per_hour:
        elapsed_hours += hours_per_step
        step_seconds_remaining = hours_per_step * 3600.0
        recharge_m_per_s = (max(0.0, step_hour_rate) / 1000.0) / 3600.0

        while step_seconds_remaining > 0:
            max_depth = float(depth.max()) if n_nodes else 0.0
            sub_dt = min(
                _cfl_stable_dt(edge_distance[edge_open], max_depth),
                step_seconds_remaining,
            )
            sub_dt = max(sub_dt, 1e-6)

            if edge_open.any():
                h_a = depth[edge_a]
                h_b = depth[edge_b]
                z_a = elevation[edge_a]
                z_b = elevation[edge_b]
                h_flow = np.maximum(h_a, h_b)
                flowing = edge_open & (h_flow > _MIN_FLOW_DEPTH_M)

                water_surface_slope = np.zeros_like(h_a)
                water_surface_slope[flowing] = (
                    (h_a[flowing] + z_a[flowing]) - (h_b[flowing] + z_b[flowing])
                ) / edge_distance[flowing]

                area = h_flow * edge_width_m
                hydraulic_radius = h_flow  # wide-shallow-flow approximation

                # Sign convention: discharge > 0 means flow from node a to
                # node b (matches the net_flux application below: positive
                # discharge depletes a's volume and fills b's). Water must
                # flow from high head to low head, so a positive
                # water_surface_slope (head_a > head_b, a is higher) must
                # push discharge more positive (more a->b flow) -- hence
                # "+", not "-". (An earlier version used "-" and a real
                # test caught it: water was flowing uphill, confirmed by
                # test_water_flows_downhill_from_higher_elevation initially
                # failing with the low end nearly dry and the high end
                # flooded.)
                numerator = discharge + GRAVITY_M_S2 * area * sub_dt * water_surface_slope
                denominator = 1.0 + GRAVITY_M_S2 * sub_dt * mannings_n**2 * np.abs(
                    discharge
                ) / np.where(flowing, area * hydraulic_radius ** (4.0 / 3.0), 1.0)
                new_discharge = np.where(flowing, numerator / denominator, 0.0)

                # Flux limiting: an edge can't drain more water this
                # sub-step than the upstream cell actually has.
                max_volume_a = h_a * cell_area_m2
                max_volume_b = h_b * cell_area_m2
                max_flow_volume = np.minimum(max_volume_a, max_volume_b) / max(
                    sub_dt, 1e-9
                )
                new_discharge = np.clip(new_discharge, -max_flow_volume, max_flow_volume)
                discharge = new_discharge
            # else: no open edges at all (fully walled mesh) -- discharge stays 0.

            net_flux = np.zeros(n_nodes, dtype=float)
            np.add.at(net_flux, edge_a, -discharge)
            np.add.at(net_flux, edge_b, discharge)

            depth = depth + sub_dt * net_flux / cell_area_m2
            depth[~is_wall] += recharge_m_per_s * sub_dt
            depth[is_wall] = 0.0  # buildings never accumulate standing water

            if not np.all(np.isfinite(depth)) or np.any(depth < -1e-9):
                raise SolverInstabilityError(
                    f"Non-finite or negative depth at t={elapsed_hours:.3f}h "
                    f"(min depth={float(depth.min()):.6g}); sub_dt={sub_dt:.6g}s. "
                    "Not continuing with an unstable result."
                )
            depth = np.maximum(depth, 0.0)

            step_seconds_remaining -= sub_dt

        rate_of_rise = (depth - prev_depth_for_rate) / hours_per_step
        prev_depth_for_rate = depth.copy()

        for node_id in requested:
            i = index_of[node_id]
            adjacent = (edge_a == i) | (edge_b == i)
            if adjacent.any() and depth[i] > _MIN_FLOW_DEPTH_M:
                velocity = float(
                    np.mean(np.abs(discharge[adjacent]))
                    / (depth[i] * edge_width_m)
                )
            else:
                velocity = 0.0
            output[node_id].append(
                TrajectoryPoint(
                    hour=elapsed_hours,
                    depth_m=float(depth[i]),
                    velocity_mps=velocity,
                    rate_of_rise_m_per_hr=float(rate_of_rise[i]),
                )
            )

    return output


def total_volume_m3(nodes: List[ComputationalMeshNode], depth_by_node: Dict[str, float], edge_width_m: float) -> float:
    """Total water volume across every (non-wall) node, for a mass-balance check."""
    cell_area_m2 = edge_width_m**2
    return sum(
        depth_by_node.get(n.node_id, 0.0) * cell_area_m2
        for n in nodes
        if not n.is_wall_node
    )
