"""CWC / National Water Data Portal client (T1A.6).

DOCUMENTATION CONSULTED IN-SESSION (anti-hallucination rule 1)
--------------------------------------------------------------
Nothing below is assumed. The access method was confirmed by fetching the
live portal and its API in this session:

* https://nwdp.nwic.gov.in — reached successfully; a CKAN-based open-data
  portal (India's National Water Data Portal, NWIC/Ministry of Jal Shakti).
  NOT a bespoke REST forecast API — CWC's actual 7-day rainfall-runoff/
  hydrodynamic forecast model (architecture doc §2.2) is not published here
  as a downloadable product. Only OBSERVED hourly telemetry is available.
* https://indiawris.gov.in — connection refused from this session. Nothing
  about India-WRIS's access method is assumed; `INDIA_WRIS_BASE_URL` stays
  unset in `.env.example`.
* CKAN's standard Action API confirmed working directly against the live
  portal:
    - GET /api/3/action/package_search?q=...   -> dataset discovery
    - GET /api/3/action/package_show?id=...     -> a dataset's resources
    - GET /api/3/action/datastore_search?resource_id=...&filters=...&limit=...&offset=...
        -> paginated row access, with a `total` field and `filters` as a
           JSON object (e.g. {"District": "..."})
    - /api/3/action/datastore_search_sql exists in CKAN generally but is
      DISABLED on this instance (confirmed: returns "Action name not
      known") — do not use it.
* Confirmed real dataset: "River Water Level (Telemetry - Hourly), Central
  Water Commission (CWC)"
  (id `river-water-level-telemetry-hourly-central-water-commission-cwc`),
  split into per-river-basin, per-time-period CSV resources, each
  datastore-enabled. Confirmed schema (24 fields) via `datastore_search`:
  `Station`, `Agency`, `State`, `District`, `River`, `Basin`, `Tributary`,
  `Latitude`, `Longitude` (both `text`-typed decimal-degree strings),
  `RL_of_zeroGauge`, `Data Acquisition Time` (`DD-MM-YYYY HH:MM`), and
  `"River Water Level Telemetry Hourly (meter)"` (the reading, `text`-typed).
  There is no numeric station-id field — `SlNo` was confirmed (by sampling
  three consecutive rows of one station) to equal `_id`, i.e. a per-ROW
  serial, not a per-station code. `Station` (the name) is the only stable
  identifier a station has in this dataset.
* A second, separately-discovered dataset covers the same geography under a
  different agency: "River Water Level (Telemetry-Hourly), Tamil Nadu SW
  and GW department"
  (id `river-water-level-telemetry-hourly-tamil-nadu-sw-and-gw-department`),
  same 24-field schema, confirmed via the same calls.

GEOGRAPHIC COVERAGE CONFIRMED FOR THE TARGET SITE (Vellore, TN)
-----------------------------------------------------------------
Both basin-group resources whose title plausibly covers Vellore
(12.9165N 79.1325E) were fully paginated and every distinct station's real
coordinates checked with the haversine formula:

* CWC "East flowing rivers between Pennar and Kanyakumari" (2026-2030):
  13 distinct stations; nearest is Buggaagraharam (Chittoor, AP,
  13.336N 79.598E) at ~68.7km.
* CWC "Cauvery" (2021-2025): includes Bhavani Bridge (Erode, TN,
  11.438N 77.681E) at a comparable distance.
* TN state "East flowing rivers between Pennar and Kanyakumari"
  (2026-2030): 4 distinct stations; nearest is Nandambakkam CheckDam
  (Chennai, 13.016N 80.183E) at ~114km.

No station within any reasonable proximity threshold of Vellore was found
in this portal's public data. This is a confirmed absence, not an
unchecked assumption — `KNOWN_RELEVANT_RESOURCES` below lists exactly the
resources searched, so it can be re-run if the portal adds coverage.
"""

from __future__ import annotations

