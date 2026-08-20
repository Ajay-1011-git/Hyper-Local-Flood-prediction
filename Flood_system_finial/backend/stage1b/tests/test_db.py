"""Tests for T1B.1 — DB & Redis connection layer.

These are integration tests against a real local PostgreSQL+PostGIS and
Redis instance (per DATABASE_URL / REDIS_URL in config.py) — there is
nothing to fake here, since T1B.1's entire job is "does the real
connection/schema work." Requires both services running locally; see
`backend/stage1b/.env.example` for the expected connection strings.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.stage1b.db import (
    DemMetadataRow,
    DownscaledForecastFieldRow,
    SensorReadingRow,
    dispose,
    get_db_session,
    get_engine,
    get_redis_client,
    init_models,
)


@pytest_asyncio.fixture(autouse=True, scope="module")
async def _schema():
    """Ensure the schema exists once for this test module, then dispose
    connections afterward so the event loop doesn't leak between tests."""
    await init_models()
    yield
    await dispose()


@pytest.mark.asyncio
async def test_init_models_creates_expected_tables():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(:names)"
            ),
            {
                "names": [
                    "downscaled_forecast_field",
                    "sensor_reading",
                    "dem_metadata",
                ]
            },
        )
        found = {row[0] for row in result}
    assert found == {"downscaled_forecast_field", "sensor_reading", "dem_metadata"}


@pytest.mark.asyncio
async def test_init_models_enables_postgis():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'postgis'")
        )
        assert result.first() is not None, "postgis extension is not enabled"


@pytest.mark.asyncio
async def test_init_models_is_idempotent():
    # Re-running must not raise (safe CREATE EXTENSION IF NOT EXISTS /
    # create_all against already-existing tables).
    await init_models()


@pytest.mark.asyncio
async def test_get_db_session_persists_and_reads_back_a_row():
    site_id = f"test_site_{uuid.uuid4().hex[:8]}"
    forecast_id = f"forecast_{uuid.uuid4().hex[:8]}"

    async with get_db_session() as session:
        row = DownscaledForecastFieldRow(
            site_id=site_id,
            site_lat=12.9165,
            site_lon=79.1325,
            site_geom="SRID=4326;POINT(79.1325 12.9165)",
            calibration_confidence="computed_only_no_nearby_station",
            source_forecast_id=forecast_id,
            generated_at=datetime.now(timezone.utc),
            members=[{"member_id": 0, "trajectory": [{"hour": 0, "inflow_mm": 1.0}]}],
        )
        session.add(row)
        await session.commit()

    async with get_db_session() as session:
        result = await session.execute(
            text(
                "SELECT site_id, calibration_confidence FROM downscaled_forecast_field "
                "WHERE site_id = :site_id"
            ),
            {"site_id": site_id},
        )
        fetched = result.first()
    assert fetched is not None
    assert fetched[0] == site_id
    assert fetched[1] == "computed_only_no_nearby_station"

    # Cleanup so repeated test runs don't accumulate rows.
    async with get_db_session() as session:
        await session.execute(
            text("DELETE FROM downscaled_forecast_field WHERE site_id = :site_id"),
            {"site_id": site_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_downscaled_forecast_field_unique_constraint_rejects_duplicate():
    site_id = f"test_site_{uuid.uuid4().hex[:8]}"
    forecast_id = f"forecast_{uuid.uuid4().hex[:8]}"

    def make_row():
        return DownscaledForecastFieldRow(
            site_id=site_id,
            site_lat=12.9165,
            site_lon=79.1325,
            site_geom="SRID=4326;POINT(79.1325 12.9165)",
            calibration_confidence="computed_only_no_nearby_station",
            source_forecast_id=forecast_id,
            generated_at=datetime.now(timezone.utc),
            members=[],
        )

    async with get_db_session() as session:
        session.add(make_row())
        await session.commit()

    with pytest.raises(Exception):
        async with get_db_session() as session:
            session.add(make_row())
            await session.commit()

    # Cleanup.
    async with get_db_session() as session:
        await session.execute(
            text("DELETE FROM downscaled_forecast_field WHERE site_id = :site_id"),
            {"site_id": site_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_sensor_reading_unique_constraint_rejects_duplicate():
    sensor_id = f"test_sensor_{uuid.uuid4().hex[:8]}"
    ts = datetime.now(timezone.utc)

    def make_row():
        return SensorReadingRow(
            sensor_id=sensor_id,
            site_id="vellore_demo_site_01",
            distance_cm=42.0,
            timestamp=ts,
        )

    async with get_db_session() as session:
        session.add(make_row())
        await session.commit()

    with pytest.raises(Exception):
        async with get_db_session() as session:
            session.add(make_row())
            await session.commit()

    # Cleanup.
    async with get_db_session() as session:
        await session.execute(
            text("DELETE FROM sensor_reading WHERE sensor_id = :sensor_id"),
            {"sensor_id": sensor_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_dem_metadata_row_roundtrip():
    bbox_key = uuid.uuid4().hex[:8]
    raster_path = f"/tmp/test_dem_{bbox_key}.tif"

    async with get_db_session() as session:
        row = DemMetadataRow(
            min_lat=12.8,
            max_lat=float(f"12.9{ord(bbox_key[0])}"),  # unique-ish bbox per run
            min_lon=79.0,
            max_lon=79.2,
            raster_path=raster_path,
        )
        session.add(row)
        await session.commit()

    async with get_db_session() as session:
        result = await session.execute(
            text("SELECT raster_path FROM dem_metadata WHERE raster_path = :p"),
            {"p": raster_path},
        )
        fetched = result.first()
    assert fetched is not None
    assert fetched[0] == raster_path

    # Cleanup.
    async with get_db_session() as session:
        await session.execute(
            text("DELETE FROM dem_metadata WHERE raster_path = :p"),
            {"p": raster_path},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_get_redis_client_pings():
    client = get_redis_client()
    assert await client.ping() is True
