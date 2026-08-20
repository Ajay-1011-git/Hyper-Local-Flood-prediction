"""Tests for T3.6 — GET /api/damage-ranking/{site_id}.

Real integration tests against actual local Redis (same philosophy as
Stage 1B's test_routes.py: this route genuinely needs it, and it's local
infrastructure, not a third-party network call).

Stage 2 is not mocked via a fake server -- there is no live Stage 2
endpoint anywhere (Ajay's Stage 2 doesn't exist in this repo yet), so the
route's real, documented behavior today is its mock-fixture fallback
path. Tests for the "Stage 2 IS configured" branch monkeypatch
`requests.get` directly, which is the one real external call this route
makes.

Uses `httpx.AsyncClient` + `ASGITransport`, not `TestClient`, for the same
event-loop reason as Stage 1B's test_routes.py (see this stage's
pytest.ini) -- confirmed necessary here too by hitting the same
"another operation is in progress" failure with TestClient first.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.stage3 import routes
from backend.stage3.config import settings
from backend.stage3.db import get_redis_client
from backend.stage3.routes import app
from backend.stage3.shared.contracts import NodeState, SimulationResult


@pytest.fixture(autouse=True)
async def _clean_redis():
    """Each test uses its own site_id (see below) so cache keys don't
    collide, but flush defensively before/after anyway."""
    redis = get_redis_client()
    yield
    keys = await redis.keys("damage_ranking:test_*")
    if keys:
        await redis.delete(*keys)


async def test_mock_fixture_path_used_when_stage2_not_configured():
    assert settings.stage2_simulation_result_base_url is None  # real .env.example default

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/damage-ranking/test_site_01")

    assert resp.status_code == 200
    assert resp.headers["X-Simulation-Source"] == "mock_dev_fixture"
    assert resp.headers["X-Cache"] == "miss"

    entries = resp.json()
    structure_ids = {e["structure_id"] for e in entries}
    assert structure_ids == {"Building_01", "Building_02", "Building_03", "Road_Segment_01"}


async def test_second_request_is_served_from_redis_cache():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/damage-ranking/test_site_02")
        second = await client.get("/api/damage-ranking/test_site_02")

    assert first.headers["X-Cache"] == "miss"
    assert second.headers["X-Cache"] == "hit-redis"
    assert first.json() == second.json()  # cached payload round-trips identically


async def test_cache_hit_skips_recomputation():
    """Proves the cache isn't just returning the same answer by
    coincidence -- rank_structures must not be called on the second
    request at all."""
    call_count = 0
    real_rank_structures = routes.rank_structures

    def _counting_rank_structures(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_rank_structures(*args, **kwargs)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch.object(routes, "rank_structures", side_effect=_counting_rank_structures):
            await client.get("/api/damage-ranking/test_site_03")
            await client.get("/api/damage-ranking/test_site_03")

    assert call_count == 1


async def test_ranked_output_reflects_real_hazard_differences():
    """Sanity check against the mock fixture's own designed story:
    Building_02 (deeper, faster in the mock fixture) should outrank
    Building_03 (shallow, slow)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/damage-ranking/test_site_04")

    entries = {e["structure_id"]: e for e in resp.json()}
    assert entries["Building_02"]["risk_score"] > entries["Building_03"]["risk_score"]
    ranks = sorted(entries.values(), key=lambda e: e["rank"])
    assert [e["risk_score"] for e in ranks] == sorted(
        (e["risk_score"] for e in ranks), reverse=True
    )


def _fake_live_simulation_result(site_id: str) -> SimulationResult:
    return SimulationResult(
        simulation_id=f"live-sim-{site_id}",
        site_id=site_id,
        source_forecast_id="live-forecast-0001",
        generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=0.3,
        validation_error_m=0.05,
        node_states=[
            NodeState(
                node_id="live_b1_n1", hour=24, depth_mean_m=1.0, depth_min_m=0.8,
                depth_max_m=1.2, velocity_mean_mps=0.5, velocity_min_mps=0.4,
                velocity_max_mps=0.6, rate_of_rise=0.05, ensemble_agreement_fraction=0.8,
                building_id="Building_01",
            ),
            NodeState(
                node_id="live_b2_n1", hour=24, depth_mean_m=1.0, depth_min_m=0.8,
                depth_max_m=1.2, velocity_mean_mps=0.5, velocity_min_mps=0.4,
                velocity_max_mps=0.6, rate_of_rise=0.05, ensemble_agreement_fraction=0.8,
                building_id="Building_02",
            ),
            NodeState(
                node_id="live_b3_n1", hour=24, depth_mean_m=1.0, depth_min_m=0.8,
                depth_max_m=1.2, velocity_mean_mps=0.5, velocity_min_mps=0.4,
                velocity_max_mps=0.6, rate_of_rise=0.05, ensemble_agreement_fraction=0.8,
                building_id="Building_03",
            ),
            NodeState(
                node_id="live_r1_n1", hour=24, depth_mean_m=1.0, depth_min_m=0.8,
                depth_max_m=1.2, velocity_mean_mps=0.5, velocity_min_mps=0.4,
                velocity_max_mps=0.6, rate_of_rise=0.05, ensemble_agreement_fraction=0.8,
                road_segment_id="Road_Segment_01",
            ),
        ],
        envelope={},
    )


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


async def test_uses_live_stage2_source_when_configured_and_reachable():
    fake_result = _fake_live_simulation_result("test_site_05")

    def _fake_get(url, timeout):
        assert url == "http://fake-stage2/api/simulation/site/test_site_05"
        return _FakeResponse(json.loads(fake_result.model_dump_json()))

    with patch.object(settings, "stage2_simulation_result_base_url", "http://fake-stage2/api/simulation/site"):
        with patch.object(routes.requests, "get", side_effect=_fake_get):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/damage-ranking/test_site_05")

    assert resp.headers["X-Simulation-Source"] == "stage2_live"
    entries = {e["structure_id"] for e in resp.json()}
    assert entries == {"Building_01", "Building_02", "Building_03", "Road_Segment_01"}


async def test_falls_back_to_mock_when_stage2_configured_but_unreachable():
    def _raising_get(url, timeout):
        raise ConnectionError("stage2 not reachable in this test")

    with patch.object(settings, "stage2_simulation_result_base_url", "http://fake-stage2/api/simulation/site"):
        with patch.object(routes.requests, "get", side_effect=_raising_get):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/damage-ranking/test_site_06")

    assert resp.status_code == 200
    assert resp.headers["X-Simulation-Source"] == "mock_dev_fixture"


async def test_missing_hazard_data_for_a_structure_returns_503_not_a_crash():
    """If the demo geometry and the simulation's node tags ever disagree
    (a real, previously-caught bug class), the route must fail loudly
    (503) rather than silently drop the mismatched structure or crash
    with an unhandled exception."""
    from backend.stage3.shared.contracts import BuildingFootprint

    bad_footprints = [
        BuildingFootprint(
            building_id="Building_does_not_exist_in_any_simulation",
            footprint_polygon=[[0, 0], [1, 0], [1, 1], [0, 1]],
        )
    ]

    with patch.object(routes, "_demo_site_geometry", return_value=(bad_footprints, [])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/damage-ranking/test_site_07")

    assert resp.status_code == 503
