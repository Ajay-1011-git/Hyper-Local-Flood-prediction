"""Tests for T1B.9 — GET /api/forecast/downscaled.

Real integration tests against the actual local PostgreSQL+PostGIS and
Redis (same philosophy as test_db.py — this route genuinely needs both,
and they're local infrastructure, not third-party network calls).

EXTERNAL NETWORK IS MOCKED (T1B.12's explicit requirement: "Mock all
external network calls (Bhuvan, TN WRD) in automated tests"). The route
calls `fetch_rainfall_telemetry()` on every cache miss, which really
downloads ~24MB of CSVs from nwdp.nwic.gov.in — an earlier version of
this file let that run live, which was wrong on three counts, all real
rather than theoretical: it violated T1B.12's requirement, it made the
suite depend on a government portal that ALREADY timed out once during
development, and it made this file take ~65s. `_FAKE_TELEMETRY` below
reproduces T1B.4's real normalized output shape — including the real
"Vellore" station row (station_id/lat/lon exactly as T1B.5's live run
found them) — so the `calibration_confidence` these tests exercise is
the same value production computes, just without the download.

Stage 1A is not mocked because there is nothing live to mock: no Stage
1A endpoint exists in this repo, so the route takes its documented
mock-fixture fallback path (see routes.py's module docstring). That's
the real behavior of this deployment today, not a test shortcut.

Uses `httpx.AsyncClient` + `ASGITransport` (async-native), not
`starlette.testclient.TestClient` — TestClient manages its own separate
event loop internally, which fought with db.py's module-level cached
engine/redis-client (bound to whichever loop first creates them) exactly
the way T1B.1's tests document ("another operation is in progress" /
"Event loop is closed"), confirmed by actually hitting it here, not
assumed. Running everything on pytest-asyncio's session-scoped loop
(pytest.ini) — the same one test_db.py already uses successfully —
avoids that entirely.

The full manual VERIFY run (uvicorn actually started, curl'd against the
REAL TN WRD path, cache states hit-redis/hit-db/miss all distinctly
observed, response validated against the shared contract) is in T1B.9's
commit message — that's the real-network evidence; these tests cover the
same behavior in an automated, hermetic, repeatable form.
"""

from __future__ import annotations

import pandas as pd
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from backend.shared.contracts import DownscaledForecastField
from backend.stage1b.config import settings
from backend.stage1b.db import DownscaledForecastFieldRow, get_db_session, get_redis_client, init_models
from backend.stage1b.routes import app

# Mirrors T1B.4's real normalized output columns exactly. The "Vellore"
# row carries the real coordinates T1B.5's live run found (12.948611,
# 79.138889 — 3.637km from the configured target site), so the
# nearest-station distance and resulting calibration_confidence match
# what production computes against the real dataset.
_FAKE_TELEMETRY = pd.DataFrame(
    [
        {
            "station_id": "Vellore",
            "station_name": "Vellore",
            "district": "Vellore",
            "latitude": 12.948611,
            "longitude": 79.138889,
            "timestamp": pd.Timestamp("2026-01-05 12:20:00"),
            "rainfall_mm": 1.0,
        },
        {
            "station_id": "Anaikidangu",
            "station_name": "Anaikidangu",
            "district": "Kanyakumari",
            "latitude": 8.234700,
            "longitude": 77.377894,
            "timestamp": pd.Timestamp("2026-02-21 16:00:00"),
            "rainfall_mm": 10.5,
        },
    ]
)


@pytest.fixture(autouse=True)
def _mock_tnwrd_network(monkeypatch):
    """Patch the symbol as routes.py imported it (`from ... import
    fetch_rainfall_telemetry`), not at its definition site — patching
    tnwrd.client.fetch_rainfall_telemetry would not affect the already-
    bound reference in routes' namespace."""
    monkeypatch.setattr(
        "backend.stage1b.routes.fetch_rainfall_telemetry",
        lambda: _FAKE_TELEMETRY,
    )


