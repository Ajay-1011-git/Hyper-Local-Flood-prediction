"""FastAPI routes — T4A.3.

`GET /api/alert/{site_id}`: assembles a real `Alert` from Stage 2's real
`SimulationResult`, Stage 3's real `DamageRankEntry` ranking, and the
real site polygon (`alerts/site_geometry.py`) — generates CAP-XML
(T4A.1) and multilingual text (T4A.2), caches in Redis (the multilingual
text involves real, paid Sarvam API calls; recomputing every request
would be wasteful).

## WebSocket relay — ALREADY EXISTS, confirmed by reading the actual code

Per this task's own explicit instruction ("confirm with Stage 2/3's
actual code whether this already exists before building a duplicate"):
it does, twice. `backend/stage1b/routes.py` and `backend/stage2/routes.py`
each already implement `/ws/site/{site_id}`, each its own separate
process/`ConnectionManager`. Building a THIRD one here would be exactly
the duplicate this task warns against, so this file does not.

**Real, unresolved gap, documented honestly rather than silently assumed
solved** (Stage 2's own `routes.py` docstring already admits the same
thing about WebSocket duplication): which single WebSocket endpoint the
frontend should actually connect to, given 2 independent processes each
with only a partial view of the event stream. Checked precisely during
T4B.1 (correcting an earlier, wrong claim in this same docstring that
Stage 2 relays `simulation_update` — it does not): as of 2026-08-20,
`sensor_assimilated` is the ONLY event either process ever actually
broadcasts (`grep -rn '"type"'` across the real code, not the contract
comments, confirms this). `simulation_update` and `ranking_update` (per
§B.2's contract) have no emitter anywhere in this repo — Stage 2 never
broadcasts after a `set_site_state()` precompute run, and Stage 3's
`damage-ranking` route (T3.6) is a plain REST endpoint, not a
broadcaster. A real deployment needs one gateway process or a shared
Redis pub/sub (per TRD's own note on multi-worker broadcast), AND
someone to actually call `connection_manager.broadcast()` after a
simulation/ranking update, not just after sensor assimilation. Flagged
here for whoever builds the frontend's WebSocket client (T4B.1) to
design around — the 3D scene's INITIAL state must come from the real
REST endpoints (already wired in T4B.0's `api/client.ts`), not from a
`simulation_update` WS event that will never arrive.

## Sources, mirroring Stage 3's own established pattern

Both `SimulationResult` (from Stage 2) and `List[DamageRankEntry]` (from
Stage 3) are fetched live if configured/reachable, else fall back to an
explicitly-labeled mock, exactly like Stage 3's T3.6 did for Stage 2
before it went live — `X-Simulation-Source` / `X-Ranking-Source` /
`X-Geometry-Source` headers make all three observable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import requests
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.stage4.alerts.cap_generator import derive_severity, derive_urgency, generate_cap_xml
from backend.stage4.alerts.multilingual import generate_alert_text
from backend.stage4.alerts.site_geometry import load_real_site_polygon
from backend.stage4.config import settings
from backend.stage4.db import get_redis_client
from backend.stage4.shared.contracts import (
    Alert,
    DamageRankEntry,
    NodeState,
    SimulationResult,
    SiteTerrainResponse,
)
from backend.stage4.terrain.dem_proxy import TerrainUnavailableError, build_site_terrain

logger = logging.getLogger(__name__)

app = FastAPI(title="Stage 4 — Alerts")

# CORS — added 2026-08-20 during T4B.0, after a REAL headless-browser test
# caught that no stage in this project had it configured at all, so no
# browser frontend could call any backend ("blocked by CORS policy: No
# 'Access-Control-Allow-Origin' header"). curl never surfaces this, which
# is exactly why every earlier stage's curl-based VERIFY passed while the
# system remained unusable from a browser.
#
# `CORS_ALLOWED_ORIGINS` is an explicit allowlist (default: the real Vite
# dev-server origins this project actually uses), NOT `["*"]` -- a
# wildcard would be the lazy fix, and this API is intended to sit behind
# a real gateway in any real deployment.
#
# NOTE, flagged rather than silently worked around: Stage 1A/1B/2/3 each
# still lack CORS, and each is another module's file (this stage's own
# anti-drift rule 6 forbids touching them). A frontend that needs to call
# those directly will hit the same wall -- see frontend/src/api/client.ts.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # The frontend reads these to show WHICH source is powering the
    # display (the honesty requirement in T4C.1/T4C.6); browsers hide
    # non-simple response headers unless they're explicitly exposed.
    expose_headers=[
        "X-Simulation-Source",
        "X-Ranking-Source",
        "X-Geometry-Source",
        "X-Cache",
    ],
)


# ---------------------------------------------------------------------------
# SimulationResult source (mirrors Stage 3's T3.6 pattern)
# ---------------------------------------------------------------------------


def _mock_simulation_result(site_id: str) -> SimulationResult:
    """Explicitly-labeled MOCK, standing in for Stage 2's not-yet-seeded/
    unreachable live endpoint. Deterministic per `site_id`."""
    return SimulationResult(
        simulation_id=f"mock-simulation-{site_id}",
        site_id=site_id,
        source_forecast_id=f"mock-forecast-{site_id}",
        generated_at=datetime.now(timezone.utc),
        # Stage 4 has no hazard_threshold_depth_m config of its own (that's
        # Stage 2/3's concern) -- a fixed, documented default for the mock
        # path only, matching Stage 3's own T3.0 default value.
        hazard_threshold_m=0.3,
        validation_error_m=0.0,
        node_states=[
            NodeState(
                node_id="mock_n1", hour=24, depth_mean_m=0.9, depth_min_m=0.7,
                depth_max_m=1.1, velocity_mean_mps=0.4, velocity_min_mps=0.3,
                velocity_max_mps=0.5, rate_of_rise=0.04, ensemble_agreement_fraction=0.8,
                building_id="Building_01",
            ),
        ],
        envelope={},
    )


def _get_simulation_result(site_id: str) -> Tuple[SimulationResult, str]:
    if settings.stage2_simulation_result_base_url:
        url = f"{settings.stage2_simulation_result_base_url}/{site_id}"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return SimulationResult.model_validate(resp.json()), "stage2_live"
        except Exception as exc:
            logger.error(
                "Failed to fetch real SimulationResult from Stage 2 (%s): %s "
                "— falling back to mock fixture.",
                url,
                exc,
            )
    return _mock_simulation_result(site_id), "mock_dev_fixture"


# ---------------------------------------------------------------------------
# DamageRankEntry ranking source
# ---------------------------------------------------------------------------


def _mock_damage_ranking(site_id: str) -> List[DamageRankEntry]:
    """Explicitly-labeled MOCK -- matches Stage 3's own real building ids
    (Building_01/02) and mock fixture shape."""
    return [
        DamageRankEntry(
            structure_id="Building_01", structure_type="building", site_id=site_id,
            hazard_score=1.34, exposure_score=100.0, vulnerability_score=0.40,
            vulnerability_source="mock -- Stage 3 unreachable",
            vulnerability_is_local_calibration=False, risk_score=53.6,
            confidence=0.8, rank=1, peak_hour=24, peak_depth_m=0.9,
            peak_velocity_mps=0.4, peak_rate_of_rise=0.04,
        ),
    ]


def _get_damage_ranking(site_id: str) -> Tuple[List[DamageRankEntry], str]:
    if settings.stage3_damage_ranking_base_url:
        url = f"{settings.stage3_damage_ranking_base_url}/{site_id}"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return [DamageRankEntry.model_validate(e) for e in resp.json()], "stage3_live"
        except Exception as exc:
            logger.error(
                "Failed to fetch real damage ranking from Stage 3 (%s): %s "
                "— falling back to mock fixture.",
                url,
                exc,
            )
    return _mock_damage_ranking(site_id), "mock_dev_fixture"


# ---------------------------------------------------------------------------
# T4B.3 — GET /api/terrain/{site_id}
#
# Closes a real cross-stage gap: neither Stage 1B's regional DEM nor Stage
# 2's TerrainGrid was reachable over HTTP, so the 3D scene had no geometry
# to render. See terrain/dem_proxy.py's module docstring for why serving it
# from here (rather than adding a Stage 2 endpoint) is the project owner's
# chosen approach, and why reading the same DEM is honest rather than a
# substitute for Stage 2's terrain.
# ---------------------------------------------------------------------------


@app.get("/api/terrain/{site_id}", response_model=SiteTerrainResponse)
async def get_terrain(site_id: str) -> SiteTerrainResponse:
    """Real regional + site-local elevation heightmaps for the 3D scene.

    Raises:
        503: no real DEM covers the configured site, or it can't be read.
            Never falls back to a synthetic/flat surface — a fabricated
            terrain would be indistinguishable from real terrain once
            rendered.
    """
    try:
        return await build_site_terrain(site_id)
    except TerrainUnavailableError as exc:
        logger.error("Terrain unavailable for %s: %s", site_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# T4A.3 — GET /api/alert/{site_id}
# ---------------------------------------------------------------------------


@app.get("/api/alert/{site_id}", response_model=Alert)
async def get_alert(site_id: str, response: Response) -> Alert:
    sim_result, sim_source = _get_simulation_result(site_id)
    damage_ranking, ranking_source = _get_damage_ranking(site_id)

    cache_key = f"alert:{site_id}:{sim_result.simulation_id}"
    redis = get_redis_client()

    cached = await redis.get(cache_key)
    if cached is not None:
        response.headers["X-Simulation-Source"] = sim_source
        response.headers["X-Ranking-Source"] = ranking_source
        response.headers["X-Cache"] = "hit-redis"
        return Alert.model_validate(json.loads(cached))

    site_polygon, geometry_source = load_real_site_polygon()

    top_entry = damage_ranking[0] if damage_ranking else None
    severity = derive_severity(top_entry)
    urgency = derive_urgency(top_entry)
    certainty_value = top_entry.confidence if top_entry is not None else 0.0

    cap_xml = generate_cap_xml(damage_ranking, sim_result, site_polygon)
    text_by_language = {
        lang: generate_alert_text(severity, damage_ranking, lang)
        for lang in settings.supported_languages_list
    }

    alert = Alert(
        id=f"{site_id}-{sim_result.simulation_id}",
        site_id=site_id,
        generated_at=sim_result.generated_at,
        severity=severity,
        certainty=certainty_value,
        urgency=urgency,
        area_polygon=site_polygon,
        effective_time=sim_result.generated_at,
        expiry_time=sim_result.generated_at + timedelta(hours=72),
        cap_xml=cap_xml,
        text_by_language=text_by_language,
    )

    await redis.set(
        cache_key, alert.model_dump_json(), ex=settings.alert_cache_ttl_seconds
    )

    response.headers["X-Simulation-Source"] = sim_source
    response.headers["X-Ranking-Source"] = ranking_source
    response.headers["X-Geometry-Source"] = geometry_source
    response.headers["X-Cache"] = "miss"
    return alert
