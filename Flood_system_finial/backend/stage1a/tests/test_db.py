"""Tests for the Stage 1A connection/persistence layer (T1A.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    import xarray as xr

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


def _wn2_shaped_dataset(num_members: int = 8) -> "xr.Dataset":
    """A dataset matching the confirmed real WeatherNext 2 Mini structure.

    Duplicated (deliberately small) from tests/test_wn2mini.py's builder
    rather than shared, to keep this test independent of that module.
    """
    import numpy as np
    import xarray as xr

    lead_hours = tuple(range(6, 121, 6))
    lats = np.arange(12.5, 13.5, 0.25)
    lons = np.arange(78.8, 79.6, 0.25)
    shape = (num_members, len(lead_hours), 1, len(lats), len(lons))
    rng = np.random.default_rng(7)
    values = rng.gamma(1.5, 0.004, size=shape).astype(np.float32)
    precip = xr.DataArray(
        values,
        dims=["sample", "time", "batch", "lat", "lon"],
        coords={
            "sample": np.arange(num_members),
            "time": np.array(
                [np.timedelta64(h, "h") for h in lead_hours], dtype="timedelta64[ns]"
            ),
            "lat": lats.astype(np.float32),
            "lon": lons.astype(np.float32),
        },
    )
    return xr.Dataset({"total_precipitation_6hr": precip})


@requires_postgres
@requires_redis
@pytest.mark.asyncio
async def test_repeated_task_runs_leave_exactly_one_row(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T1A.5 idempotency: three runs of the same window -> one row.

    GEFS is simulated unavailable so this exercises the WN2 Mini path
    deterministically. Without it (2026-08-20 amendment made GEFS real
    and primary) this test would make three real live NOMADS fetches --
    ~372 network requests each, against T1A.12's own "mock all external
    network calls" rule -- and would then assert against a `wn2mini-`
    forecast_id that a successful GEFS run would never produce. The
    behaviour under test is persistence idempotency, not source
    selection; GEFS's own behaviour is covered in tests/test_gefs_*.py.
    """
    from pathlib import Path

    import stage1a.forecast.fallback as fallback_module
    from stage1a.config import Stage1ASettings
    from stage1a.forecast.tasks import generate_and_persist
    from stage1a.gefs.errors import GEFSUnavailableError
    from stage1a.shared.contracts import BoundingBox
    from stage1a.wn2mini.parser import build_forecast_id

    def _gefs_unavailable(*args: object, **kwargs: object) -> None:
        raise GEFSUnavailableError("simulated: GEFS unavailable for this test")

    monkeypatch.setattr(fallback_module, "fetch_gefs_forecast", _gefs_unavailable)

    bbox = BoundingBox(min_lat=12.5, max_lat=13.3, min_lon=78.8, max_lon=79.5)
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)

    wn2_path = Path(str(tmp_path)) / "tn_flood_forecast.nc"
    _wn2_shaped_dataset(num_members=8).to_netcdf(wn2_path, engine="h5netcdf")
    settings = Stage1ASettings(wn2_mini_forecast_path=wn2_path)

    await init_db()
    for _ in range(3):
        await generate_and_persist(bbox, start, settings)

    forecast_id = build_forecast_id(bbox, start)
    async with get_engine().connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM regional_ensemble_forecast "
                    "WHERE forecast_id = :fid"
                ),
                {"fid": forecast_id},
            )
        ).scalar_one()
    assert count == 1
