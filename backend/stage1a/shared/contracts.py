"""Stage 1A / Stage 1B shared data contract.

VERBATIM copy of §B.2 of `stage1a_build_instructions.md`. A byte-identical
copy also lives at `backend/stage1b/shared/contracts.py` (per-module copy
arrangement, confirmed with the human). Do NOT rename fields, change types,
or "improve" this schema — any change breaks the independently-built
Stage 1B module.
"""

from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional


class BoundingBox(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


class TimestepValue(BaseModel):
    hour: int          # 0 to 72
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
