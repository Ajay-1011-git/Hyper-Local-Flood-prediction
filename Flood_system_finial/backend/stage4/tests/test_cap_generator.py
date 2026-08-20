"""Tests for T4A.1 — CAP-XML generator.

Validates generated XML against the REAL, vendored OASIS CAP-v1.2.xsd
(alerts/schemas/CAP-v1.2.xsd — downloaded directly from
docs.oasis-open.org this session, see cap_generator.py's module
docstring), not a hand-rolled structural check — real XSD validation via
lxml.etree.XMLSchema.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from lxml import etree

from backend.stage4.alerts.cap_generator import (
    CAP_NAMESPACE,
    derive_certainty,
    derive_severity,
    derive_urgency,
    generate_cap_xml,
)
from backend.stage4.shared.contracts import DamageRankEntry, SimulationResult

_XSD_PATH = Path(__file__).resolve().parents[1] / "alerts" / "schemas" / "CAP-v1.2.xsd"
_SCHEMA = etree.XMLSchema(etree.parse(str(_XSD_PATH)))


def _entry(
    *,
    vulnerability_score: float = 0.82,
    confidence: float = 0.7,
    peak_hour: int = 5,
) -> DamageRankEntry:
    return DamageRankEntry(
        structure_id="Building_02",
        structure_type="building",
        site_id="vit-vellore",
        hazard_score=6.1,
        exposure_score=300.0,
        vulnerability_score=vulnerability_score,
        vulnerability_source="USACE EGM 04-01 x AIDR 7-3",
        vulnerability_is_local_calibration=False,
        risk_score=1789.8,
        confidence=confidence,
        rank=1,
        peak_hour=peak_hour,
        peak_depth_m=1.8,
        peak_velocity_mps=2.1,
        peak_rate_of_rise=0.15,
    )


def _sim_result(*, generated_at: datetime | None = None) -> SimulationResult:
    return SimulationResult(
        simulation_id="test-sim-0001",
        site_id="vit-vellore",
        source_forecast_id="test-forecast-0001",
        generated_at=generated_at or datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc),
        hazard_threshold_m=0.3,
        validation_error_m=0.02,
        node_states=[],
        envelope={},
    )


_SITE_POLYGON = [[12.9685, 79.1555], [12.9700, 79.1555], [12.9700, 79.1565], [12.9685, 79.1565]]


def _validate(xml_str: str) -> None:
    doc = etree.fromstring(xml_str.encode("utf-8"))
    if not _SCHEMA.validate(doc):
        pytest.fail(f"Generated XML failed real CAP-v1.2.xsd validation: {_SCHEMA.error_log}")


# ----------------------------------------------------------- derivation rules


def test_certainty_matches_caps_own_probability_band_definition():
    assert derive_certainty(0.9) == "Likely"
    assert derive_certainty(0.5) == "Likely"
    assert derive_certainty(0.49) == "Possible"
    assert derive_certainty(0.01) == "Possible"
    assert derive_certainty(0.0) == "Unlikely"


def test_severity_tiers_from_real_vulnerability_score():
    assert derive_severity(_entry(vulnerability_score=0.9)) == "Extreme"
    assert derive_severity(_entry(vulnerability_score=0.6)) == "Severe"
    assert derive_severity(_entry(vulnerability_score=0.3)) == "Moderate"
    assert derive_severity(_entry(vulnerability_score=0.1)) == "Minor"
    assert derive_severity(_entry(vulnerability_score=0.0)) == "Minor"
    assert derive_severity(None) == "Unknown"


def test_urgency_tiers_from_real_peak_hour():
    assert derive_urgency(_entry(peak_hour=1)) == "Immediate"
    assert derive_urgency(_entry(peak_hour=6)) == "Immediate"
    assert derive_urgency(_entry(peak_hour=7)) == "Expected"
    assert derive_urgency(_entry(peak_hour=24)) == "Expected"
    assert derive_urgency(_entry(peak_hour=25)) == "Future"
    assert derive_urgency(None) == "Unknown"


# --------------------------------------------------------- real XSD validation


def test_generated_xml_validates_against_the_real_cap_schema():
    xml_str = generate_cap_xml([_entry()], _sim_result(), _SITE_POLYGON)
    _validate(xml_str)


def test_generated_xml_uses_the_real_confirmed_namespace():
    xml_str = generate_cap_xml([_entry()], _sim_result(), _SITE_POLYGON)
    assert f'xmlns="{CAP_NAMESPACE}"' in xml_str
    assert CAP_NAMESPACE == "urn:oasis:names:tc:emergency:cap:1.2"


def test_status_is_always_test_never_actual():
    """Explicit project-owner decision (2026-08-20): this system has never
    been connected to a real dissemination channel. See module docstring."""
    xml_str = generate_cap_xml([_entry()], _sim_result(), _SITE_POLYGON)
    doc = etree.fromstring(xml_str.encode("utf-8"))
    status = doc.find(f"{{{CAP_NAMESPACE}}}status")
    assert status.text == "Test"


def test_empty_damage_ranking_produces_a_valid_unknown_severity_alert():
    """No fabricated top entry when there's genuinely no data -- still a
    real, schema-valid document."""
    xml_str = generate_cap_xml([], _sim_result(), _SITE_POLYGON)
    _validate(xml_str)
    doc = etree.fromstring(xml_str.encode("utf-8"))
    info = doc.find(f"{{{CAP_NAMESPACE}}}info")
    assert info.find(f"{{{CAP_NAMESPACE}}}severity").text == "Unknown"
    assert info.find(f"{{{CAP_NAMESPACE}}}urgency").text == "Unknown"


def test_certainty_traces_to_real_top_entry_confidence_not_a_placeholder():
    xml_str = generate_cap_xml([_entry(confidence=0.05)], _sim_result(), _SITE_POLYGON)
    doc = etree.fromstring(xml_str.encode("utf-8"))
    info = doc.find(f"{{{CAP_NAMESPACE}}}info")
    assert info.find(f"{{{CAP_NAMESPACE}}}certainty").text == "Possible"


def test_expires_is_72_hours_after_effective():
    xml_str = generate_cap_xml([_entry()], _sim_result(), _SITE_POLYGON)
    doc = etree.fromstring(xml_str.encode("utf-8"))
    info = doc.find(f"{{{CAP_NAMESPACE}}}info")
    effective = info.find(f"{{{CAP_NAMESPACE}}}effective").text
    expires = info.find(f"{{{CAP_NAMESPACE}}}expires").text
    assert effective == "2026-08-20T12:00:00+00:00"
    assert expires == "2026-08-23T12:00:00+00:00"


def test_polygon_uses_real_lat_lon_order_and_closes_the_ring():
    xml_str = generate_cap_xml([_entry()], _sim_result(), _SITE_POLYGON)
    doc = etree.fromstring(xml_str.encode("utf-8"))
    polygon = doc.find(f".//{{{CAP_NAMESPACE}}}polygon")
    points = polygon.text.split()
    assert points[0] == "12.9685,79.1555"  # lat,lon order, matching real SACHET convention
    assert points[0] == points[-1]  # closed ring


def test_naive_datetime_is_rejected_not_silently_assumed_utc():
    naive_sim = _sim_result(generated_at=datetime(2026, 8, 20, 12, 0, 0))
    with pytest.raises(ValueError):
        generate_cap_xml([_entry()], naive_sim, _SITE_POLYGON)
