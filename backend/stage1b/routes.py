"""FastAPI routes — T1B.9 (GET /api/forecast/downscaled) and
T1B.11 (POST /api/sensor/reading).

## T1B.9 route contract: a real spec conflict, reconciled

`Flood_system_TRD.md` §5.1 (the project's declared source of truth) says:
    GET /api/forecast/downscaled?lat={}&lon={}

but this Stage 1B build document's own T1B.9 task text says:
    GET /api/forecast/downscaled?site_id={}

Per this module's CLAUDE.md ("if any prompt here seems to disagree with
[the Architecture/TRD] documents, those documents win — stop and
reconcile before proceeding"), and confirmed with the human rather than
silently picking one: **the TRD's `?lat=&lon=` form is implemented.**
Internally this resolves to `TARGET_SITE_ID` — the only demo site this
system has terrain/calibration data for — validating the requested
coordinates are actually near that site (real haversine distance, T1B.5's
formula, reused rather than re-derived) rather than silently answering
for arbitrary coordinates nowhere near Vellore.

## Regional forecast source

Stage 1A (which produces `RegionalEnsembleForecast`) has no live endpoint
in this repo yet — built independently by a different team member. Per
this project's explicit allowance for this ("fetching the current
RegionalEnsembleForecast from Stage 1A's endpoint (or a configured mock
during standalone development)"): if `STAGE1A_REGIONAL_FORECAST_URL` is
configured, this route fetches and validates a real forecast from it;
otherwise it falls back to an explicitly-labeled mock fixture, generated
deterministically per a 6-hour forecast window (so repeated requests
within the same window are idempotent — same `forecast_id`, same DB row,
per the quality gate). Which path was used is exposed via the
`X-Regional-Forecast-Source` response header (`stage1a_live` |
`mock_dev_fixture`) — a non-breaking, out-of-band signal, since changing
the shared `DownscaledForecastField` contract itself needs sign-off from
whoever owns Stage 1A's copy, per T1A.4's precedent for the same kind of
decision.

## Calibration coefficients at request time

T1B.6's `fit_calibration` needs real matched (TN WRD reading, coarse
regional estimate) pairs to fit non-trivial terrain coefficients — which,
like the point above, isn't possible yet without Stage 1A's historical
archive. This route therefore uses `IDENTITY_COEFFICIENTS` for the actual
downscaling math (a real, honest choice — not a shortcut: fabricating
historical regional estimates to force a non-trivial fit would violate
this project's core anti-hallucination rule). `calibration_confidence`
on the response is still the REAL, independently-computable T1B.5 result
(a real nearby TN WRD station does exist for Vellore) — these are two
separate signals and this route doesn't conflate them.

## Persistence + caching

Idempotent per forecast window: DB has a unique constraint on
`(site_id, source_forecast_id)` (T1B.1); a request for a window already
computed reads that existing row rather than recomputing or duplicating
it. Also cached in Redis (`downscaled:{site_id}:{forecast_id}`), TTL set
to the forecast window's remaining lifetime, so repeated requests within
a window skip the DB round-trip entirely.
`X-Cache: hit-redis | hit-db | hit-db-race | miss` and
`X-Regional-Forecast-Source` headers make both of these decisions
observable rather than opaque.

## T1B.11 — POST /api/sensor/reading + WS /ws/site/{site_id}

See sensor/ingest.py's module docstring for the two spec reconciliations
in this route: the request body omitting `site_id` (TRD §5.1 — resolved
server-side to `TARGET_SITE_ID`, same single-demo-site pattern as
T1B.9), and the WebSocket event name/semantics (TRD's `sensor_assimilated`
name kept, but `assimilated: False` and `updated_region: None` since no
real Stage 2 assimilation exists yet — confirmed with the human).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests
from fastapi import FastAPI, Header, HTTPException, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from backend.shared.contracts import (
    BoundingBox,
    DownscaledForecastField,
    EnsembleMember,
    RegionalEnsembleForecast,
    SensorReading,
    TimestepValue,
)
from backend.stage1b.config import settings
from backend.stage1b.db import (
    DemMetadataRow,
    DownscaledForecastFieldRow,
    get_db_session,
    get_redis_client,
)
from backend.stage1b.downscaling.calibration import IDENTITY_COEFFICIENTS
from backend.stage1b.downscaling.orchestrator import (
    SiteOutsideTerrainGridError,
    generate_downscaled_field,
)
from backend.stage1b.sensor.ingest import (
    SensorReadingIngestRequest,
    connection_manager,
    ingest_sensor_reading,
)
from backend.stage1b.tnwrd.client import fetch_rainfall_telemetry
from backend.stage1b.tnwrd.nearest_station import (
    _haversine_km,
    find_nearest_tnwrd_station,
    get_calibration_confidence,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Stage 1B — Hyperlocal Flood Prediction")

# How close a requested (lat, lon) must be to TARGET_SITE_LAT/LON to be
# served by this demo deployment's single calibrated site. Flagged per
# this project's convention for unverified defaults, same as the
# station-proximity threshold: a reasonable starting point, not an
# independently proven-correct radius.
SITE_MATCH_RADIUS_KM = 10.0

# Regional forecasts are treated as valid for a 6-hour window (matches the
# Architecture doc's mention of a 72h/50-member ensemble refreshed
# periodically, not continuously) — also flagged as reasonable-not-
# verified.
FORECAST_WINDOW_HOURS = 6


def _current_forecast_window() -> tuple[datetime, datetime]:
    """Returns (window_start, window_end), both UTC."""
    now = datetime.now(timezone.utc)
    window_index = now.hour // FORECAST_WINDOW_HOURS
    window_start = now.replace(
        hour=window_index * FORECAST_WINDOW_HOURS, minute=0, second=0, microsecond=0
    )
    return window_start, window_start + timedelta(hours=FORECAST_WINDOW_HOURS)


def _mock_regional_forecast() -> RegionalEnsembleForecast:
    """An explicitly-labeled MOCK RegionalEnsembleForecast, standing in for
    Stage 1A's not-yet-existing live endpoint. Deterministic per the
    current forecast window (see module docstring) so repeated requests
    within that window are idempotent, not a fresh random forecast_id
    each time."""
    window_start, _ = _current_forecast_window()
    forecast_id = f"mock-regional-{window_start.strftime('%Y%m%dT%H%M')}Z"
    return RegionalEnsembleForecast(
        forecast_id=forecast_id,
        source="GenCast",
        region_bbox=BoundingBox(min_lat=12.7, max_lat=13.1, min_lon=79.0, max_lon=79.3),
        generated_at=window_start,
        members=[
            EnsembleMember(
                member_id=i,
                trajectory=[
                    TimestepValue(hour=h, rainfall_mm=0.0) for h in range(0, 73, 6)
                ],
            )
            for i in range(3)
        ],
    )


async def _get_regional_forecast() -> tuple[RegionalEnsembleForecast, str]:
    """Returns (forecast, source) where source is 'stage1a_live' or
    'mock_dev_fixture'."""
    if settings.stage1a_regional_forecast_url:
        try:
            resp = requests.get(settings.stage1a_regional_forecast_url, timeout=15)
            resp.raise_for_status()
            return RegionalEnsembleForecast.model_validate(resp.json()), "stage1a_live"
        except Exception as exc:
            logger.error(
                "Failed to fetch real regional forecast from Stage 1A "
                "(%s): %s — falling back to mock fixture.",
                settings.stage1a_regional_forecast_url,
                exc,
            )
    return _mock_regional_forecast(), "mock_dev_fixture"


async def _get_terrain_grid_path(site_lat: float, site_lon: float) -> str:
    async with get_db_session() as session:
        result = await session.execute(
            select(DemMetadataRow).where(
                DemMetadataRow.min_lat <= site_lat,
                DemMetadataRow.max_lat >= site_lat,
                DemMetadataRow.min_lon <= site_lon,
                DemMetadataRow.max_lon >= site_lon,
                DemMetadataRow.terrain_grid_path.is_not(None),
            )
        )
        row = result.scalars().first()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No processed terrain grid (T1B.3 output) covers the "
                "configured target site yet — run T1B.2's DEM fetch and "
                "T1B.3's terrain processing first."
            ),
        )
    # The query filters terrain_grid_path.is_not(None), so this is
    # guaranteed non-null here even though the column is Optional[str] in
    # general (T1B.1's schema: null until T1B.3 has processed a raster).
    assert row.terrain_grid_path is not None
    return row.terrain_grid_path


async def _get_calibration_confidence(site_lat: float, site_lon: float) -> str:
    """Real T1B.5 nearest-station lookup — this is cheap enough (a single
    CKAN + CSV fetch) to do per-request; unlike calibration coefficient
    fitting (which needs Stage 1A's not-yet-available historical archive,
    see module docstring), this doesn't depend on anything missing."""
    telemetry = fetch_rainfall_telemetry()
    _station, distance_km = find_nearest_tnwrd_station(site_lat, site_lon, telemetry)
    return get_calibration_confidence(distance_km)


