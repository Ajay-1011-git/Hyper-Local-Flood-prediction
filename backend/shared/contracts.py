"""Canonical data contracts shared across pipeline stages.

DO NOT rename fields, change types, or "improve" these schemas casually —
Stage 1A, Stage 1B, and (eventually) Stage 2 each independently build code
against them. Any change here must be agreed by whoever owns the consuming
stage before it lands.

- Stage 1A produces `RegionalEnsembleForecast` and `RiverStageForecast`.
- Stage 1B consumes `RegionalEnsembleForecast` and produces
  `DownscaledForecastField` and `SensorReading`.

Copied verbatim from the project's Stage 1A / Stage 1B build-instruction
documents (§B.2 in each).
"""

from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional


# ---------------------------------------------------------------------------
# Stage 1A outputs
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


class TimestepValue(BaseModel):
    hour: int  # 0 to 72
    rainfall_mm: float


class EnsembleMember(BaseModel):
    member_id: int
    trajectory: List[TimestepValue]


class RegionalEnsembleForecast(BaseModel):
    forecast_id: str
    source: str = "GenCast"
    region_bbox: BoundingBox
    generated_at: datetime
    resolution_km: float = 28.0
    members: List[EnsembleMember]


class StageTimestepValue(BaseModel):
    hour: int
    water_level_m: float


class RiverStageForecast(BaseModel):
    source: str = "CWC"
    station_id: str
    station_name: str
    lat: float
    lon: float
    forecast_horizon_hours: int
    trajectory: List[StageTimestepValue]
    breach_threshold_m: Optional[float] = None
    breach_probability: Optional[float] = None
    station_proximity_verified: bool


# ---------------------------------------------------------------------------
# Stage 1B outputs
# ---------------------------------------------------------------------------


class DownscaledTimestepValue(BaseModel):
    hour: int
    inflow_mm: float


class DownscaledEnsembleMember(BaseModel):
    member_id: int  # must match the source RegionalEnsembleForecast's member_id
    trajectory: List[DownscaledTimestepValue]


class DownscaledForecastField(BaseModel):
    site_id: str
    site_lat: float
    site_lon: float
    resolution_km: float = 2.0
    calibration_source: str = "TN WRD"
    calibration_confidence: str  # "calibrated_nearby_station" | "computed_only_no_nearby_station"
    source_forecast_id: str  # traces back to RegionalEnsembleForecast.forecast_id
    generated_at: datetime
    members: List[DownscaledEnsembleMember]


class SensorReading(BaseModel):
    sensor_id: str
    site_id: str
    distance_cm: float
    timestamp: datetime
    assimilated: bool = False
