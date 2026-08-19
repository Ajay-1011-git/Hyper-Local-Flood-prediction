"""Integration tests for Stage 1A's FastAPI routes (T1A.8), external calls mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from stage1a import routes
from stage1a.cwc.errors import CWCUnavailableError
from stage1a.gencast.errors import GenCastUnavailableError
from stage1a.gencast.parser import build_forecast_id
from stage1a.gencast.provenance import ForecastPath, ForecastProvenance, RegionalForecastResult
from stage1a.shared.contracts import (
    BoundingBox,
    EnsembleMember,
    RegionalEnsembleForecast,
    RiverStageForecast,
    StageTimestepValue,
    TimestepValue,
)

FORECAST_START = datetime(2026, 8, 19, tzinfo=timezone.utc)


def _sample_regional_result() -> RegionalForecastResult:
    forecast = RegionalEnsembleForecast(
        forecast_id=build_forecast_id(routes.TARGET_REGION_BBOX, FORECAST_START),
        source="WeatherNext2_Cyclones_Mini",
        region_bbox=routes.TARGET_REGION_BBOX,
        generated_at=FORECAST_START,
        resolution_km=111.0,
        members=[
            EnsembleMember(
                member_id=i,
                trajectory=[TimestepValue(hour=h, rainfall_mm=1.0) for h in (6, 12)],
            )
            for i in range(8)
        ],
    )
    return RegionalForecastResult(
        forecast=forecast,
        provenance=ForecastProvenance(
            path=ForecastPath.WN2_MINI,
            retrieved_at=datetime.now(timezone.utc),
            synthetic=False,
        ),
    )


def _sample_river_forecast() -> RiverStageForecast:
    return RiverStageForecast(
        station_id="TestStation",
        station_name="TestStation",
        lat=12.92,
        lon=79.14,
        forecast_horizon_hours=0,
        trajectory=[StageTimestepValue(hour=0, water_level_m=1.5)],
        station_proximity_verified=True,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(routes.app)


# --------------------------------------------------------- /api/forecast/regional


def test_regional_route_serves_valid_cached_forecast(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _sample_regional_result()

    async def fake_read_latest_forecast_id() -> str:
        return result.forecast.forecast_id

    async def fake_read_cached_forecast(
        forecast_id: str,
    ) -> tuple[RegionalEnsembleForecast, ForecastProvenance]:
        assert forecast_id == result.forecast.forecast_id
        return result.forecast, result.provenance

    monkeypatch.setattr(routes, "read_latest_forecast_id", fake_read_latest_forecast_id)
    monkeypatch.setattr(routes, "read_cached_forecast", fake_read_cached_forecast)

    response = client.get("/api/forecast/regional")
    assert response.status_code == 200
    body = response.json()
    assert RegionalEnsembleForecast.model_validate(body) == result.forecast
    assert response.headers["x-forecast-source-path"] == "ForecastPath.WN2_MINI"
    assert response.headers["x-forecast-synthetic"] == "false"


def test_regional_route_ignores_cache_for_a_different_region(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached forecast for the wrong bbox must trigger regeneration, not be served."""
    wrong_region = _sample_regional_result()
    wrong_region.forecast.region_bbox = BoundingBox(
        min_lat=0.0, max_lat=1.0, min_lon=0.0, max_lon=1.0
    )
    fresh = _sample_regional_result()

    async def fake_read_latest_forecast_id() -> str:
        return wrong_region.forecast.forecast_id

    async def fake_read_cached_forecast(
        forecast_id: str,
    ) -> tuple[RegionalEnsembleForecast, ForecastProvenance]:
        return wrong_region.forecast, wrong_region.provenance

    async def fake_generate_and_persist(
        bbox: BoundingBox, forecast_start: datetime
    ) -> RegionalForecastResult:
        assert bbox == routes.TARGET_REGION_BBOX
        return fresh

    monkeypatch.setattr(routes, "read_latest_forecast_id", fake_read_latest_forecast_id)
    monkeypatch.setattr(routes, "read_cached_forecast", fake_read_cached_forecast)
    monkeypatch.setattr(routes, "generate_and_persist", fake_generate_and_persist)

    response = client.get("/api/forecast/regional")
    assert response.status_code == 200
    assert response.json()["forecast_id"] == fresh.forecast.forecast_id


def test_regional_route_generates_on_cache_miss(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _sample_regional_result()

    async def fake_read_latest_forecast_id() -> Optional[str]:
        return None

    async def fake_generate_and_persist(
        bbox: BoundingBox, forecast_start: datetime
    ) -> RegionalForecastResult:
        assert bbox == routes.TARGET_REGION_BBOX
        return result

    monkeypatch.setattr(routes, "read_latest_forecast_id", fake_read_latest_forecast_id)
    monkeypatch.setattr(routes, "generate_and_persist", fake_generate_and_persist)

    response = client.get("/api/forecast/regional")
    assert response.status_code == 200
    assert response.json()["forecast_id"] == result.forecast.forecast_id


def test_regional_route_returns_503_when_nothing_is_available(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_read_latest_forecast_id() -> Optional[str]:
        return None

    async def fake_generate_and_persist(
        bbox: BoundingBox, forecast_start: datetime
    ) -> RegionalForecastResult:
        raise GenCastUnavailableError("nothing available")

    monkeypatch.setattr(routes, "read_latest_forecast_id", fake_read_latest_forecast_id)
    monkeypatch.setattr(routes, "generate_and_persist", fake_generate_and_persist)

    response = client.get("/api/forecast/regional")
    assert response.status_code == 503


# ----------------------------------------------------- /api/forecast/river-stage


def test_river_stage_route_serves_valid_forecast(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    station = {
        "station_id": "TestStation",
        "station_name": "TestStation",
        "lat": 12.92,
        "lon": 79.14,
        "resource_id": "r1",
    }

    async def fake_fetch_station_list_cached(
        settings: Any = None,
    ) -> list[dict[str, Any]]:
        return [station]

    def fake_fetch_station_data(
        station_arg: dict[str, Any], hours: int = 72, settings: Any = None
    ) -> list[dict[str, Any]]:
        assert station_arg["station_id"] == "TestStation"
        return [
            {
                "Station": "TestStation",
                "Data Acquisition Time": "19-08-2026 12:00",
                "River Water Level Telemetry Hourly (meter)": "1.5",
            }
        ]

    monkeypatch.setattr(routes, "fetch_station_list_cached", fake_fetch_station_list_cached)
    monkeypatch.setattr(routes, "fetch_station_data", fake_fetch_station_data)

    response = client.get("/api/forecast/river-stage?lat=12.9165&lon=79.1325")
    assert response.status_code == 200
    body = response.json()
    assert RiverStageForecast.model_validate(body).station_id == "TestStation"


def test_river_stage_route_requires_lat_lon(client: TestClient) -> None:
    response = client.get("/api/forecast/river-stage")
    assert response.status_code == 422


def test_river_stage_route_rejects_out_of_range_coordinates(client: TestClient) -> None:
    response = client.get("/api/forecast/river-stage?lat=200&lon=79.1325")
    assert response.status_code == 422


def test_river_stage_route_returns_503_on_cwc_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_station_list_cached(
        settings: Any = None,
    ) -> list[dict[str, Any]]:
        raise CWCUnavailableError("portal unreachable")

    monkeypatch.setattr(routes, "fetch_station_list_cached", fake_fetch_station_list_cached)

    response = client.get("/api/forecast/river-stage?lat=12.9165&lon=79.1325")
    assert response.status_code == 503
