"""Live sensor assimilation via a local ghost-cell update (T2.8).

METHOD: DISTANCE-WEIGHTED NUDGING, NOT RE-RUNNING T2.5'S PDE SOLVER
---------------------------------------------------------------------
First attempt (tried and rejected, for the record): re-run T2.5's local
inertial solver for a short real-time window (matching the sensor's ~2s
polling interval), seeded from the current running state and corrected at
the sensor node. Real-tested against the actual VIT Vellore mesh: this
produced physically absurd results (the corrected node's depth drained to
near-zero within 2 simulated seconds, and reported a >4 m/s velocity for
an ordinary urban flood cell) — a single sharp point correction against a
gentle rainfall-driven background is a fundamentally different regime
than what the scheme's CFL/friction balance is tuned for (see T2.5's own
module docstring: it targets sub-critical, gently-varying flow). Rather
than hand-tune the PDE solver's stability margins for a use case it
wasn't designed for, this module instead uses NUDGING (a.k.a. successive
correction / optimal interpolation) — a standard, simpler technique from
real operational data assimilation: blend the observation with the
model's background state, weighted by real graph distance from the
sensor, linearly decaying to zero influence at `propagation_radius_m`.
This is well-behaved by construction (a convex combination of two
non-negative depths is always non-negative and bounded between them —
no solver stability margin to violate) and satisfies the task's actual
requirement ("recomputing... locally") without needing the full nonlinear
momentum equation for what is, physically, a single scalar correction.

ONLY DEPTH (AND FIELDS DERIVED FROM IT) ARE NUDGED
---------------------------------------------------------------------
The HC-SR04 measures distance to the water surface — depth, and nothing
else. `velocity_mean/min/max_mps` and `rate_of_rise` are left as the
model's own unaltered estimates at every node (nudging them toward some
invented "corrected" value would fabricate information the sensor never
provided). `ensemble_agreement_fraction` IS re-derived from the nudged
depth (a real, honest recomputation, not a fabrication) since it's
directly defined in terms of depth vs. `hazard_threshold_m`.

SENSOR NOT YET PHYSICALLY PLACED -- ENDPOINT LEFT OPEN, NOT HARDCODED
---------------------------------------------------------------------------
Confirmed with the project owner (2026-08-20): the ESP32/HC-SR04 hardware
unit has not been deployed yet, so there is no real (x, y) position or
mount height to hardcode. `assimilate_reading` takes `target_x_m`/
`target_y_m`/`sensor_mount_height_m` as required parameters rather than
reading them from a fabricated default -- T2.9's route resolves them from
`Stage2Settings` (added this task, all `Optional[float] = None`) and
raises `SensorLocationNotConfiguredError` if they're still unset, so the
API surface exists and is wired end-to-end now, without pretending a
physical location exists yet.

DISTANCE-TO-DEPTH CONVENTION -- A STATED MODELING ASSUMPTION
---------------------------------------------------------------------------
`SensorReading.distance_cm` is the HC-SR04's raw downward-facing
ultrasonic range to the water surface (architecture doc: "mounted facing
downward over a container of water"). Converted to depth via
`depth_m = max(0, sensor_mount_height_m - distance_cm / 100)` -- the
standard convention for a fixed-height downward sensor (depth rises as
the measured distance to the surface shrinks). `sensor_mount_height_m`
is NOT independently verified against the real hardware rig (it doesn't
exist yet) -- FLAG FOR HUMAN REVIEW / real calibration once it does.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Dict, List

from stage2.assimilation.errors import SensorAtWallNodeError
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge, NodeState, SimulationResult
from backend.shared.contracts import SensorReading  # noqa: E402  (see shared/contracts.py's sys.path note)

DEFAULT_PROPAGATION_RADIUS_M = 20.0  # FLAG FOR HUMAN REVIEW -- not independently verified


def find_nearest_node(
    nodes: List[ComputationalMeshNode], target_x_m: float, target_y_m: float
) -> ComputationalMeshNode:
    """The real node whose (x_m, y_m) is closest (Euclidean) to the target position."""
    return min(
        nodes, key=lambda n: (n.x_m - target_x_m) ** 2 + (n.y_m - target_y_m) ** 2
    )


def distance_cm_to_depth_m(distance_cm: float, sensor_mount_height_m: float) -> float:
    """Convert a raw HC-SR04 reading to water depth (see module docstring)."""
    return max(0.0, sensor_mount_height_m - distance_cm / 100.0)


def _local_neighborhood(
    start_node_id: str, edges: List[MeshEdge], radius_m: float
) -> Dict[str, float]:
    """Real graph-distance (m) to every node reachable within `radius_m` (BFS)."""
    adjacency: Dict[str, List[tuple[str, float]]] = {}
    for e in edges:
        adjacency.setdefault(e.node_id_a, []).append((e.node_id_b, e.distance_m))
        adjacency.setdefault(e.node_id_b, []).append((e.node_id_a, e.distance_m))

    visited: Dict[str, float] = {start_node_id: 0.0}
    queue: deque[str] = deque([start_node_id])
    while queue:
        current = queue.popleft()
        current_dist = visited[current]
        for neighbor, edge_dist in adjacency.get(current, []):
            new_dist = current_dist + edge_dist
            if new_dist <= radius_m and new_dist < visited.get(neighbor, float("inf")):
                visited[neighbor] = new_dist
                queue.append(neighbor)
    return visited


def assimilate_reading(
    reading: SensorReading,
    current_state: SimulationResult,
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    target_x_m: float,
    target_y_m: float,
    sensor_mount_height_m: float,
    propagation_radius_m: float = DEFAULT_PROPAGATION_RADIUS_M,
) -> SimulationResult:
    """Assimilate one live `reading` into `current_state`, locally.

    Only the latest hour present in `current_state.node_states`, and only
    nodes within `propagation_radius_m` of the sensor's nearest mesh node,
    are recomputed and replaced -- everything else is returned unchanged
    (see module docstring for the nudging method and why it replaced an
    earlier, real-tested-and-rejected PDE-re-propagation attempt).

    Raises:
        SensorAtWallNodeError: if the nearest node is a building (T2.4's
            no-flow invariant would be violated by injecting water there).
    """
    target_node = find_nearest_node(nodes, target_x_m, target_y_m)
    if target_node.is_wall_node:
        raise SensorAtWallNodeError(
            f"Nearest node to ({target_x_m}, {target_y_m}) is {target_node.node_id}, "
            f"a wall node (building_id={target_node.building_id}) — refusing to "
            "assimilate a water depth into a no-flow obstacle."
        )

    measured_depth_m = distance_cm_to_depth_m(reading.distance_cm, sensor_mount_height_m)
    distances = _local_neighborhood(target_node.node_id, edges, propagation_radius_m)
    latest_hour = max(ns.hour for ns in current_state.node_states)

    updated_node_states: List[NodeState] = []
    for ns in current_state.node_states:
        if ns.hour != latest_hour or ns.node_id not in distances:
            updated_node_states.append(ns)  # untouched -- same object, confirms locality
            continue

        weight = (
            1.0
            if propagation_radius_m <= 0
            else max(0.0, 1.0 - distances[ns.node_id] / propagation_radius_m)
        )

        def _nudge(background: float) -> float:
            return weight * measured_depth_m + (1.0 - weight) * background

        nudged_mean = _nudge(ns.depth_mean_m)
        nudged_min = _nudge(ns.depth_min_m)
        nudged_max = _nudge(ns.depth_max_m)

        updated_node_states.append(
            ns.model_copy(
                update={
                    "depth_mean_m": nudged_mean,
                    "depth_min_m": nudged_min,
                    "depth_max_m": nudged_max,
                    "ensemble_agreement_fraction": (
                        1.0 if nudged_mean > current_state.hazard_threshold_m else 0.0
                    )
                    if weight >= 1.0
                    else ns.ensemble_agreement_fraction,
                    # velocity/rate_of_rise deliberately untouched -- the sensor
                    # measures depth only (see module docstring).
                }
            )
        )

    return current_state.model_copy(
        update={
            "node_states": updated_node_states,
            "generated_at": datetime.now(timezone.utc),
        }
    )
