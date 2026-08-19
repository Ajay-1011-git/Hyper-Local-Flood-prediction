"""Nearest TN WRD station lookup + calibration-confidence honesty check — T1B.5.

`find_nearest_tnwrd_station` computes a real haversine distance from the
target site to every unique station in T1B.4's fetched telemetry, and
returns whichever is actually closest — not whichever happens to share the
target's district. Per the project's own explicit instruction: check
whether Vellore has telemetry data before assuming a nearby district's
station has to stand in. T1B.4 confirmed a real Vellore-district station
exists ("Gollapally"); this task determines whether it (or something else
entirely) is close enough to actually use.
"""

from __future__ import annotations

import math
from typing import cast

import pandas as pd

# Mean Earth radius (IUGG value, the standard constant for haversine
# distance — not something invented for this project).
_EARTH_RADIUS_KM = 6371.0088

# Flagged per this project's own convention (see T1A.7 / stage1b_build_
# instructions.md T1B.5): this default has NOT been independently verified
# as correct for this project's calibration needs — it's a reasonable
# starting point for the human to review, not a proven-correct value.
DEFAULT_PROXIMITY_THRESHOLD_KM = 25.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_KM * c


def find_nearest_tnwrd_station(
    target_lat: float, target_lon: float, stations_df: pd.DataFrame
) -> tuple[pd.Series, float]:
    """Find the TN WRD station nearest `(target_lat, target_lon)`.

    `stations_df` may be either a per-reading DataFrame (T1B.4's
    `fetch_rainfall_telemetry()` output, one row per hourly reading) or an
    already-deduplicated per-station one — this function deduplicates on
    `station_id` internally either way, so callers don't need to know
    which shape they're passing.

    Returns `(station_row, distance_km)` where `station_row` is a
    `pd.Series` with at least `station_id`, `station_name`, `latitude`,
    `longitude` (whatever other columns `stations_df` carries come along
    too), and `distance_km` is the real computed haversine distance —
    never assumed or approximated by district match.

    Raises `ValueError` if `stations_df` is empty.
    """
    if stations_df.empty:
        raise ValueError("stations_df is empty — no TN WRD stations to search")

    unique_stations = stations_df.drop_duplicates(subset=["station_id"]).copy()
    unique_stations["distance_km"] = unique_stations.apply(
        lambda row: _haversine_km(
            target_lat, target_lon, row["latitude"], row["longitude"]
        ),
        axis=1,
    )
    nearest_idx = unique_stations["distance_km"].idxmin()
    # .loc[scalar_label] on a DataFrame with a unique index always returns a
    # Series, never a DataFrame; pandas-stubs' return type is just
    # conservatively wider than that guarantee.
    nearest_row = cast(pd.Series, unique_stations.loc[nearest_idx])
    distance_km = float(cast(float, nearest_row["distance_km"]))
    station_row = nearest_row.drop("distance_km")
    return station_row, distance_km


def get_calibration_confidence(
    distance_km: float, threshold_km: float = DEFAULT_PROXIMITY_THRESHOLD_KM
) -> str:
    """Return `"calibrated_nearby_station"` if `distance_km` is within
    `threshold_km` of the target site, else
    `"computed_only_no_nearby_station"` — based only on the real computed
    distance, never assumed positive."""
    if distance_km <= threshold_km:
        return "calibrated_nearby_station"
    return "computed_only_no_nearby_station"
