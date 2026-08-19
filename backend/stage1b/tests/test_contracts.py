"""Tests for the shared data contract wiring (§B.2 / T1B.0).

Found by a coverage audit during T1B.12: `backend/stage1b/shared/
contracts.py` — the re-export module that lets this stage's code say
`from stage1b.shared.contracts import ...` — was at 0% coverage, imported
by no test at all, despite being exactly what T1B.0's VERIFY step checks
(`python -c "from stage1b.shared.contracts import
DownscaledForecastField, SensorReading"`). If that re-export broke (a
renamed symbol upstream, a typo in `__all__`), nothing in the suite would
have caught it. These tests close that gap.

They also pin the cross-stage contract itself: Stage 1A is built
independently against a byte-identical copy of these models, so a field
rename or type change here silently breaks the other team member's code
at merge time. Asserting the exact field names makes that a loud test
failure instead.
"""

from __future__ import annotations

from datetime import datetime, timezone

import backend.stage1b.shared.contracts as stage1b_contracts
from backend.shared.contracts import (
    DownscaledForecastField,
    RegionalEnsembleForecast,
    SensorReading,
)


def test_stage1b_reexport_exposes_the_expected_names():
    """T1B.0's VERIFY import path must keep working."""
    from backend.stage1b.shared.contracts import (  # noqa: F401
        BoundingBox,
        DownscaledEnsembleMember,
        DownscaledForecastField as ReexportedField,
        DownscaledTimestepValue,
        RegionalEnsembleForecast as ReexportedRegional,
        SensorReading as ReexportedSensorReading,
    )

    # Re-exported, not redefined — a second, drifting definition of the
    # same concept is exactly what CLAUDE.md's rule 3 forbids.
    assert ReexportedField is DownscaledForecastField
    assert ReexportedSensorReading is SensorReading
    assert ReexportedRegional is RegionalEnsembleForecast


def test_stage1b_reexport_all_matches_actual_exports():
    for name in stage1b_contracts.__all__:
        assert hasattr(stage1b_contracts, name), (
            f"__all__ lists {name!r} but the module doesn't export it"
        )


def test_downscaled_forecast_field_contract_fields_are_unchanged():
    """Stage 2 consumes this unmodified; Stage 1A's builder shares the
    RegionalEnsembleForecast half. Renaming a field here is a breaking
    change that must be a deliberate, coordinated decision — not a silent
    edit."""
    assert set(DownscaledForecastField.model_fields) == {
        "site_id",
        "site_lat",
        "site_lon",
        "resolution_km",
        "calibration_source",
        "calibration_confidence",
        "source_forecast_id",
        "generated_at",
        "members",
    }


def test_sensor_reading_contract_fields_are_unchanged():
    assert set(SensorReading.model_fields) == {
        "sensor_id",
        "site_id",
        "distance_cm",
        "timestamp",
        "assimilated",
    }


def test_regional_ensemble_forecast_contract_fields_are_unchanged():
    """This one is shared verbatim with Stage 1A's independently-built
    module — the highest-risk contract in the repo for a silent merge
    break."""
    assert set(RegionalEnsembleForecast.model_fields) == {
        "forecast_id",
        "source",
        "region_bbox",
        "generated_at",
        "resolution_km",
        "members",
    }


def test_contract_defaults_match_spec():
    reading = SensorReading(
        sensor_id="s",
        site_id="site",
        distance_cm=1.0,
        timestamp=datetime.now(timezone.utc),
    )
    assert reading.assimilated is False  # §B.2 default

    field = DownscaledForecastField(
        site_id="site",
        site_lat=12.9,
        site_lon=79.1,
        calibration_confidence="calibrated_nearby_station",
        source_forecast_id="f",
        generated_at=datetime.now(timezone.utc),
        members=[],
    )
    assert field.resolution_km == 2.0  # §B.2 default
    assert field.calibration_source == "TN WRD"  # §B.2 default
