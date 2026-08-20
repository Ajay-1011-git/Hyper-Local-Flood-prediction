"""Regional-forecast Celery task and persistence (T1A.5).

This task delegates to `forecast.fallback.get_regional_forecast`, which
runs the GEFS -> WeatherNext 2 Mini chain (see that module's docstring —
the legacy GenCast live-inference path was removed outright, no
credentials for it were ever available).

With WeatherNext 2 Mini as the working real path, this task is typically
now a file-existence check plus a fast parse of a small (tens-of-MB) NetCDF
file, not the "protect the API from a TPU-scale computation" job it was
originally justified as. It stays on Celery for consistency with the rest
of the pipeline and because persistence still shouldn't block a request
handler, but the original heavy-compute justification no longer applies.

Runs forecast acquisition out-of-band rather than inline in a request
handler (TRD §3.2), then persists the result to PostgreSQL and caches it in
Redis.

Idempotency: everything is keyed on T1A.3's deterministic `forecast_id`, and
the database write is an upsert (`db.upsert_regional_forecast`). Re-running
the task for the same window updates the existing row; it never inserts a
second one.

API note (anti-hallucination rule 2): Celery 5.6.3's task API was verified
in-session before this was written — see `celery_app.py`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine, Optional, TypeVar

from stage1a.celery_app import app
from stage1a.config import Stage1ASettings
from stage1a.db import (
    dispose_connections,
    get_db_session,
    get_redis_client,
    upsert_regional_forecast,
)
from stage1a.forecast.fallback import get_regional_forecast
from stage1a.forecast.provenance import ForecastProvenance, RegionalForecastResult
from stage1a.wn2mini.parser import FORECAST_HORIZON_HOURS
from stage1a.shared.contracts import BoundingBox, RegionalEnsembleForecast

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: Redis key prefixes. Provenance is cached beside the forecast rather than
#: inside it, so the cached payload stays exactly the §B.2 contract.
FORECAST_CACHE_PREFIX = "stage1a:regional_forecast:"
PROVENANCE_CACHE_PREFIX = "stage1a:regional_forecast_provenance:"

#: Cache lifetime matches the window the forecast describes, so a stale
#: forecast expires on its own rather than being served past its horizon.
CACHE_TTL = timedelta(hours=FORECAST_HORIZON_HOURS)


def forecast_cache_key(forecast_id: str) -> str:
    return f"{FORECAST_CACHE_PREFIX}{forecast_id}"


def provenance_cache_key(forecast_id: str) -> str:
    return f"{PROVENANCE_CACHE_PREFIX}{forecast_id}"


async def persist_regional_forecast(result: RegionalForecastResult) -> None:
    """Upsert the forecast into PostgreSQL and cache it in Redis.

    Idempotent in both stores: the row is keyed on `forecast_id` and the
    cache keys are derived from it, so repeated calls overwrite rather than
    accumulate.
    """
    forecast = result.forecast

    async for session in get_db_session():
        await upsert_regional_forecast(session, forecast)

    redis = get_redis_client()
    ttl = int(CACHE_TTL.total_seconds())
    await redis.set(
        forecast_cache_key(forecast.forecast_id),
        forecast.model_dump_json(),
        ex=ttl,
    )
    await redis.set(
        provenance_cache_key(forecast.forecast_id),
        result.provenance.model_dump_json(),
        ex=ttl,
    )
    # Pointer to the most recent window, so the API can answer "the latest
    # forecast" without scanning keys.
    await redis.set(f"{FORECAST_CACHE_PREFIX}latest", forecast.forecast_id, ex=ttl)


async def read_cached_forecast(
    forecast_id: str,
) -> Optional[tuple[RegionalEnsembleForecast, Optional[ForecastProvenance]]]:
    """Return the cached forecast and provenance for `forecast_id`, if present."""
    redis = get_redis_client()
    raw = await redis.get(forecast_cache_key(forecast_id))
    if raw is None:
        return None
    forecast = RegionalEnsembleForecast.model_validate_json(raw)

    provenance: Optional[ForecastProvenance] = None
    raw_provenance = await redis.get(provenance_cache_key(forecast_id))
    if raw_provenance is not None:
        provenance = ForecastProvenance.model_validate_json(raw_provenance)
    return forecast, provenance


async def read_latest_forecast_id() -> Optional[str]:
    """Return the `forecast_id` of the most recently persisted forecast."""
    value = await get_redis_client().get(f"{FORECAST_CACHE_PREFIX}latest")
    return str(value) if value is not None else None


async def generate_and_persist(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
) -> RegionalForecastResult:
    """Acquire the forecast (live or fallback) and persist it."""
    result = get_regional_forecast(bbox, forecast_start, settings)
    await persist_regional_forecast(result)
    logger.info(
        "Persisted regional forecast %s via %s (synthetic=%s)",
        result.forecast.forecast_id,
        result.provenance.path.value,
        result.provenance.synthetic,
    )
    return result


def run_task_coroutine(coro: "Coroutine[Any, Any, _T]") -> _T:
    """Run `coro` on a private event loop, closing DB/Redis before it exits.

    Celery tasks are synchronous, so each one drives its coroutine with
    `asyncio.run()` — a fresh loop every time. `db.py`'s connections are
    bound to the loop that opened them, so they are disposed inside this
    loop rather than left for the next task to inherit.
    """

    async def _runner() -> _T:
        try:
            return await coro
        finally:
            await dispose_connections()

    return asyncio.run(_runner())


@app.task(name="stage1a.generate_regional_forecast", bind=True)
def generate_regional_forecast_task(
    self: Any, bbox_dict: dict[str, float], forecast_start_iso: str
) -> dict[str, Any]:
    """Celery entry point: generate and persist a regional forecast.

    Args:
        bbox_dict: a `BoundingBox` as a plain dict (Celery's JSON serializer
            cannot carry a Pydantic model).
        forecast_start_iso: forecast initialisation time, ISO 8601.

    Returns:
        A small JSON-serialisable summary. The forecast itself is read back
        from PostgreSQL/Redis, not shipped through the result backend.
    """
    bbox = BoundingBox.model_validate(bbox_dict)
    forecast_start = datetime.fromisoformat(forecast_start_iso)
    if forecast_start.tzinfo is None:
        forecast_start = forecast_start.replace(tzinfo=timezone.utc)

    result = run_task_coroutine(generate_and_persist(bbox, forecast_start))
    return {
        "forecast_id": result.forecast.forecast_id,
        "member_count": len(result.forecast.members),
        "path": result.provenance.path.value,
        "synthetic": result.provenance.synthetic,
    }