def _require_target_site() -> tuple[float, float]:
    """`TARGET_SITE_LAT`/`TARGET_SITE_LON` are `Optional[float]` in
    config.py (per §B.1's `.env.example`, which ships them blank — the
    human must fill in a real target site). This route genuinely cannot
    function without them, so it fails fast with a clear error rather than
    letting `None` silently flow into distance/terrain-lookup math — also
    narrows the type from `float | None` to `float` for the type checker,
    rather than threading `Optional` through every downstream call."""
    if settings.target_site_lat is None or settings.target_site_lon is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "TARGET_SITE_LAT / TARGET_SITE_LON are not configured "
                "(see backend/stage1b/.env) — this deployment has no site "
                "to serve forecasts for."
            ),
        )
    return settings.target_site_lat, settings.target_site_lon


def _row_to_field(row: DownscaledForecastFieldRow) -> DownscaledForecastField:
    return DownscaledForecastField(
        site_id=row.site_id,
        site_lat=row.site_lat,
        site_lon=row.site_lon,
        resolution_km=row.resolution_km,
        calibration_source=row.calibration_source,
        calibration_confidence=row.calibration_confidence,
        source_forecast_id=row.source_forecast_id,
        generated_at=row.generated_at,
        members=row.members,
    )


@app.get("/api/forecast/downscaled", response_model=DownscaledForecastField)
async def get_downscaled_forecast(lat: float, lon: float, response: Response):
    site_lat, site_lon = _require_target_site()
    distance_km = _haversine_km(lat, lon, site_lat, site_lon)
    if distance_km > SITE_MATCH_RADIUS_KM:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No downscaled forecast available near ({lat}, {lon}) — "
                f"{distance_km:.1f}km from this deployment's only "
                f"configured site ({settings.target_site_id}), outside "
                f"the {SITE_MATCH_RADIUS_KM}km match radius."
            ),
        )

    regional_forecast, forecast_source = await _get_regional_forecast()
    cache_key = f"downscaled:{settings.target_site_id}:{regional_forecast.forecast_id}"

    redis = get_redis_client()
    cached = await redis.get(cache_key)
    if cached is not None:
        response.headers["X-Regional-Forecast-Source"] = forecast_source
        response.headers["X-Cache"] = "hit-redis"
        return DownscaledForecastField.model_validate_json(cached)

    async with get_db_session() as session:
        existing = await session.execute(
            select(DownscaledForecastFieldRow).where(
                DownscaledForecastFieldRow.site_id == settings.target_site_id,
                DownscaledForecastFieldRow.source_forecast_id
                == regional_forecast.forecast_id,
            )
        )
        row = existing.scalars().first()
        cache_status = "hit-db" if row is not None else "miss"

        if row is not None:
            field = _row_to_field(row)
        else:
            terrain_grid_path = await _get_terrain_grid_path(site_lat, site_lon)
            calibration_confidence = await _get_calibration_confidence(
                site_lat, site_lon
            )

            try:
                field = generate_downscaled_field(
                    regional_forecast=regional_forecast,
                    site_id=settings.target_site_id,
                    site_lat=site_lat,
                    site_lon=site_lon,
                    terrain_grid_path=terrain_grid_path,
                    calibration_coeffs=IDENTITY_COEFFICIENTS,
                    calibration_confidence=calibration_confidence,
                )
            except SiteOutsideTerrainGridError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

            new_row = DownscaledForecastFieldRow(
                site_id=field.site_id,
                site_lat=field.site_lat,
                site_lon=field.site_lon,
                site_geom=f"SRID=4326;POINT({field.site_lon} {field.site_lat})",
                resolution_km=field.resolution_km,
                calibration_source=field.calibration_source,
                calibration_confidence=field.calibration_confidence,
                source_forecast_id=field.source_forecast_id,
                generated_at=field.generated_at,
                members=[m.model_dump(mode="json") for m in field.members],
            )
            session.add(new_row)
            try:
                await session.commit()
            except Exception:
                # Idempotency race: another request inserted the same
                # (site_id, source_forecast_id) row between our SELECT and
                # this INSERT (the DB's unique constraint is the real
                # guarantee here; this is just avoiding a needless 500 on
                # the loser of that race). Roll back and re-read rather
                # than erroring.
                await session.rollback()
                existing_after_race = await session.execute(
                    select(DownscaledForecastFieldRow).where(
                        DownscaledForecastFieldRow.site_id
                        == settings.target_site_id,
                        DownscaledForecastFieldRow.source_forecast_id
                        == regional_forecast.forecast_id,
                    )
                )
                row = existing_after_race.scalars().first()
                if row is None:
                    raise
                field = _row_to_field(row)
                cache_status = "hit-db-race"

    _, window_end = _current_forecast_window()
    ttl_seconds = max(
        1, int((window_end - datetime.now(timezone.utc)).total_seconds())
    )
    await redis.set(cache_key, field.model_dump_json(), ex=ttl_seconds)

    response.headers["X-Regional-Forecast-Source"] = forecast_source
    response.headers["X-Cache"] = cache_status
    return field