async def _clear_cache_keys():
    redis = get_redis_client()
    async for key in redis.scan_iter(match=f"downscaled:{settings.target_site_id}:*"):
        await redis.delete(key)


async def _cleanup_test_rows():
    async with get_db_session() as session:
        await session.execute(
            delete(DownscaledForecastFieldRow).where(
                DownscaledForecastFieldRow.site_id == settings.target_site_id
            )
        )
        await session.commit()


async def _count_rows_for_site() -> int:
    async with get_db_session() as session:
        result = await session.execute(
            text(
                "SELECT count(*) FROM downscaled_forecast_field WHERE site_id = :sid"
            ),
            {"sid": settings.target_site_id},
        )
        return result.scalar_one()


@pytest_asyncio.fixture
async def client():
    await init_models()
    await _clear_cache_keys()
    await _cleanup_test_rows()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await _cleanup_test_rows()
    await _clear_cache_keys()


@pytest.mark.asyncio
async def test_get_downscaled_forecast_returns_valid_field_for_target_site(client):
    resp = await client.get(
        "/api/forecast/downscaled",
        params={"lat": settings.target_site_lat, "lon": settings.target_site_lon},
    )
    assert resp.status_code == 200
    field = DownscaledForecastField.model_validate(resp.json())
    assert field.site_id == settings.target_site_id
    assert len(field.members) > 0
    # Confirms the mocked telemetry reproduces production's real result:
    # the "Vellore" station in _FAKE_TELEMETRY is 3.637km away, inside
    # T1B.5's 25km threshold — the same value T1B.9's live-network VERIFY
    # run produced. If this ever flips, the mock has drifted from the
    # real dataset's behavior, which is exactly what it should catch.
    assert field.calibration_confidence == "calibrated_nearby_station"
    assert resp.headers["X-Regional-Forecast-Source"] in (
        "stage1a_live",
        "mock_dev_fixture",
    )
    assert resp.headers["X-Cache"] == "miss"


@pytest.mark.asyncio
async def test_get_downscaled_forecast_is_idempotent(client):
    r1 = await client.get(
        "/api/forecast/downscaled",
        params={"lat": settings.target_site_lat, "lon": settings.target_site_lon},
    )
    r2 = await client.get(
        "/api/forecast/downscaled",
        params={"lat": settings.target_site_lat, "lon": settings.target_site_lon},
    )
    assert r1.json()["source_forecast_id"] == r2.json()["source_forecast_id"]
    assert r1.json()["generated_at"] == r2.json()["generated_at"]  # reused, not recomputed
    assert await _count_rows_for_site() == 1


@pytest.mark.asyncio
async def test_get_downscaled_forecast_second_request_is_cache_hit(client):
    await client.get(
        "/api/forecast/downscaled",
        params={"lat": settings.target_site_lat, "lon": settings.target_site_lon},
    )
    r2 = await client.get(
        "/api/forecast/downscaled",
        params={"lat": settings.target_site_lat, "lon": settings.target_site_lon},
    )
    assert r2.headers["X-Cache"] == "hit-redis"


