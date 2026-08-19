"""Tests for the Stage 1A connection/persistence layer (T1A.1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from stage1a.db import (
    Stage1ADatabaseError,
    _async_database_url,
    get_db_session,
    get_engine,
    get_redis_client,
    init_db,
    upsert_regional_forecast,
    upsert_river_stage_forecast,
)
from stage1a.shared.contracts import (
    BoundingBox,
    EnsembleMember,
    RegionalEnsembleForecast,
    RiverStageForecast,
    StageTimestepValue,
    TimestepValue,
)
from stage1a.tests.conftest import requires_postgres, requires_redis


# ---------------------------------------------------------------- pure logic


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgresql://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        (
            "postgres://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        (
            "postgresql+psycopg2://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        (
            "postgresql+asyncpg://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
    ],
)
def test_async_database_url_normalises_driver(given: str, expected: str) -> None:
    assert _async_database_url(given) == expected


def test_async_database_url_rejects_unknown_scheme() -> None:
    with pytest.raises(Stage1ADatabaseError):
        _async_database_url("mysql://u:p@h/d")


# --------------------------------------------------------------- integration


def _sample_regional(forecast_id: str = "test-forecast-1") -> RegionalEnsembleForecast:
    return RegionalEnsembleForecast(
        forecast_id=forecast_id,
        region_bbox=BoundingBox(
            min_lat=12.5, max_lat=13.3, min_lon=78.8, max_lon=79.5
        ),
        generated_at=datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc),
        members=[
            EnsembleMember(
                member_id=i,
                trajectory=[TimestepValue(hour=h, rainfall_mm=0.5 * h) for h in range(3)],
            )
            for i in range(2)
        ],
    )


def _sample_river(station_id: str = "test-station-1") -> RiverStageForecast:
    return RiverStageForecast(
        station_id=station_id,
        station_name="Test Station",
        lat=12.9165,
        lon=79.1325,
        forecast_horizon_hours=72,
        trajectory=[StageTimestepValue(hour=h, water_level_m=1.0 + h) for h in range(3)],
        station_proximity_verified=False,
    )


@requires_redis
@pytest.mark.asyncio
async def test_redis_client_pings() -> None:
    assert await get_redis_client().ping() is True


@requires_postgres
@pytest.mark.asyncio
async def test_init_db_is_idempotent_and_creates_both_tables() -> None:
    await init_db()
    await init_db()  # second run must be a no-op, not an error

    async with get_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename IN "
                    "('regional_ensemble_forecast', 'river_stage_forecast')"
                )
            )
        ).scalars().all()
    assert set(rows) == {"regional_ensemble_forecast", "river_stage_forecast"}


@requires_postgres
@pytest.mark.asyncio
async def test_postgis_extension_enabled() -> None:
    async with get_engine().connect() as conn:
        version = (await conn.execute(text("SELECT postgis_version()"))).scalar_one()
    assert version


@requires_postgres
@pytest.mark.asyncio
async def test_upsert_regional_forecast_is_idempotent() -> None:
    await init_db()
    forecast = _sample_regional()

    for _ in range(2):
        async for session in get_db_session():
            await upsert_regional_forecast(session, forecast)

    async with get_engine().connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM regional_ensemble_forecast "
                    "WHERE forecast_id = :fid"
                ),
                {"fid": forecast.forecast_id},
            )
        ).scalar_one()
    assert count == 1


@requires_postgres
@pytest.mark.asyncio
async def test_upsert_river_stage_forecast_is_idempotent_and_geocoded() -> None:
    await init_db()
    forecast = _sample_river()

    for _ in range(2):
        async for session in get_db_session():
            await upsert_river_stage_forecast(session, forecast)

    async with get_engine().connect() as conn:
        count, wkt = (
            await conn.execute(
                text(
                    "SELECT count(*), min(ST_AsText(geom::geometry)) "
                    "FROM river_stage_forecast WHERE station_id = :sid"
                ),
                {"sid": forecast.station_id},
            )
        ).one()
    assert count == 1
    assert wkt == f"POINT({forecast.lon} {forecast.lat})"
