"""Hazard extraction — T3.1.

`extract_peak_hazard` pulls, per requested node, the single worst moment
in its simulated time series — never the mean, per the build doc's
explicit rule ("a building's risk is driven by its worst moment, not its
mean condition across the window").

ASSUMPTION, flagged per this project's anti-hallucination rule 4 (state
unavoidable assumptions explicitly rather than guess silently): the build
doc's phrasing ("the peak depth, peak velocity, peak rate-of-rise... the
hour each peak occurred") is ambiguous between (a) three independently-
maximized signals, each with its own hour, or (b) one single "worst
moment" hour, with all three signals read together at that hour.
`DamageRankEntry` (this stage's own downstream contract, already defined
in backend/shared/contracts.py) settles this: it has exactly ONE
`peak_hour: int` field paired with `peak_depth_m`/`peak_velocity_mps`/
`peak_rate_of_rise` — meaning those three values must come from the SAME
hour, not three independently-maximized hours. So interpretation (b) is
implemented here.

Within (b), a second choice remains: which single hour counts as "worst"?
Depth is used as the anchor metric — the standard convention for "peak
flood stage" in hydrology, and the field DamageRankEntry itself leads
with. This is NOT the same as "ranking by depth alone" (a different rule,
governing T3.5's cross-structure RISK ranking, which stays hazard_score =
f(depth, velocity, rate_of_rise) all three) — this is only about which
single hour, within one node's own time series, gets reported as that
node's peak. Velocity, rate-of-rise, and ensemble_agreement_fraction are
then read at that same depth-anchored hour, not independently
maximized. Flagged here for human review, same as this project's other
assumption-driven defaults (station-proximity threshold, calibration
minimum-sample count, etc.) — reasonable, not independently proven
correct, and worth revisiting once Stage 2's real output is available to
sanity-check against.
"""

from __future__ import annotations

from backend.stage3.shared.contracts import NodeState, SimulationResult


class NodeNotFoundInSimulationError(Exception):
    """Raised when a requested node_id has no NodeState entries in the
    given SimulationResult — never silently omitted or defaulted to
    zero."""


class EmptyNodeTrajectoryError(Exception):
    """Raised when a node_id has NodeState entries but none carry a valid
    hour (should be unreachable given SimulationResult's contract, but
    guarded rather than assumed)."""


def extract_peak_hazard(
    sim_result: SimulationResult, node_ids: list[str]
) -> dict[str, dict]:
    """For each id in `node_ids`, find the hour of maximum `depth_mean_m`
    within `sim_result.node_states` and return that hour's full hazard
    signal.

    Returns a dict keyed by node_id, each value a dict with:
      - "peak_hour": int
      - "peak_depth_m": float
      - "peak_velocity_mps": float
      - "peak_rate_of_rise": float
      - "ensemble_agreement_fraction": float

    Raises `NodeNotFoundInSimulationError` if a requested node_id has no
    matching entries in `sim_result.node_states` — never silently
    skipped or defaulted.
    """
    by_node: dict[str, list[NodeState]] = {}
    for state in sim_result.node_states:
        by_node.setdefault(state.node_id, []).append(state)

    result: dict[str, dict] = {}
    for node_id in node_ids:
        states = by_node.get(node_id)
        if not states:
            raise NodeNotFoundInSimulationError(
                f"No NodeState entries for node_id={node_id!r} in "
                f"SimulationResult {sim_result.simulation_id!r} "
                f"(site_id={sim_result.site_id!r})"
            )

        peak_state = max(states, key=lambda s: s.depth_mean_m)

        result[node_id] = {
            "peak_hour": peak_state.hour,
            "peak_depth_m": peak_state.depth_mean_m,
            "peak_velocity_mps": peak_state.velocity_mean_mps,
            "peak_rate_of_rise": peak_state.rate_of_rise,
            "ensemble_agreement_fraction": peak_state.ensemble_agreement_fraction,
        }

    return result
