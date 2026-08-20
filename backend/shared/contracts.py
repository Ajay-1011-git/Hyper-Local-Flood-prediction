"""Canonical data contracts shared across pipeline stages.

DO NOT rename fields, change types, or "improve" these schemas casually —
Stage 1A, Stage 1B, and (eventually) Stage 2 each independently build code
against them. Any change here must be agreed by whoever owns the consuming
stage before it lands.

- Stage 1A produces `RegionalEnsembleForecast` and `RiverStageForecast`.
- Stage 1B consumes `RegionalEnsembleForecast` and produces
  `DownscaledForecastField` and `SensorReading`.

Copied verbatim from the project's Stage 1A / Stage 1B build-instruction
documents (§B.2 in each).
"""

from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional


# ---------------------------------------------------------------------------
# Stage 1A outputs
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


class TimestepValue(BaseModel):
    hour: int  # 0 to 72
    rainfall_mm: float


class EnsembleMember(BaseModel):
    member_id: int
    trajectory: List[TimestepValue]


class RegionalEnsembleForecast(BaseModel):
    forecast_id: str
    source: str = "GenCast"
    region_bbox: BoundingBox
    generated_at: datetime
    resolution_km: float = 28.0
    members: List[EnsembleMember]


class StageTimestepValue(BaseModel):
    hour: int
    water_level_m: float


class RiverStageForecast(BaseModel):
    source: str = "CWC"
    station_id: str
    station_name: str
    lat: float
    lon: float
    forecast_horizon_hours: int
    trajectory: List[StageTimestepValue]
    breach_threshold_m: Optional[float] = None
    breach_probability: Optional[float] = None
    station_proximity_verified: bool


# ---------------------------------------------------------------------------
# Stage 1B outputs
# ---------------------------------------------------------------------------


class DownscaledTimestepValue(BaseModel):
    hour: int
    inflow_mm: float


class DownscaledEnsembleMember(BaseModel):
    member_id: int  # must match the source RegionalEnsembleForecast's member_id
    trajectory: List[DownscaledTimestepValue]


class DownscaledForecastField(BaseModel):
    site_id: str
    site_lat: float
    site_lon: float
    resolution_km: float = 2.0
    calibration_source: str = "TN WRD"
    calibration_confidence: str  # "calibrated_nearby_station" | "computed_only_no_nearby_station"
    source_forecast_id: str  # traces back to RegionalEnsembleForecast.forecast_id
    generated_at: datetime
    members: List[DownscaledEnsembleMember]


class SensorReading(BaseModel):
    sensor_id: str
    site_id: str
    distance_cm: float
    timestamp: datetime
    assimilated: bool = False


# ---------------------------------------------------------------------------
# Stage 2 outputs — confirmed, verbatim from stage2_build_instructions_glb.md
# §B.2. Stage 2 hasn't been built in this repo yet (Ajay, not started as of
# 2026-08-20); these are added here pre-emptively, in the single shared
# location, specifically to avoid a repeat of the exact mistake caught and
# fixed during the Stage 1A/1B merge (Stage 1A redefined the shared
# contract instead of importing it). Whoever builds Stage 2 should import
# these from here, not redefine them under backend/stage2/shared/.
#
# Each is consumed downstream per that stage's own build doc's "Consumed,
# unchanged, imported verbatim" list:
#   AnchorPoint, BuildingFootprint, TerrainGrid -> Stage 4
#   BuildingFootprint                            -> Stage 3
# `ComputationalMeshNode` is intentionally NOT here — no downstream stage
# doc lists it as a cross-stage import; it appears to be Stage 2-internal
# (mesh/computational_mesh.py's own working representation, feeding the
# solver/GNN, not passed to Stage 3/4).
# ---------------------------------------------------------------------------


class AnchorPoint(BaseModel):
    scene_object_name: str
    scene_local_position: List[float]  # [x, y, z] in Blender scene units
    real_world_lat: float
    real_world_lon: float
    real_world_elevation_m: Optional[float] = None
    scene_to_real_scale_factor: float
    north_axis: str  # e.g. "+Y", confirmed from the Blender task's output


