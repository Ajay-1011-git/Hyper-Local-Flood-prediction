"""Stage 1A FastAPI routes (T1A.8) — flood_system_TRD.md §5.1.

    GET /api/forecast/regional
      -> latest cached RegionalEnsembleForecast for the configured target
         region, triggering forecast acquisition if none exists yet.

    GET /api/forecast/river-stage?lat={}&lon={}
      -> RiverStageForecast for the station nearest the given coordinates.

Both responses are declared via `response_model`, so FastAPI/Pydantic
validates them against §B.2 before they leave the process (§A quality
gate: "Pydantic validates ALL external data... never pass raw dict/JSON
deeper into the codebase unvalidated" — the same principle applied on the
way out, not just the way in).

Design note on triggering generation: `get_regional_forecast_route` awaits
`generate_and_persist` in-process rather than enqueuing
`generate_regional_forecast_task` via Celery and blocking on `.get()`. The
Celery task exists and is exercised by T1A.5's own tests/VERIFY; calling
`.delay(...).get()` from inside an async request handler risks a sync-over-
async deadlock, and — per the T1A.2-T1A.5 amendment — the real working path
(WeatherNext 2 Mini) is now a fast file-parse, not the TPU-scale job Celery
was originally justified against. If a future source genuinely needs
out-of-band execution, route through the Celery task instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from stage1a.config import get_settings
from stage1a.cwc.client import fetch_station_data, fetch_station_list_cached
from stage1a.cwc.errors import CWCError
from stage1a.cwc.parser import find_nearest_station, parse_station_forecast
from stage1a.gencast.errors import GenCastError
from stage1a.gencast.tasks import generate_and_persist, read_cached_forecast, read_latest_forecast_id
from stage1a.shared.contracts import BoundingBox, RegionalEnsembleForecast, RiverStageForecast
from stage1a.wn2mini.errors import WN2Error

#: The system's configured target region for the regional forecast route.
#: Matches the bounding box the real, confirmed-working WeatherNext 2 Mini
#: export covers (see wn2mini/loader.py's module docstring) — Tamil Nadu,
#: lat 8-14 deg N, lon 76-82 deg E. Not derived from TARGET_SITE_LAT/LON
#: with an arbitrary buffer, since this box is what actually has real data
#: behind it.
TARGET_REGION_BBOX = BoundingBox(min_lat=8.0, max_lat=14.0, min_lon=76.0, max_lon=82.0)

app = FastAPI(title="Stage 1A — Regional Forecast Acquisition")


def _current_forecast_window() -> datetime:
    """The forecast_start used when no cached forecast exists yet.

    Real "now" — not aligned to any fixed schedule. Harmless for the
    WeatherNext 2 Mini path (it does not filter by forecast_start, per
    fallback.py's `_try_wn2_mini`); for the legacy GenCast fallback path it
    is the window `find_precomputed_file` will look for.
    """
    return datetime.now(timezone.utc)


@app.get("/api/forecast/regional", response_model=RegionalEnsembleForecast)
async def get_regional_forecast_route() -> JSONResponse:
    """Return the latest forecast, generating one if none is cached yet."""
    forecast_id = await read_latest_forecast_id()
    if forecast_id is not None:
        cached = await read_cached_forecast(forecast_id)
        if cached is not None:
            forecast, provenance = cached
            if forecast.region_bbox == TARGET_REGION_BBOX:
                return _regional_response(forecast, provenance)
            # The "latest" pointer is global, not per-region (T1A.5). A
            # cached forecast for a different bbox (e.g. leftover from
            # manual testing against another region) must not be served
            # for this route's fixed target region — fall through and
            # generate a fresh one instead of returning stale/wrong data.

    try:
        result = await generate_and_persist(TARGET_REGION_BBOX, _current_forecast_window())
    except (GenCastError, WN2Error) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"No regional forecast is currently available: {exc}",
        ) from exc

    return _regional_response(result.forecast, result.provenance)


def _regional_response(forecast: RegionalEnsembleForecast, provenance: object) -> JSONResponse:
    """Build the JSON response, surfacing provenance as headers (not schema fields).

    Keeps `RegionalEnsembleForecast` itself byte-identical to §B.2 — nothing
    about which source served this response is added to the body.
    """
    headers = {}
    if provenance is not None:
        headers["X-Forecast-Source-Path"] = str(getattr(provenance, "path", ""))
        headers["X-Forecast-Synthetic"] = str(getattr(provenance, "synthetic", "")).lower()
    return JSONResponse(content=forecast.model_dump(mode="json"), headers=headers)


@app.get("/api/forecast/river-stage", response_model=RiverStageForecast)
async def get_river_stage_forecast_route(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
) -> RiverStageForecast:
    """Return the RiverStageForecast for the station nearest `(lat, lon)`."""
    settings = get_settings()
    try:
        stations = await fetch_station_list_cached(settings)
        nearest = find_nearest_station(lat, lon, stations)
        raw_data = fetch_station_data(nearest, hours=72, settings=settings)
        return parse_station_forecast(
            raw_data,
            nearest,
            lat,
            lon,
            settings.cwc_station_proximity_threshold_km,
        )
    except CWCError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"No river stage data is currently available: {exc}",
        ) from exc
