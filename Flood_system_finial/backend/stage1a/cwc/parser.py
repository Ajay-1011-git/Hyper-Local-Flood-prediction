"""CWC nearest-station lookup and `RiverStageForecast` parser (T1A.7).

REAL DATA, NOT A FORECAST — READ BEFORE CHANGING THIS FILE
------------------------------------------------------------
As established in `cwc/client.py`'s docstring: the National Water Data
Portal exposes OBSERVED hourly telemetry, not CWC's actual forward-looking
7-day forecast model. There is no lead-time-indexed data to parse.

Per an explicit human decision (2026-08-19, asked because this is a real
gap between what §B.2's `RiverStageForecast.trajectory` implies and what
this data source actually is): `trajectory` is populated with the most
recent OBSERVED readings, newest first, `hour=0` for the latest reading and
increasingly negative for older ones. `forecast_horizon_hours=0` — nothing
is projected forward. This keeps architecture doc §2.2's actual stated role
for CWC in this system: "an independent hydrological cross-check... does
that [rainfall] translate into an actual river or reservoir threshold
breach" — i.e. downstream code should compare the regional rainfall forecast
against whether the river is ALREADY rising, not against a CWC-predicted
future level that does not exist in this open data source.

`breach_threshold_m`/`breach_probability` are left `None` — nothing in the
confirmed schema (`RL_of_zeroGauge` is a gauge-datum reference elevation,
not a danger level) supports populating either without fabricating a
number.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from stage1a.cwc.errors import CWCParseError
from stage1a.shared.contracts import RiverStageForecast, StageTimestepValue

_READING_FIELD = "River Water Level Telemetry Hourly (meter)"
_TIME_FIELD = "Data Acquisition Time"
_TIME_FORMAT = "%d-%m-%Y %H:%M"  # confirmed against real records in T1A.6


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    earth_radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def find_nearest_station(
    target_lat: float, target_lon: float, stations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return the station in `stations` closest to `(target_lat, target_lon)`.

    Real haversine distance against real station coordinates — no
    assumption about which station is "probably" close. Attaches the
    computed `_distance_km` to the returned dict so the caller does not
    have to recompute it.

    Raises:
        CWCParseError: if `stations` is empty. Never invents a station.
    """
    if not stations:
        raise CWCParseError(
            "No CWC stations to search — cannot find a nearest station "
            "without inventing one."
        )
    best: Optional[dict[str, Any]] = None
    best_distance = math.inf
    for station in stations:
        distance = haversine_km(target_lat, target_lon, station["lat"], station["lon"])
        if distance < best_distance:
            best_distance = distance
            best = station
    assert best is not None  # stations is non-empty, so a best always exists
    return {**best, "_distance_km": best_distance}


def _parse_reading(value: Any) -> Optional[float]:
    """Parse a raw CWC reading string into a float, or None if unusable.

    The confirmed real data contains missing/placeholder values (`"-"`) and
    occasional non-numeric artifacts; these are skipped rather than raising,
    since one bad row should not fail an entire station's trajectory. A
    trajectory that ends up empty after skipping IS an error — see
    `parse_station_forecast`.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_station_forecast(
    raw_data: list[dict[str, Any]],
    station: dict[str, Any],
    target_lat: float,
    target_lon: float,
    proximity_threshold_km: float,
) -> RiverStageForecast:
    """Structure `station`'s recent observed readings into `RiverStageForecast`.

    Args:
        raw_data: records as returned by `cwc.client.fetch_station_data`,
            expected newest-first (`_id` descending).
        station: the station dict (from `fetch_station_list`, optionally via
            `find_nearest_station`) this data belongs to.
        target_lat, target_lon: the site being served, used to (re)compute
            the real distance for `station_proximity_verified` — computed
            here rather than trusted from a possibly-stale `_distance_km`,
            since this function's contract must hold even if called
            directly with a hand-picked station.
        proximity_threshold_km: distance below which the station counts as
            "verified" close enough to the target site. Config-driven
            (`Stage1ASettings.cwc_station_proximity_threshold_km`), not a
            hardcoded guess.

    Returns a `RiverStageForecast` with `forecast_horizon_hours=0` and
    `trajectory` holding OBSERVED readings (`hour=0`=latest, negative for
    older) — see the module docstring for why. `station_proximity_verified`
    is only True if the real computed distance is within the threshold; if
    no station anywhere is close enough, this still returns a forecast from
    the nearest available station, marked `False` — never fails silently
    and never fabricates a closer station.

    Raises:
        CWCParseError: if no reading in `raw_data` can be parsed as a
            number — an empty trajectory would silently look like "the
            station reported nothing" when the real problem is "every row
            was unusable."
    """
    distance_km = haversine_km(target_lat, target_lon, station["lat"], station["lon"])
    verified = distance_km <= proximity_threshold_km

    trajectory: list[StageTimestepValue] = []
    for offset, record in enumerate(raw_data):
        level = _parse_reading(record.get(_READING_FIELD))
        if level is None:
            continue
        trajectory.append(StageTimestepValue(hour=-offset, water_level_m=level))

    if not trajectory:
        raise CWCParseError(
            f"Station {station.get('station_id')!r} returned "
            f"{len(raw_data)} raw record(s), but none had a usable "
            f"`{_READING_FIELD}` value. Refusing to return an empty "
            "trajectory as if the station simply had no data."
        )

    return RiverStageForecast(
        station_id=str(station["station_id"]),
        station_name=str(station.get("station_name", station["station_id"])),
        lat=float(station["lat"]),
        lon=float(station["lon"]),
        forecast_horizon_hours=0,
        trajectory=trajectory,
        breach_threshold_m=None,
        breach_probability=None,
        station_proximity_verified=verified,
    )


def latest_reading_time(raw_data: list[dict[str, Any]]) -> Optional[datetime]:
    """Parse the newest record's `Data Acquisition Time`, if present and valid."""
    if not raw_data:
        return None
    raw = raw_data[0].get(_TIME_FIELD)
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), _TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