class BuildingFootprint(BaseModel):
    building_id: str  # "Building_01" etc.
    footprint_polygon: List[List[float]]  # [[x, y], ...], real-world meters, site-local frame
    height_m: Optional[float] = None


class TerrainGrid(BaseModel):
    site_id: str
    resolution_m: float
    origin_lat: float
    origin_lon: float
    elevation_grid: List[List[float]]  # 2D array, meters
    interpolated_from_regional_dem: bool  # honesty flag: DEM-derived, not surveyed


# ---------------------------------------------------------------------------
# Stage 2 outputs — PROVISIONAL, RECONSTRUCTED, NOT YET CONFIRMED.
#
# Every Stage 2/3/4 build doc says to import `NodeState`/`SimulationResult`
# "verbatim from Stage 2" or "from the earlier combined Stage 2/3/4
# document" — but that earlier document does not exist anywhere in
# Flood_system_finial/, and no doc gives these classes' actual fields.
# This is a real, confirmed gap (checked: grepped every .md in that folder
# for every field name below; TRD §5.3's `SimulationNode` is the only
# concrete precedent, and it predates and doesn't match the newer docs'
# vocabulary).
#
# What follows is reconstructed from every direct field/attribute mention
# found across all four stage docs + the TRD, cited per field. It is NOT a
# verbatim copy of an authoritative spec (none exists to copy from) —
# treat it as a starting draft. MUST be confirmed/corrected by whoever
# actually builds Stage 2's T2.6 (GNN)/T2.7 (ensemble aggregation), since
# they're the ones who will know the real shape their own code produces.
# Do not silently start depending on the unconfirmed fields (marked below)
# as if they were settled.
# ---------------------------------------------------------------------------


class NodeState(BaseModel):
    """One computational mesh node's simulated hydraulic state at one
    timestep, aggregated across the forecast ensemble — never raw
    per-member arrays (Stage 2 T2.7's explicit rule: "Do not persist or
    return raw per-member arrays — only the aggregated NodeState
    fields")."""

    node_id: str  # CONFIRMED name: matches ComputationalMeshNode.node_id (stage2 doc)
    hour: int  # UNCONFIRMED name/range; by analogy with every other timestep field
    # in this project (TimestepValue.hour, DownscaledTimestepValue.hour), 0-72

    depth_mean_m: float  # CONFIRMED literal name (stage4 doc: "NodeState.depth_mean_m")
    depth_min_m: float  # UNCONFIRMED name; stage2 doc says ensemble aggregation computes
    depth_max_m: float  # "mean/min/max depth" per node/timestep — paired with depth_mean_m
    velocity_mean_mps: float  # UNCONFIRMED name; parallel to depth_mean_m, same
    velocity_min_mps: float  # stage2 doc sentence ("mean/min/max depth AND velocity")
    velocity_max_mps: float
    rate_of_rise: float  # UNCONFIRMED aggregation form (single value vs mean/min/max) —
    # TRD §5.3's SimulationNode.states has a bare `rate_of_rise`, and
    # stage3 doc's DamageRankEntry.peak_rate_of_rise (singular, not
    # _mean/_min/_max) suggests this one field is NOT split 3 ways
    # like depth/velocity are — needs confirming, not assumed.

    ensemble_agreement_fraction: float  # CONFIRMED name (stage3 doc's extract_peak_hazard
    # return value; stage4 doc: Alert.certainty "from ensemble agreement —
    # never a placeholder"). Fraction of ensemble members exceeding a
    # configurable hazard threshold at this node/hour (stage2 T2.7).

    building_id: Optional[str] = None  # UNCONFIRMED addition, added while implementing
    # stage3 T3.5, not by original doc citation — flagged for explicit user
    # sign-off (recorded 2026-08-20). Real gap: stage2 doc T2.1 confirms
    # `ComputationalMeshNode.building_id` IS set for wall nodes ("set if
    # is_wall_node is True"), but `ComputationalMeshNode` is Stage-2-internal
    # (see note above `AnchorPoint`: "no downstream stage doc lists it as a
    # cross-stage import") — so as drafted, NodeState/SimulationResult (what
    # Stage 3 actually receives) carried no way to group hazard by
    # structure at all. `rank_structures` (T3.5) needs exactly this link.
    # This mirrors ComputationalMeshNode's real, confirmed field name/
    # semantics (not invented from nothing) but its presence on NodeState
    # specifically is NOT yet confirmed against Stage 2's actual T2.6/T2.7
    # output — MUST be corrected once Stage 2 is real. None for
    # non-wall/non-road-adjacent nodes (most of the mesh).
    road_segment_id: Optional[str] = None  # UNCONFIRMED, same reasoning as
    # building_id above, extended to roads by analogy — stage2 doc's T2.1
    # only confirms the building_id tagging explicitly; road-node tagging
    # is this project's own inference, not cited from any doc. At most one
    # of building_id/road_segment_id is set per node; both None for open
    # terrain/water nodes with no structure overlap.