@pytest.mark.asyncio
async def test_get_downscaled_forecast_404_far_from_target_site(client):
    resp = await client.get("/api/forecast/downscaled", params={"lat": 0.0, "lon": 0.0})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_downscaled_forecast_accepts_nearby_not_just_exact_coords(client):
    # A point ~0.5-0.7km from the target site, still within
    # SITE_MATCH_RADIUS_KM (10km).
    resp = await client.get(
        "/api/forecast/downscaled",
        params={
            "lat": settings.target_site_lat + 0.005,
            "lon": settings.target_site_lon + 0.005,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["site_id"] == settings.target_site_id


# ---------------------------------------------------------------------------
# Stage 1A integration seam (_get_regional_forecast's live-fetch branch).
#
# Flagged by T1B.12's coverage audit as completely untested — and it's the
# single highest-risk untested path in this module: it is the seam where
# this stage consumes the OTHER team member's independently-built Stage
# 1A. With STAGE1A_REGIONAL_FORECAST_URL unset (today's state) it never
# runs, so without these tests it would execute for the first time in
# production on merge day. The malformed-response test additionally pins
# the exact contract Stage 1A must return.
# ---------------------------------------------------------------------------


def _valid_stage1a_payload() -> dict:
    """Exactly the shape Stage 1A must return, per the shared
    RegionalEnsembleForecast contract in backend/shared/contracts.py."""
    return {
        "forecast_id": "stage1a-real-0001",
        "source": "GenCast",
        "region_bbox": {
            "min_lat": 12.7,
            "max_lat": 13.1,
            "min_lon": 79.0,
            "max_lon": 79.3,
        },
        "generated_at": "2026-08-19T06:00:00Z",
        "resolution_km": 28.0,
        "members": [
            {
                "member_id": 0,
                "trajectory": [
                    {"hour": 0, "rainfall_mm": 3.0},
                    {"hour": 6, "rainfall_mm": 7.5},
                ],
            }
        ],
    }


class _FakeStage1AResponse:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise RuntimeError("stage1a returned an error status")

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_regional_forecast_uses_stage1a_when_configured_and_healthy(monkeypatch):
    from backend.stage1b.routes import _get_regional_forecast

    monkeypatch.setattr(
        "backend.stage1b.routes.settings.stage1a_regional_forecast_url",
        "http://stage1a.internal/api/forecast/regional",
    )
    monkeypatch.setattr(
        "backend.stage1b.routes.requests.get",
        lambda url, **kw: _FakeStage1AResponse(_valid_stage1a_payload()),
    )

    forecast, source = await _get_regional_forecast()
    assert source == "stage1a_live"
    assert forecast.forecast_id == "stage1a-real-0001"
    assert forecast.members[0].trajectory[0].rainfall_mm == 3.0


@pytest.mark.asyncio
async def test_regional_forecast_falls_back_to_mock_when_stage1a_unreachable(
    monkeypatch,
):
    from backend.stage1b.routes import _get_regional_forecast

    monkeypatch.setattr(
        "backend.stage1b.routes.settings.stage1a_regional_forecast_url",
        "http://stage1a.internal/api/forecast/regional",
    )

    def _boom(url, **kw):
        raise ConnectionError("stage1a is down")

    monkeypatch.setattr("backend.stage1b.routes.requests.get", _boom)

    # Must degrade to the labeled mock, not propagate a 500 — Stage 1A
    # being down shouldn't take this stage's endpoint down with it.
    forecast, source = await _get_regional_forecast()
    assert source == "mock_dev_fixture"
    assert forecast.forecast_id.startswith("mock-regional-")


@pytest.mark.asyncio
async def test_regional_forecast_falls_back_when_stage1a_returns_wrong_shape(
    monkeypatch,
):
    """If Stage 1A's response doesn't satisfy the shared contract (a
    renamed field, a missing member list), this must fall back rather
    than 500 or — worse — silently accept a half-valid forecast."""
    from backend.stage1b.routes import _get_regional_forecast

    monkeypatch.setattr(
        "backend.stage1b.routes.settings.stage1a_regional_forecast_url",
        "http://stage1a.internal/api/forecast/regional",
    )
    broken = _valid_stage1a_payload()
    del broken["members"]  # contract violation
    monkeypatch.setattr(
        "backend.stage1b.routes.requests.get",
        lambda url, **kw: _FakeStage1AResponse(broken),
    )

    forecast, source = await _get_regional_forecast()
    assert source == "mock_dev_fixture"


@pytest.mark.asyncio
async def test_regional_forecast_falls_back_on_stage1a_error_status(monkeypatch):
    from backend.stage1b.routes import _get_regional_forecast

    monkeypatch.setattr(
        "backend.stage1b.routes.settings.stage1a_regional_forecast_url",
        "http://stage1a.internal/api/forecast/regional",
    )
    monkeypatch.setattr(
        "backend.stage1b.routes.requests.get",
        lambda url, **kw: _FakeStage1AResponse({}, status_ok=False),
    )

    forecast, source = await _get_regional_forecast()
    assert source == "mock_dev_fixture"
