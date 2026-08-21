"""Tests for T4A.3 — GET /api/alert/{site_id}.

Real integration tests against actual local Redis (same philosophy as
Stage 3's test_routes.py: this route genuinely needs it). Stage 2/3 are
not mocked via fake servers by default -- no live deployment is
guaranteed running, so the route's real, documented behavior is its
mock-fixture fallback path; the "configured and reachable" branches are
tested by monkeypatching `requests.get` directly. Sarvam AI translation
calls (via `generate_alert_text`) are mocked too, per this project's
convention of never letting automated tests depend on real, paid,
third-party network calls succeeding.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.stage4 import routes
from backend.stage4.config import settings
from backend.stage4.db import get_redis_client
from backend.stage4.routes import app


@pytest.fixture(autouse=True)
async def _clean_redis():
    redis = get_redis_client()
    yield
    keys = await redis.keys("alert:test_*")
    if keys:
        await redis.delete(*keys)


@pytest.fixture(autouse=True)
def _mock_translation():
    """Sarvam is a real, paid, live network call -- never exercised by
    the default test suite (see `test_sarvam_client.py` for the one real
    live call, gated separately)."""
    with patch(
        "backend.stage4.alerts.multilingual.translate_text",
        side_effect=lambda text, source, target: f"[{target}]{text}",
    ):
        yield


async def test_mock_fixture_path_used_when_stage2_stage3_not_configured():
    with patch.object(settings, "stage2_simulation_result_base_url", None):
        with patch.object(settings, "stage3_damage_ranking_base_url", None):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/alert/test_site_01")

    assert resp.status_code == 200
    assert resp.headers["X-Simulation-Source"] == "mock_dev_fixture"
    assert resp.headers["X-Ranking-Source"] == "mock_dev_fixture"
    assert resp.headers["X-Cache"] == "miss"

    body = resp.json()
    assert body["site_id"] == "test_site_01"
    assert "<alert" in body["cap_xml"]
    assert set(body["text_by_language"].keys()) == {"en", "ta", "hi", "te", "ml", "kn"}
    assert body["text_by_language"]["ta"].startswith("[ta]")  # confirms translation path ran


async def test_second_request_is_served_from_redis_cache():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/alert/test_site_02")
        second = await client.get("/api/alert/test_site_02")

    assert first.headers["X-Cache"] == "miss"
    assert second.headers["X-Cache"] == "hit-redis"
    assert first.json() == second.json()


async def test_cache_hit_skips_recomputation_including_sarvam_calls():
    """Proves caching genuinely avoids re-running expensive work (real
    Sarvam calls, XML generation), not just returning the same answer by
    coincidence."""
    call_count = {"n": 0}
    real_generate_cap_xml = routes.generate_cap_xml

    def _counting(*args, **kwargs):
        call_count["n"] += 1
        return real_generate_cap_xml(*args, **kwargs)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch.object(routes, "generate_cap_xml", side_effect=_counting):
            await client.get("/api/alert/test_site_03")
            await client.get("/api/alert/test_site_03")

    assert call_count["n"] == 1


async def test_severity_urgency_certainty_trace_to_the_real_top_ranked_entry():
    # This test is ABOUT the mock-fixture path, so the live Stage 2/3 URLs
    # are explicitly unset for it. Without this it depends on whether a
    # real Stage 2 happens to be running on this machine: `.env` configures
    # those URLs, so the route made a genuine network call, got a 404 for
    # this synthetic site id, and fell back to the mock anyway -- passing
    # for the wrong reason when no server was up, and failing outright
    # when one was. A test's result must not depend on that.
    with patch.object(settings, "stage2_simulation_result_base_url", None):
        with patch.object(settings, "stage3_damage_ranking_base_url", None):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/alert/test_site_04")

    body = resp.json()
    # Mock damage ranking's top entry: vulnerability_score=0.40 -> Moderate
    # (>= 0.25 tier), peak_hour=24 -> Expected, confidence=0.8 -> certainty 0.8.
    assert body["severity"] == "Moderate"
    assert body["urgency"] == "Expected"
    assert body["certainty"] == pytest.approx(0.8)


async def test_uses_live_stage2_and_stage3_sources_when_configured():
    from datetime import datetime, timezone

    from backend.stage4.shared.contracts import DamageRankEntry, NodeState, SimulationResult

    fake_sim = SimulationResult(
        simulation_id="live-sim-01", site_id="test_site_05",
        source_forecast_id="live-forecast-01", generated_at=datetime.now(timezone.utc),
        hazard_threshold_m=0.3, validation_error_m=0.02,
        node_states=[
            NodeState(
                node_id="n1", hour=5, depth_mean_m=1.0, depth_min_m=0.8, depth_max_m=1.2,
                velocity_mean_mps=0.5, velocity_min_mps=0.4, velocity_max_mps=0.6,
                rate_of_rise=0.05, ensemble_agreement_fraction=0.9, building_id="Building_02",
            ),
        ],
        envelope={},
    )
    fake_ranking = [
        DamageRankEntry(
            structure_id="Building_02", structure_type="building", site_id="test_site_05",
            hazard_score=6.0, exposure_score=300.0, vulnerability_score=0.9,
            vulnerability_source="real", vulnerability_is_local_calibration=False,
            risk_score=1620.0, confidence=0.9, rank=1, peak_hour=5,
            peak_depth_m=1.8, peak_velocity_mps=2.0, peak_rate_of_rise=0.15,
        ),
    ]

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _fake_get(url, timeout=None, params=None):
        # `params` carries the real scenario Stage 4 now forwards to
        # Stage 2/3, so an alert is always built from the simulation the
        # operator is actually looking at. Asserted rather than ignored:
        # dropping it would silently alert on the wrong scenario.
        assert params == {"scenario": "real"}
        if "simulation" in url:
            return _FakeResponse(fake_sim.model_dump(mode="json"))
        return _FakeResponse([e.model_dump(mode="json") for e in fake_ranking])

    with patch.object(settings, "stage2_simulation_result_base_url", "http://fake-stage2/api/simulation/site"):
        with patch.object(settings, "stage3_damage_ranking_base_url", "http://fake-stage3/api/damage-ranking"):
            with patch.object(routes.requests, "get", side_effect=_fake_get):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get("/api/alert/test_site_05")

    assert resp.headers["X-Simulation-Source"] == "stage2_live"
    assert resp.headers["X-Ranking-Source"] == "stage3_live"
    body = resp.json()
    assert body["severity"] == "Extreme"  # vulnerability_score=0.9
    assert body["urgency"] == "Immediate"  # peak_hour=5


async def test_falls_back_to_mock_when_configured_but_unreachable():
    def _raising_get(url, timeout):
        raise ConnectionError("unreachable in this test")

    with patch.object(settings, "stage2_simulation_result_base_url", "http://fake-stage2/api/simulation/site"):
        with patch.object(settings, "stage3_damage_ranking_base_url", "http://fake-stage3/api/damage-ranking"):
            with patch.object(routes.requests, "get", side_effect=_raising_get):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get("/api/alert/test_site_06")

    assert resp.status_code == 200
    assert resp.headers["X-Simulation-Source"] == "mock_dev_fixture"
    assert resp.headers["X-Ranking-Source"] == "mock_dev_fixture"