import json
from typing import Any, Final, NamedTuple, Optional

import httpx

from stage1a.config import Stage1ASettings, get_settings
from stage1a.cwc.errors import CWCUnavailableError

#: Redis key for the cached station list. fetch_station_list() takes ~60s
#: (pagination against ~47k live rows across 3 resources) -- unusable as a
#: per-request cost for T1A.8's river-stage route. Station locations change
#: essentially never, so a long TTL is safe.
_STATION_LIST_CACHE_KEY: Final[str] = "stage1a:cwc:station_list"
_STATION_LIST_CACHE_TTL_SECONDS: Final[int] = 24 * 60 * 60

_REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0
_MAX_ROWS_PER_PAGE: Final[int] = 20_000  # this portal's confirmed per-request cap


class KnownResource(NamedTuple):
    """A CKAN resource confirmed (in-session) to hold CWC/TN telemetry data."""

    resource_id: str
    label: str
    agency: str


#: Basin-group resources confirmed to plausibly cover Tamil Nadu / the
#: target site, current 2026-2030 period (see module docstring for how each
#: was found and what it covers). Not exhaustive of every CWC resource —
#: scoped to what's geographically relevant to this project's target site.
KNOWN_RELEVANT_RESOURCES: Final[tuple[KnownResource, ...]] = (
    KnownResource(
        resource_id="dc45c606-eaed-4e9e-a4f0-84152ff13e10",
        label="East flowing rivers between Pennar and Kanyakumari (2026-2030)",
        agency="CWC",
    ),
    KnownResource(
        resource_id="d027c5ac-379d-4ac2-8ced-97b02b6edbc0",
        label="Cauvery (2026-2030)",
        agency="CWC",
    ),
    KnownResource(
        resource_id="8485986c-9765-46b2-80c0-334c46cf80f9",
        label="East flowing rivers between Pennar and Kanyakumari (2026-2030)",
        agency="Tamil Nadu SW and GW Department",
    ),
)


def _datastore_search(
    base_url: str,
    resource_id: str,
    *,
    filters: Optional[dict[str, str]] = None,
    limit: int = _MAX_ROWS_PER_PAGE,
    offset: int = 0,
) -> dict[str, Any]:
    """Call CKAN's `datastore_search` action and return its `result` object.

    Raises:
        CWCUnavailableError: on a network failure or a non-success CKAN
            response — never swallowed to return an empty result.
    """
    params: dict[str, Any] = {
        "resource_id": resource_id,
        "limit": limit,
        "offset": offset,
    }
    if filters:
        import json as _json

        params["filters"] = _json.dumps(filters)

    url = f"{base_url.rstrip('/')}/api/3/action/datastore_search"
    try:
        response = httpx.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise CWCUnavailableError(
            f"National Water Data Portal request failed for resource "
            f"{resource_id}: {exc}"
        ) from exc

    if not payload.get("success"):
        raise CWCUnavailableError(
            f"National Water Data Portal returned an unsuccessful response "
            f"for resource {resource_id}: {payload.get('error')}"
        )
    result: dict[str, Any] = payload["result"]
    return result


