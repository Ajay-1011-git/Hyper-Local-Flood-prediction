"""FastAPI route — T3.6.

`GET /api/damage-ranking/{site_id}`: fetches the current `SimulationResult`
for `site_id`, computes T3.5's ranking on cache miss, caches the result in
Redis thereafter.

## Two real gaps, both flagged (mirrors Stage 1B's precedent for the
## identical "no live upstream endpoint exists yet" situation)

1. **SimulationResult source.** Stage 2's real, documented endpoint is
   `GET /api/simulation/site/{site_id}` (stage2 build doc T2.9) -- Stage 2
   is now real and built (2026-08-20), but its precompute pipeline is
   Celery-orchestrated and out of Stage 2's own T2.9 scope, so no
   deployment with a seeded site is guaranteed to be running at any given
   moment. If `STAGE2_SIMULATION_RESULT_BASE_URL` is configured AND a live
   server is reachable AND seeded for the requested `site_id`, this route
   fetches and validates a real `SimulationResult` from
   `{base_url}/{site_id}`; otherwise (unset, unreachable, or 404 — not
   seeded yet) it falls back to an explicitly-labeled mock fixture,
   deterministic per `site_id` (so repeated requests are idempotent --
   same `simulation_id`, same cache key) -- exactly Stage 1B's
   `_mock_regional_forecast()` pattern for Stage 1A before it went live.
   Which path was used is exposed via `X-Simulation-Source`
   (`stage2_live` | `mock_dev_fixture`).

2. **Building/road-segment geometry source.** `rank_structures` (T3.5)
   also needs `BuildingFootprint`/`RoadSegment` lists. Stage 2's build doc
   still defines NO endpoint that serves these (only the two T2.9 routes
   above exist) -- checked directly against that doc, not assumed absent.
   RESOLVED 2026-08-20 (found during a full-system wiring audit): the
   real GLB model and its anchor data are now present locally, and Stage
   2's own real extraction functions (T2.1/T2.3, plus the new
   `road_segmentation.py` from this same audit) can derive real geometry
   from them directly -- see `demo_site/real_geometry.py`'s module
   docstring for the full reasoning (a direct cross-import of Stage 2's
   functions, not an HTTP call, mirroring the same-direction precedent
   already established by Stage 2 reading Stage 1B's DB directly). Falls
   back to a small, explicitly-labeled placeholder only if the real GLB
   isn't present locally (e.g. a fresh clone without the gitignored
   data) -- exposed via `X-Geometry-Source` (`real_glb` |
   `placeholder_fallback`).

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
from fastapi.middleware.cors import CORSMiddleware

from backend.stage3.config import settings
from backend.stage3.db import get_redis_client
from backend.stage3.demo_site.real_geometry import (
    load_real_demo_site_geometry,
    placeholder_demo_site_geometry,
)
from backend.stage3.ranking.risk_ranking import (
    NoMatchingNodesForStructureError,
    rank_structures,
)
from backend.stage3.shared.contracts import (
    DamageRankEntry,
    NodeState,
    SimulationResult,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Stage 3 — Damage Ranking")

# Real browser origins allowed to call this API -- an explicit allowlist,
# never "*" (same convention as Stage 4's routes.py). Closes the CORS gap
# flagged in Stage 4's own routes.py comment: the frontend calls this
# stage directly (frontend/src/api/client.ts), not through Stage 4.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Gap #1: SimulationResult source (see module docstring)
# ---------------------------------------------------------------------------


def _mock_simulation_result(site_id: str) -> SimulationResult:
    """An explicitly-labeled MOCK SimulationResult, standing in for Stage
    2's not-yet-seeded/unreachable live endpoint. Deterministic per
    `site_id` (a fixed `simulation_id`) so repeated requests are
    idempotent -- not a fresh random result each time. Node states are
    tagged with `building_id`/`road_segment_id` matching Stage 2's REAL
    ids (`Building_01`/`Building_02` -- `Building_03` no longer exists in
    the real site per Stage 2's own confirmed 2026-08-20 ground truth;
    `Road_Segment_000` matches `road_segmentation.py`'s real zero-padded
    naming), so this mock stays consistent with `real_geometry.py`'s
    structure ids even when Stage 2 itself isn't reachable."""
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
            node_id="mock_r1_n1", hour=24, depth_mean_m=0.5, depth_min_m=0.4,
            depth_max_m=0.6, velocity_mean_mps=0.6, velocity_min_mps=0.4,
            velocity_max_mps=0.8, rate_of_rise=0.05, ensemble_agreement_fraction=0.75,
            road_segment_id="Road_Segment_000",
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


def _get_simulation_result(site_id: str, scenario: str = "real") -> tuple[SimulationResult, str]:
    """Returns (result, source) where source is 'stage2_live' or
    'mock_dev_fixture'.

    `scenario` is passed straight through to Stage 2, which runs two real
    simulations per site (see its own `precompute.py` docstring): the real
    forecast, and an explicitly-hypothetical heavy-rain case. Ranking the
    wrong one against the other's hazard would be a real correctness bug,
    so the scenario travels with the request rather than being assumed.
    """
    if settings.stage2_simulation_result_base_url:
        url = f"{settings.stage2_simulation_result_base_url}/{site_id}"
        try:
            resp = requests.get(url, params={"scenario": scenario}, timeout=60)
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
# T3.6 — GET /api/damage-ranking/{site_id}
# ---------------------------------------------------------------------------


@app.get("/api/damage-ranking/{site_id}", response_model=list[DamageRankEntry])
async def get_damage_ranking(
    site_id: str, response: Response, scenario: str = "real"
) -> list[DamageRankEntry]:
    sim_result, sim_source = _get_simulation_result(site_id, scenario)

    # `simulation_id` already encodes the scenario (Stage 2 prefixes it),
    # so this key can never serve one scenario's ranking for the other.
    cache_key = f"damage_ranking:{site_id}:{sim_result.simulation_id}"
    redis = get_redis_client()

    cached = await redis.get(cache_key)
    if cached is not None:
        response.headers["X-Simulation-Source"] = sim_source
        response.headers["X-Simulation-Scenario"] = scenario
        response.headers["X-Cache"] = "hit-redis"
        return [DamageRankEntry.model_validate(entry) for entry in json.loads(cached)]

    # Geometry source is deliberately coupled to the simulation source,
    # not independently chosen: the mock SimulationResult only tags a
    # small, fixed set of structure ids (Building_01/02, one road
    # segment) -- real geometry has 2 real buildings but 41 real road
    # segments (see real_geometry.py's module docstring), which the mock
    # fixture doesn't cover. Mixing a real 41-segment geometry set with
    # the mock's 1-segment simulation would make every uncovered real
    # segment raise NoMatchingNodesForStructureError -- a real,
    # previously-hit bug during this fix's own development, not a
    # hypothetical. Using placeholder geometry alongside the mock
    # simulation keeps the two honestly paired.
    if sim_source == "stage2_live":
        (footprints, road_segments), geometry_source = load_real_demo_site_geometry()
    else:
        footprints, road_segments = placeholder_demo_site_geometry()
        geometry_source = "placeholder_fallback"

    try:
        entries = rank_structures(sim_result, footprints, road_segments)
    except NoMatchingNodesForStructureError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = [entry.model_dump(mode="json") for entry in entries]
    await redis.set(cache_key, json.dumps(payload), ex=settings.damage_ranking_cache_ttl_seconds)

    response.headers["X-Simulation-Source"] = sim_source
    response.headers["X-Geometry-Source"] = geometry_source
    response.headers["X-Simulation-Scenario"] = scenario
    response.headers["X-Cache"] = "miss"
    return entries