class SimulationResult(BaseModel):
    """Stage 2's full simulation output for one site, one forecast run."""

    simulation_id: str  # UNCONFIRMED name; needed for stage3's own idempotency
    # requirement ("re-running for the same SimulationResult id produces
    # the same ranking") and stage3's Redis-caching-by-id design — some
    # identifier must exist, exact field name not confirmed.
    site_id: str  # CONFIRMED: appears throughout (routes, WS channel, Alert.site_id)
    source_forecast_id: str  # UNCONFIRMED name; by analogy with
    # DownscaledForecastField.source_forecast_id's traceability pattern,
    # used everywhere else in this project — SimulationResult presumably
    # traces back to the DownscaledForecastField it was computed from.
    generated_at: datetime  # UNCONFIRMED; standard field on every other contract here
    hazard_threshold_m: float  # UNCONFIRMED name; the threshold
    # ensemble_agreement_fraction is computed against (stage2 T2.7:
    # "agreement fraction against a configurable hazard threshold")
    validation_error_m: float  # CONFIRMED (stage2 doc T2.6 VERIFY: "this
    # becomes SimulationResult.validation_error_m") — the fine-tuned GNN's
    # depth/velocity MAE against the solver on held-out scenarios.
    node_states: List[NodeState]  # CONFIRMED shape (stage4 doc's WS payload:
    # `{"type": "simulation_update", "payload": {"node_states": [...], ...}}`)
    envelope: dict  # CONFIRMED key name (same WS payload), UNCONFIRMED internal
    # shape — likely a site-wide summary (e.g. count/fraction of members
    # exceeding a threshold over time, per the architecture doc's example
    # language "18 of 50 scenarios exceed 50cm depth by hour 48"), but the
    # exact fields are not specified anywhere available.


# ---------------------------------------------------------------------------
# Stage 3 outputs — confirmed, verbatim from stage3_build_instructions.md
# §B.2. Stage 3 hasn't been built in this repo yet either; added here for
# the same reason as Stage 2's contracts above.
# ---------------------------------------------------------------------------


class RoadSegment(BaseModel):
    segment_id: str
    polyline: List[List[float]]  # [[x, y], ...], real-world meters, site-local frame
    width_m: Optional[float] = None


class DamageRankEntry(BaseModel):
    structure_id: str  # "Building_01" or a RoadSegment.segment_id
    structure_type: str  # "building" | "road_segment"
    site_id: str
    hazard_score: float
    exposure_score: float
    vulnerability_score: float
    vulnerability_source: str  # citation, never blank
    vulnerability_is_local_calibration: bool = False  # always False unless real local data exists
    risk_score: float
    confidence: float  # from ensemble_agreement_fraction
    rank: int
    peak_hour: int
    peak_depth_m: float
    peak_velocity_mps: float
    peak_rate_of_rise: float
