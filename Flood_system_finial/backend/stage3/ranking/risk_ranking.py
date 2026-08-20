"""Risk ranking — T3.5.

Combines T3.1's hazard extraction, T3.3's exposure scoring, and T3.4's
vulnerability curve into the final ranked `DamageRankEntry` list, per the
build doc's literal instruction: "combine hazard x exposure x
vulnerability into the final ranked list."

ASSUMPTION #1, flagged (real contract gap, user sign-off recorded
2026-08-20): `rank_structures` needs to know which of `sim_result`'s
`NodeState` entries belong to which building/road segment. Stage 2's own
doc confirms mesh nodes DO carry this link (`ComputationalMeshNode.
building_id`, set for wall nodes) -- but that class is Stage-2-internal,
never passed downstream, so `NodeState` as originally drafted had no such
field. `building_id`/`road_segment_id` were added to `NodeState` in
`backend/shared/contracts.py` to close this gap -- see that file and
`backend/stage3/CLAUDE.md`'s "Added during T3.5" note. UNCONFIRMED
against Stage 2's real output; must be corrected once Stage 2 exists.

ASSUMPTION #2, flagged: a structure's mesh footprint is (or can be) more
than one node -- e.g. a building's wall nodes are every grid cell inside
its footprint polygon (stage2 doc T2.1). This module's own "peak" for a
structure is therefore the worst-depth node's peak (extending T3.1's
own depth-anchoring convention across a *set* of nodes, not just across
one node's own time series) -- not an average across the structure's
nodes, consistent with the project's standing "worst moment, not mean
condition" rule.

ASSUMPTION #3, flagged: no formula for combining depth/velocity/
rate-of-rise into a single `hazard_score` number is specified anywhere in
this project's docs (checked: grepped every .md in Flood_system_finial/
for "hazard_score" -- it appears only as a bare field name, never a
formula). Implemented here as a simple equal-weighted sum of the three
peak values, chosen so all three are visibly, independently present in
the score (satisfying CLAUDE.md's non-negotiable "never rank by depth
alone" rule, and stage3 doc's Final Acceptance item 1) and each
contributes monotonically. Not independently validated against published
flood-risk-ranking literature -- revisit once Stage 2's real output
exists to sanity-check against.
"""

from __future__ import annotations

from backend.stage3.exposure.exposure_scoring import compute_exposure_score
from backend.stage3.hazard.extract_hazard import extract_peak_hazard
from backend.stage3.shared.contracts import (
    BuildingFootprint,
    DamageRankEntry,
    RoadSegment,
    SimulationResult,
)
from backend.stage3.vulnerability.fragility_curve import (
    VULNERABILITY_CURVE_SOURCE,
    compute_vulnerability,
)


class NoMatchingNodesForStructureError(Exception):
    """Raised when a structure (building or road segment) has zero
    `NodeState` entries tagged with its id in `sim_result.node_states` --
    never silently scored as zero-hazard."""


def _node_ids_for(structure_id: str, sim_result: SimulationResult, field: str) -> list[str]:
    ids = sorted(
        {
            state.node_id
            for state in sim_result.node_states
            if getattr(state, field) == structure_id
        }
    )
    if not ids:
        raise NoMatchingNodesForStructureError(
            f"No NodeState entries with {field}={structure_id!r} in "
            f"SimulationResult {sim_result.simulation_id!r} "
            f"(site_id={sim_result.site_id!r})"
        )
    return ids


def _structure_peak_hazard(node_ids: list[str], sim_result: SimulationResult) -> dict:
    """Peak across this structure's own set of nodes, anchored on depth
    (see module docstring, Assumption #2) -- deterministic tie-break by
    node_id, since `dict` iteration/`max` over equal keys is otherwise
    insertion-order-dependent."""
    per_node = extract_peak_hazard(sim_result, node_ids)
    best_node_id = max(sorted(per_node), key=lambda nid: per_node[nid]["peak_depth_m"])
    return per_node[best_node_id]


def _hazard_score(peak: dict) -> float:
    """See module docstring, Assumption #3."""
    return peak["peak_depth_m"] + peak["peak_velocity_mps"] + peak["peak_rate_of_rise"]


def _score_structure(
    structure_id: str,
    structure_type: str,
    node_field: str,
    exposure_input,
    sim_result: SimulationResult,
) -> DamageRankEntry:
    node_ids = _node_ids_for(structure_id, sim_result, node_field)
    peak = _structure_peak_hazard(node_ids, sim_result)

    hazard_score = _hazard_score(peak)
    exposure_score = compute_exposure_score(exposure_input)
    vulnerability_score = compute_vulnerability(peak["peak_depth_m"], peak["peak_velocity_mps"])

    return DamageRankEntry(
        structure_id=structure_id,
        structure_type=structure_type,
        site_id=sim_result.site_id,
        hazard_score=hazard_score,
        exposure_score=exposure_score,
        vulnerability_score=vulnerability_score,
        vulnerability_source=VULNERABILITY_CURVE_SOURCE,
        vulnerability_is_local_calibration=False,
        risk_score=hazard_score * exposure_score * vulnerability_score,
        confidence=peak["ensemble_agreement_fraction"],
        rank=0,  # placeholder; assigned after the full list is sorted below
        peak_hour=peak["peak_hour"],
        peak_depth_m=peak["peak_depth_m"],
        peak_velocity_mps=peak["peak_velocity_mps"],
        peak_rate_of_rise=peak["peak_rate_of_rise"],
    )


def rank_structures(
    sim_result: SimulationResult,
    footprints: list[BuildingFootprint],
    road_segments: list[RoadSegment],
) -> list[DamageRankEntry]:
    """Compute risk per structure/segment, sort descending by
    `risk_score`, and assign `rank` sequentially.

    Deterministic: identical input always produces an identical output
    list, including tie-breaking order (ties broken by `structure_id`
    ascending -- never by insertion order, which real callers should not
    be relied upon to keep stable).
    """
    entries = [
        _score_structure(fp.building_id, "building", "building_id", fp, sim_result)
        for fp in footprints
    ] + [
        _score_structure(seg.segment_id, "road_segment", "road_segment_id", seg, sim_result)
        for seg in road_segments
    ]

    entries.sort(key=lambda e: (-e.risk_score, e.structure_id))
    for i, entry in enumerate(entries, start=1):
        entry.rank = i

    return entries
