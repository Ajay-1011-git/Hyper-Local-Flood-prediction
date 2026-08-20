"""CAP-XML generator — T4A.1.

REAL SCHEMA, CONFIRMED IN-SESSION (not assumed or recalled from memory)
---------------------------------------------------------------------------
Fetched directly this session:
- OASIS CAP v1.2 spec (docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html)
  for the real element hierarchy and enumerated values.
- The real XSD itself, downloaded and vendored at
  `alerts/schemas/CAP-v1.2.xsd` (from
  docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.xsd) — used by this
  module's own tests to validate generated XML structurally, not just by
  inspection.
- India's SACHET platform (NDMA/C-DOT's national CAP alerting system):
  confirmed via a live web search + a specific technical writeup
  (thejeshgn.com/2025/05/28/common-alerting-protocol-cap-in-the-indian-
  context/, which references and quotes real SACHET CAP feed output)
  that SACHET uses PLAIN, UNMODIFIED CAP 1.2 — no SACHET-specific
  namespace, no custom required elements. The one SACHET-specific detail
  found: its real `<area><polygon>` coordinates are (lat, lon) WGS84
  pairs (matching this project's own `Alert.area_polygon` field comment,
  `[[lat, lon], ...]` — no reordering needed).

Real, confirmed values used below:
  namespace: "urn:oasis:names:tc:emergency:cap:1.2"
  status enum: Actual | Exercise | System | Test | Draft
  msgType enum: Alert | Update | Cancel | Ack | Error
  scope enum: Public | Restricted | Private
  category enum: Geo | Met | Safety | Security | Rescue | Fire | Health |
                 Env | Transport | Infra | CBRNE | Other
  urgency enum: Immediate | Expected | Future | Past | Unknown
  severity enum: Extreme | Severe | Moderate | Minor | Unknown
  certainty enum: Observed | Likely | Possible | Unlikely | Unknown

`status = "Test"`, EXPLICIT PROJECT-OWNER DECISION (2026-08-20): this
system has never been registered with or connected to SACHET or any real
dissemination channel (TV, radio, coastal sirens, etc.). CAP's own
definition of `Test` is "technical testing only, all recipients
disregard" — used here so the generated XML can never be mistaken for a
real, currently-in-effect public alert if it were ever seen outside this
demo's context, while every OTHER field (severity/certainty/urgency and
all underlying data) stays fully real, computed from real Stage 2/3
output — nothing about the alert's actual hazard content is fabricated
or watered down, only its dissemination status is honestly marked.

DERIVATION RULES, FLAGGED AS JUDGMENT CALLS (no formula given in any
project doc for turning a risk_score/peak_hour/ensemble_agreement_fraction
into a CAP enum — these are reasonable, principled mappings, not
independently validated against real emergency-management practice):

- `certainty` (CAP enum) is the one exception — NOT a flagged guess.
  CAP's own spec defines `Likely` as "p > ~50%" and `Possible` as
  "p <= ~50%", i.e. the enum's real definition IS a probability band.
  `ensemble_agreement_fraction` (`DamageRankEntry.confidence`) is
  literally that probability, so the mapping is a direct application of
  CAP's own stated definition, not an invented threshold:
    >= 0.5  -> "Likely"
    >  0.0  -> "Possible"
    == 0.0  -> "Unlikely"
  ("Observed" is never used — this project has no confirmed, occurred
  event, only a forecast/simulation, however real the underlying physics.)

- `severity`: derived from the top-ranked structure's `vulnerability_score`
  (a real, bounded [0,1] damage-fraction from T3.4's cited depth-damage
  curve — a more physically meaningful bounded signal than `risk_score`,
  which has no natural scale since it's hazard x exposure x vulnerability
  with exposure in raw m^2/population units). Tiers chosen to roughly
  track AIDR Guideline 7-3's own D*V hazard bands (already used in T3.4):
    >= 0.75 -> "Extreme"
    >= 0.50 -> "Severe"
    >= 0.25 -> "Moderate"
    >  0.0  -> "Minor"
    == 0.0  -> "Minor" (real data showing zero risk, not absence of data)
  Empty `damage_ranking` (no data at all) -> "Unknown".

- `urgency`: derived from the top-ranked structure's `peak_hour` (real,
  from T3.1's hazard extraction) -- how soon the worst moment arrives:
    <= 6h  -> "Immediate"
    <= 24h -> "Expected"
    >  24h -> "Future"

- `effective`/`expires`: `effective = sim_result.generated_at` (the real
  simulation's own timestamp); `expires = effective + 72h`, matching this
  project's own stated 72-hour forecast horizon (TRD/architecture docs'
  consistent convention) — not independently chosen.

- `sender`: a real, but self-issued (not NDMA-registered) identifier,
  `"hyperlocal-flood-prediction-system@{site_id}"` — flagged as a
  placeholder value; this project has no real registered CAP sender
  identity, and fabricating one (e.g. impersonating a real agency's
  sender ID) would be actively dangerous, not just inaccurate.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from lxml import etree

from backend.stage4.shared.contracts import DamageRankEntry, SimulationResult

CAP_NAMESPACE = "urn:oasis:names:tc:emergency:cap:1.2"
_NSMAP = {None: CAP_NAMESPACE}


def derive_certainty(confidence: float) -> str:
    """CAP's own spec defines these as probability bands -- direct
    application, not an invented threshold. See module docstring."""
    if confidence >= 0.5:
        return "Likely"
    if confidence > 0.0:
        return "Possible"
    return "Unlikely"


def derive_severity(top_entry: DamageRankEntry | None) -> str:
    """Flagged judgment call -- see module docstring."""
    if top_entry is None:
        return "Unknown"
    v = top_entry.vulnerability_score
    if v >= 0.75:
        return "Extreme"
    if v >= 0.50:
        return "Severe"
    if v >= 0.25:
        return "Moderate"
    return "Minor"


def derive_urgency(top_entry: DamageRankEntry | None) -> str:
    """Flagged judgment call -- see module docstring."""
    if top_entry is None:
        return "Unknown"
    if top_entry.peak_hour <= 6:
        return "Immediate"
    if top_entry.peak_hour <= 24:
        return "Expected"
    return "Future"


def _format_cap_datetime(dt: datetime) -> str:
    """CAP requires `YYYY-MM-DDThh:mm:ss±hh:mm` (a real UTC offset, not a
    bare 'Z') -- confirmed against the real spec's own example
    (`2003-04-02T14:39:01-05:00`). `isoformat()` on a timezone-aware
    datetime already produces exactly this shape."""
    if dt.tzinfo is None:
        raise ValueError(
            f"CAP datetime fields require a timezone-aware datetime, got naive {dt!r}"
        )
    return dt.isoformat(timespec="seconds")


def generate_cap_xml(
    damage_ranking: List[DamageRankEntry],
    sim_result: SimulationResult,
    site_polygon: List[List[float]],
) -> str:
    """Generate a real, schema-valid CAP 1.2 alert XML document.

    `damage_ranking` is expected sorted descending by `risk_score` (T3.5's
    own contract) — this function does not re-sort, but does not assume
    non-empty either (an empty list produces an honest `severity=Unknown`
    alert rather than crashing or fabricating a top entry).

    `site_polygon`: `[[lat, lon], ...]` real site boundary coordinates —
    supplied by the caller (this function does not derive one), matching
    the confirmed real SACHET convention of (lat, lon) ordering.
    """
    top_entry = damage_ranking[0] if damage_ranking else None

    severity = derive_severity(top_entry)
    urgency = derive_urgency(top_entry)
    certainty = derive_certainty(top_entry.confidence if top_entry else 0.0)

    effective = sim_result.generated_at
    expires = effective + timedelta(hours=72)

    # lxml-stubs' Element() signature doesn't model the real, documented
    # {None: uri} default-namespace idiom (it's a stub limitation, not a
    # real runtime restriction -- confirmed working: this produces the
    # real `xmlns="..."` default-namespace declaration, not a prefixed
    # one, exactly what CAP's own schema/examples use).
    alert = etree.Element("alert", nsmap=_NSMAP)  # type: ignore[arg-type]
    etree.SubElement(alert, "identifier").text = (
        f"{sim_result.site_id}-{sim_result.simulation_id}"
    )
    etree.SubElement(alert, "sender").text = (
        f"hyperlocal-flood-prediction-system@{sim_result.site_id}"
    )
    etree.SubElement(alert, "sent").text = _format_cap_datetime(effective)
    etree.SubElement(alert, "status").text = "Test"
    etree.SubElement(alert, "msgType").text = "Alert"
    etree.SubElement(alert, "scope").text = "Public"

    info = etree.SubElement(alert, "info")
    etree.SubElement(info, "category").text = "Met"
    etree.SubElement(info, "event").text = "Flash Flood Forecast"
    etree.SubElement(info, "urgency").text = urgency
    etree.SubElement(info, "severity").text = severity
    etree.SubElement(info, "certainty").text = certainty
    etree.SubElement(info, "effective").text = _format_cap_datetime(effective)
    etree.SubElement(info, "expires").text = _format_cap_datetime(expires)
    etree.SubElement(info, "senderName").text = "Hyper-Local Flood Prediction System (demo)"
    etree.SubElement(info, "headline").text = (
        f"Flood hazard forecast for site {sim_result.site_id}"
    )
    etree.SubElement(info, "description").text = (
        f"Simulation {sim_result.simulation_id} for site {sim_result.site_id}: "
        f"{len(damage_ranking)} structure(s)/segment(s) ranked by flood risk. "
        + (
            f"Highest-risk: {top_entry.structure_id} "
            f"(risk_score={top_entry.risk_score:.3f}, "
            f"peak depth={top_entry.peak_depth_m:.2f}m at hour {top_entry.peak_hour}, "
            f"vulnerability={top_entry.vulnerability_score:.2f})."
            if top_entry is not None
            else "No ranked structures available."
        )
    )

    area = etree.SubElement(info, "area")
    etree.SubElement(area, "areaDesc").text = f"Site {sim_result.site_id}"
    if site_polygon:
        polygon = etree.SubElement(area, "polygon")
        # CAP polygon syntax: whitespace-separated "lat,lon" pairs, closed
        # (first point repeated last) -- confirmed against the real spec's
        # own <polygon> examples.
        points = list(site_polygon)
        if points and points[0] != points[-1]:
            points = points + [points[0]]
        polygon.text = " ".join(f"{lat},{lon}" for lat, lon in points)

    return etree.tostring(
        alert, xml_declaration=True, encoding="UTF-8", pretty_print=True
    ).decode("utf-8")
