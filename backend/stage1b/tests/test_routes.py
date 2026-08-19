"""Tests for T1B.9 — GET /api/forecast/downscaled.

Real integration tests against the actual local PostgreSQL+PostGIS and
Redis (same philosophy as test_db.py — this route genuinely needs both,
so there's nothing meaningful to mock at that layer). External calls
(Stage 1A, TN WRD) are the real ones this deployment is currently wired
to: Stage 1A falls back to the explicitly-labeled mock fixture (no live
endpoint exists yet — see routes.py's module docstring), and TN WRD's
nearest-station lookup is genuinely live (T1B.4/T1B.5).

Uses `httpx.AsyncClient` + `ASGITransport` (async-native), not
`starlette.testclient.TestClient` — TestClient manages its own separate
event loop internally, which fought with db.py's module-level cached
engine/redis-client (bound to whichever loop first creates them) exactly
the way T1B.1's tests document ("another operation is in progress" /
"Event loop is closed"), confirmed by actually hitting it here, not
assumed. Running everything on pytest-asyncio's session-scoped loop
(pytest.ini) — the same one test_db.py already uses successfully —
avoids that entirely.

The full manual VERIFY run (uvicorn actually started, curl'd, cache
states hit-redis/hit-db/miss all distinctly observed, response validated
against the shared contract) is in this task's commit message — these
tests cover the same behavior in an automated, repeatable form.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from backend.shared.contracts import DownscaledForecastField
from backend.stage1b.config import settings
from backend.stage1b.db import DownscaledForecastFieldRow, get_db_session, get_redis_client, init_models
from backend.stage1b.routes import app


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