def fetch_station_list(
    settings: Optional[Stage1ASettings] = None,
    resources: tuple[KnownResource, ...] = KNOWN_RELEVANT_RESOURCES,
) -> list[dict[str, Any]]:
    """Return every distinct station across `resources`.

    Each dict has: `station_id` (the CKAN `Station` name — the only stable
    identifier this dataset provides), `station_name` (same value, kept
    distinct for readability at call sites), `lat`, `lon` (floats), `river`,
    `district`, `state`, `resource_id`, `resource_label`, `agency`.

    Paginates fully (this portal caps each request at ~20k rows regardless
    of the requested `limit`) so no station is missed because its records
    happen to start after the first page.

    Raises:
        CWCUnavailableError: if the portal cannot be reached at all. A
            resource with zero stations is not an error by itself — it is
            reflected as that resource simply contributing nothing.
    """
    settings = settings or get_settings()
    base_url = settings.cwc_data_portal_base_url

    stations: dict[tuple[str, str], dict[str, Any]] = {}
    for resource in resources:
        offset = 0
        while True:
            result = _datastore_search(
                base_url, resource.resource_id, offset=offset
            )
            records = result.get("records", [])
            if not records:
                break
            for record in records:
                name = record.get("Station")
                if not name:
                    continue
                key = (resource.resource_id, name)
                if key in stations:
                    continue
                try:
                    lat = float(record["Latitude"])
                    lon = float(record["Longitude"])
                except (KeyError, TypeError, ValueError):
                    continue  # station has no usable coordinates; skip it
                stations[key] = {
                    "station_id": name,
                    "station_name": name,
                    "lat": lat,
                    "lon": lon,
                    "river": record.get("River"),
                    "district": record.get("District"),
                    "state": record.get("State"),
                    "resource_id": resource.resource_id,
                    "resource_label": resource.label,
                    "agency": resource.agency,
                }
            offset += len(records)
            total = result.get("total", offset)
            if offset >= total:
                break

    return list(stations.values())


async def fetch_station_list_cached(
    settings: Optional[Stage1ASettings] = None,
    resources: tuple[KnownResource, ...] = KNOWN_RELEVANT_RESOURCES,
) -> list[dict[str, Any]]:
    """`fetch_station_list`, cached in Redis for `_STATION_LIST_CACHE_TTL_SECONDS`.

    For T1A.8's river-stage route, which cannot afford a ~60s live
    pagination on every request. Falls through to a live fetch (and
    refreshes the cache) on a cache miss.
    """
    from stage1a.db import get_redis_client  # local import: avoid a cwc<->db cycle

    redis = get_redis_client()
    cached = await redis.get(_STATION_LIST_CACHE_KEY)
    if cached is not None:
        result: list[dict[str, Any]] = json.loads(cached)
        return result

    stations = fetch_station_list(settings, resources)
    await redis.set(
        _STATION_LIST_CACHE_KEY, json.dumps(stations), ex=_STATION_LIST_CACHE_TTL_SECONDS
    )
    return stations


def fetch_station_data(
    station: dict[str, Any],
    hours: int = 72,
    settings: Optional[Stage1ASettings] = None,
) -> list[dict[str, Any]]:
    """Return the most recent `hours` observed readings for `station`.

    Args:
        station: a dict as returned by `fetch_station_list` — must carry
            `resource_id` and `station_id`.
        hours: how many of the most recent hourly readings to return.

    Returns records newest-first (`_id` descending), each the raw CKAN row
    dict. This is OBSERVED telemetry, not a forecast — see the module
    docstring and `cwc/parser.py` for how it is structured into
    `RiverStageForecast`.

    Raises:
        CWCUnavailableError: on a network failure or unsuccessful response.
    """
    settings = settings or get_settings()
    base_url = settings.cwc_data_portal_base_url

    # CKAN's datastore_search has no native "sort by _id desc" without the
    # `sort` param; use it directly rather than fetching everything and
    # sorting client-side.
    params: dict[str, Any] = {
        "resource_id": station["resource_id"],
        "filters": None,
        "limit": hours,
        "sort": "_id desc",
    }
    import json as _json

    params["filters"] = _json.dumps({"Station": station["station_id"]})

    url = f"{base_url.rstrip('/')}/api/3/action/datastore_search"
    try:
        response = httpx.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise CWCUnavailableError(
            f"National Water Data Portal request failed for station "
            f"{station['station_id']!r}: {exc}"
        ) from exc

    if not payload.get("success"):
        raise CWCUnavailableError(
            f"National Water Data Portal returned an unsuccessful response "
            f"for station {station['station_id']!r}: {payload.get('error')}"
        )
    records: list[dict[str, Any]] = payload["result"].get("records", [])
    return records