# ---------------------------------------------------------------------------
# T1B.11 — POST /api/sensor/reading + WS /ws/site/{site_id}
# ---------------------------------------------------------------------------


@app.post("/api/sensor/reading", response_model=SensorReading)
async def post_sensor_reading(
    request: SensorReadingIngestRequest,
    x_sensor_token: str | None = Header(default=None),
):
    """Per TRD §5.1 body shape + this build doc's auth requirement: header
    must match SENSOR_INGEST_TOKEN, reject with 401 if not. No specific
    header name is mandated by either document, so a simple custom header
    (`X-Sensor-Token`) is used — matches the .env.example comment calling
    this "simple shared-secret auth", appropriate for what the ESP32's
    constrained HTTPClient can easily set."""
    if not settings.sensor_ingest_token:
        raise HTTPException(
            status_code=503,
            detail="SENSOR_INGEST_TOKEN is not configured on this deployment.",
        )
    if x_sensor_token != settings.sensor_ingest_token:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Sensor-Token")

    site_lat, site_lon = _require_target_site()
    _ = (site_lat, site_lon)  # not needed here; just confirms a site is configured
    return await ingest_sensor_reading(request, site_id=settings.target_site_id)


@app.websocket("/ws/site/{site_id}")
async def ws_site(websocket: WebSocket, site_id: str):
    await connection_manager.connect(site_id, websocket)
    try:
        while True:
            # This is a broadcast-only channel (server -> client); the
            # server doesn't act on anything the client sends, but must
            # still await *something* to detect disconnects promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        connection_manager.disconnect(site_id, websocket)
