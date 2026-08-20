"""FastAPI route — T3.6.

`GET /api/damage-ranking/{site_id}`: fetches the current `SimulationResult`
for `site_id`, computes T3.5's ranking on cache miss, caches the result in
Redis thereafter.

## Two real gaps, both flagged (mirrors Stage 1B's precedent for the
## identical "no live upstream endpoint exists yet" situation)

1. **SimulationResult source.** Stage 2's real, documented endpoint is
   `GET /api/simulation/site/{site_id}` (stage2 build doc T2.9) -- no live
   deployment of it exists in this repo yet (Ajay's Stage 2 is still in
   progress as of 2026-08-20). If `STAGE2_SIMULATION_RESULT_BASE_URL` is
   configured, this route fetches and validates a real `SimulationResult`
   from `{base_url}/{site_id}`; otherwise (or on fetch failure) it falls
   back to an explicitly-labeled mock fixture, deterministic per
   `site_id` (so repeated requests are idempotent -- same `simulation_id`,
   same cache key) -- exactly Stage 1B's `_mock_regional_forecast()`
   pattern for Stage 1A before it went live. Which path was used is
   exposed via `X-Simulation-Source` (`stage2_live` | `mock_dev_fixture`).

2. **Building/road-segment geometry source.** `rank_structures` (T3.5)
   also needs `BuildingFootprint`/`RoadSegment` lists. Stage 2's build doc
   defines NO endpoint that serves these at all (only the two T2.9 routes
   above exist) -- checked directly against that doc, not assumed absent.
   Real footprint data doesn't exist anywhere yet either: the actual
   Blender/GLB model of the demo site's buildings was still being
   produced by the team as of this writing. `_demo_site_geometry()` below
   is therefore an explicitly-labeled PLACEHOLDER (small illustrative
   rectangles/lines, not real surveyed coordinates), standing in only
   until Stage 2 defines and exposes a real footprint-serving mechanism.
   Must be replaced, not silently trusted as real geometry.

## Caching

Per T3.6's literal spec ("cached in Redis thereafter") -- Redis only, no
DB persistence (unlike Stage 1B's T1B.9, which needed a DB table for a
different idempotency requirement). Cache key is
`damage_ranking:{site_id}:{simulation_id}`, TTL from
`DAMAGE_RANKING_CACHE_TTL_SECONDS` (config.py, flagged unverified
default). `X-Cache: hit-redis | miss` makes this observable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException, Response

from backend.stage3.config import settings
from backend.stage3.db import get_redis_client
from backend.stage3.ranking.risk_ranking import (
    NoMatchingNodesForStructureError,
    rank_structures,
)
from backend.stage3.shared.contracts import (
    BuildingFootprint,
    DamageRankEntry,
    NodeState,
    RoadSegment,
    SimulationResult,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Stage 3 — Damage Ranking")


# ---------------------------------------------------------------------------
# Gap #1: SimulationResult source (see module docstring)
# ---------------------------------------------------------------------------


def _mock_simulation_result(site_id: str) -> SimulationResult:
    """An explicitly-labeled MOCK SimulationResult, standing in for Stage
    2's not-yet-deployed live endpoint. Deterministic per `site_id` (a
    fixed `simulation_id`) so repeated requests are idempotent -- not a
    fresh random result each time. Node states are tagged with
    `building_id`/`road_segment_id` matching `_demo_site_geometry()`'s
    structure ids, since both must agree for `rank_structures` to find
    any nodes at all."""
    node_states = [
        NodeState(
            node_id="mock_b1_n1", hour=24, depth_mean_m=0.9, depth_min_m=0.7,
            depth_max_m=1.1, velocity_mean_mps=0.4, velocity_min_mps=0.3,
            velocity_max_mps=0.5, rate_of_rise=0.04, ensemble_agreement_fraction=0.8,
            building_id="Building_01",
        ),
        NodeState(
            node_id="mock_b2_n1", hour=30, depth_mean_m=1.6, depth_min_m=1.3,
            depth_max_m=1.9, velocity_mean_mps=1.1, velocity_min_mps=0.8,
            velocity_max_mps=1.4, rate_of_rise=0.10, ensemble_agreement_fraction=0.7,
            building_id="Building_02",
        ),
        NodeState(
            node_id="mock_b3_n1", hour=18, depth_mean_m=0.3, depth_min_m=0.2,
            depth_max_m=0.4, velocity_mean_mps=0.2, velocity_min_mps=0.1,
            velocity_max_mps=0.3, rate_of_rise=0.02, ensemble_agreement_fraction=0.9,
            building_id="Building_03",
        ),
        NodeState(
            node_id="mock_r1_n1", hour=24, depth_mean_m=0.5, depth_min_m=0.4,
            depth_max_m=0.6, velocity_mean_mps=0.6, velocity_min_mps=0.4,
            velocity_max_mps=0.8, rate_of_rise=0.05, ensemble_agreement_fraction=0.75,
            road_segment_id="Road_Segment_01",
        ),
    ]

    return SimulationResult(
        simulation_id=f"mock-simulation-{site_id}",
        site_id=site_id,
        source_forecast_id=f"mock-forecast-{site_id}",
        generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=settings.hazard_threshold_depth_m,
        validation_error_m=0.0,  # honest: no real GNN validation exists for a mock
        node_states=node_states,
        envelope={},
    )


def _get_simulation_result(site_id: str) -> tuple[SimulationResult, str]:
    """Returns (result, source) where source is 'stage2_live' or
    'mock_dev_fixture'."""
    if settings.stage2_simulation_result_base_url:
        url = f"{settings.stage2_simulation_result_base_url}/{site_id}"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return SimulationResult.model_validate(resp.json()), "stage2_live"
        except Exception as exc:
            logger.error(
                "Failed to fetch real SimulationResult from Stage 2 (%s): "
                "%s — falling back to mock fixture.",
                url,
                exc,
            )
    return _mock_simulation_result(site_id), "mock_dev_fixture"


# ---------------------------------------------------------------------------
# Gap #2: building/road-segment geometry source (see module docstring)
# ---------------------------------------------------------------------------


def _demo_site_geometry() -> tuple[list[BuildingFootprint], list[RoadSegment]]:
    """PLACEHOLDER geometry, NOT real surveyed coordinates -- see module
    docstring's Gap #2. Structure ids match `_mock_simulation_result`'s
    `building_id`/`road_segment_id` tags."""
    footprints = [
        BuildingFootprint(
            building_id="Building_01",
            footprint_polygon=[[0, 0], [10, 0], [10, 10], [0, 10]],
        ),
        BuildingFootprint(
            building_id="Building_02",
            footprint_polygon=[[20, 0], [35, 0], [35, 12], [20, 12]],
        ),
        BuildingFootprint(
            building_id="Building_03",
            footprint_polygon=[[45, 0], [52, 0], [52, 6], [45, 6]],
        ),
    ]
    road_segments = [
        RoadSegment(
            segment_id="Road_Segment_01",
            polyline=[[0, 20], [40, 20]],
            width_m=7.0,
        ),
    ]
    return footprints, road_segments


# ---------------------------------------------------------------------------
# T3.6 — GET /api/damage-ranking/{site_id}
# ---------------------------------------------------------------------------


@app.get("/api/damage-ranking/{site_id}", response_model=list[DamageRankEntry])
async def get_damage_ranking(site_id: str, response: Response) -> list[DamageRankEntry]:
    sim_result, sim_source = _get_simulation_result(site_id)

    cache_key = f"damage_ranking:{site_id}:{sim_result.simulation_id}"
    redis = get_redis_client()

    cached = await redis.get(cache_key)
    if cached is not None:
        response.headers["X-Simulation-Source"] = sim_source
        response.headers["X-Cache"] = "hit-redis"
        return [DamageRankEntry.model_validate(entry) for entry in json.loads(cached)]

    footprints, road_segments = _demo_site_geometry()
    try:
        entries = rank_structures(sim_result, footprints, road_segments)
    except NoMatchingNodesForStructureError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = [entry.model_dump(mode="json") for entry in entries]
    await redis.set(cache_key, json.dumps(payload), ex=settings.damage_ranking_cache_ttl_seconds)

    response.headers["X-Simulation-Source"] = sim_source
    response.headers["X-Cache"] = "miss"
    return entries
