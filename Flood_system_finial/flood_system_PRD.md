# Product Requirements Document (PRD)
## Hyperlocal Flood Prediction & Early Warning System

**Document status:** Final
**Track:** AI-Powered Flood Prediction and Early Warning System
**Aligned SDGs:** SDG 1 (No Poverty), SDG 11 (Sustainable Cities and Communities), SDG 13 (Climate Action)

---

## 1. Problem Statement

Flood events in India, including in Tamil Nadu, cause disproportionate loss of life, property, and economic stability in communities that lack hyperlocal, street-level warning systems. Existing flood forecasting tools operate at regional or national scale — global systems provide broad-area risk estimates but no building-level detail; national systems provide river-basin-scale forecasts but no physical simulation of how water actually moves once it arrives at a specific location.

The governing problem statement requires a system that:
1. Produces **hyper-local predictions with at least a 72-hour lead time**.
2. Delivers **multilingual alerts** to affected populations.
3. **Integrates with existing government disaster response systems**.

No existing public system — reviewed and verified directly rather than assumed — satisfies all three simultaneously at true street-level resolution. This PRD defines a system that does.

---

## 2. Goals and Objectives

| Goal | Description |
|---|---|
| G1 | Deliver a genuine 72-hour advance flood warning, grounded in verified forecast skill rather than an unsubstantiated claim |
| G2 | Resolve flood hazard down to a 2km radius using verified prediction methods, and to sub-meter precision within a specific physically simulated site |
| G3 | Rank flood damage risk per building/road segment, not as an undifferentiated area-wide alert |
| G4 | Communicate uncertainty honestly at every stage — probabilistic output, not false precision |
| G5 | Produce alerts in a format directly compatible with India's existing government alerting infrastructure (CAP/SACHET) |
| G6 | Deliver alerts in multiple languages to the affected population |
| G7 | Demonstrate a live, working data-assimilation mechanism — real sensor input updating a running simulation, not a static demo |

---

## 3. Stakeholders and Target Users

| Stakeholder | Relationship to system |
|---|---|
| District/State Disaster Management Authorities | Primary institutional recipient of the ranked risk list and CAP-XML alerts; uses output to direct evacuation and resource allocation |
| NDMA (National Disaster Management Authority) | Downstream recipient via SACHET-compatible alert format |
| Residents of the flood-prone area | End recipients of multilingual, role-appropriate alert messages |
| Emergency response teams | Consumers of the building/road-level damage-priority ranking for on-the-ground deployment |
| Evaluating panel (hackathon context) | Assesses technical soundness, honesty of claims, and demonstration quality |

### User Stories

- **As a district disaster management officer**, I want a ranked list of specific at-risk structures 72 hours in advance, so that I can prioritize evacuation and resource deployment before the event, not after.
- **As a resident of a flood-prone street**, I want an alert in my own language that tells me clearly whether and when I am at risk, so that I can act on it without needing to interpret technical data.
- **As an emergency responder**, I want to know which specific buildings are highest-priority, not just which district is affected, so that limited response capacity is deployed where it matters most.
- **As a system operator**, I want the system to say plainly when it is uncertain, so that decisions made on its output are not built on false confidence.
- **As a technical evaluator**, I want to see the system's forecast, physics simulation, and live sensor input all functioning together, so that I can assess it as a working system rather than a set of disconnected claims.

---

## 4. Scope

### 4.1 In scope
- 72-hour regional rainfall/discharge ensemble forecasting
- Independent river/reservoir stage cross-check
- 2km-resolution terrain-based rainfall downscaling, calibrated against real local gauge data
- Sub-meter hyperlocal physics simulation of one specific, real, photogrammetry-scanned site
- Live sensor-based data assimilation into the running simulation (single hardware unit)
- Per-building/road damage risk ranking
- 3D visualization of terrain, water surface, and damage overlay
- CAP-XML alert generation, SACHET-schema-compatible
- Multilingual alert text generation

### 4.2 Out of scope for this build
- Field deployment of a distributed sensor network across the full 2km zone (a single demonstration unit is used instead)
- Any generative AI downscaling model requiring a regional training checkpoint not currently available for the target region
- Coastal or storm-surge hazard modeling (target site is inland)
- Live, unassisted operation without human oversight of the alert-dissemination step
- Multi-site or nationwide deployment (this build targets one specific real site)

---

## 5. Functional Requirements

### Stage 1 — Prediction

| ID | Requirement |
|---|---|
| FR-1 | The system shall retrieve a 72-hour, multi-member rainfall ensemble forecast from a published AI global weather model for the target region. |
| FR-2 | The system shall retrieve an independent river/reservoir stage forecast for the same region and time window, from a government hydrological monitoring source. |
| FR-3 | The system shall downscale the regional rainfall ensemble to 2km resolution using terrain features (elevation, slope, aspect) derived from a digital elevation model. |
| FR-4 | The downscaling model's parameters shall be calibrated against verified, real, historical local rainfall gauge data before being used in a live forecast. |
| FR-5 | The system shall sample the 2km-resolution forecast field at the exact coordinates of the physical simulation site (Stage 2) and produce a time-varying boundary condition for it. |
| FR-6 | The system shall accept a live reading from a physical sensor and make it available to Stage 2 as a real-time correction input. |
| FR-7 | The system shall preserve and expose the full ensemble spread at every stage — no output shall collapse the forecast to a single deterministic value without also reporting its distribution. |

### Stage 2 — Physics Simulation

| ID | Requirement |
|---|---|
| FR-8 | The system shall generate a georeferenced, elevation-anchored 3D mesh of the target site from photogrammetry capture. |
| FR-9 | Building footprints within the scanned site shall be represented as no-flow boundary nodes within the physics computation, not as decorative geometry layered over an unaware simulation. |
| FR-10 | The system shall compute water depth, velocity, and rate-of-rise at every mesh node, for every timestep across the 72-hour forecast window, for every ensemble member. |
| FR-11 | The physics model shall accept the live sensor reading (FR-6) as a boundary-condition update to its running state, without requiring a full simulation restart. |
| FR-12 | A conventional numerical solver, independent of the trained neural model, shall be available as a fallback capable of producing the same category of output if the neural model is unavailable or unstable. |

### Stage 3 — Damage Risk

| ID | Requirement |
|---|---|
| FR-13 | The system shall compute a risk score for each building and road segment as a function of hazard (depth, velocity, rate-of-rise, ensemble agreement), exposure (structure/road presence, population where available), and vulnerability (a stated damage/fragility function). |
| FR-14 | The system shall output a ranked list of structures/segments by computed risk, each with an attached confidence value derived from ensemble agreement. |
| FR-15 | Hazard computation shall include flow velocity and rate-of-rise as independent inputs, not depth alone. |

### Stage 4 — Visualization and Alerting

| ID | Requirement |
|---|---|
| FR-16 | The system shall render the simulated site in 3D, with the fine-scanned mesh seamlessly embedded within the surrounding wider-area terrain. |
| FR-17 | The system shall render the water surface using values computed by Stage 2 — the rendering layer shall perform no independent physics computation. |
| FR-18 | The system shall visually represent forecast uncertainty (e.g., a bounded envelope around a most-likely extent), and this representation shall visibly respond when new sensor data is assimilated. |
| FR-19 | The system shall recolor buildings/segments in the 3D render according to Stage 3's damage ranking. |
| FR-20 | The system shall generate a CAP-XML alert with severity, certainty, urgency, area, and effective/expiry fields populated from real system output — certainty specifically from ensemble agreement, not a static or placeholder value. |
| FR-21 | The system shall produce alert text in multiple languages appropriate to the affected population. |

---

## 6. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Honesty of output | No component shall present a probabilistic or approximate result as a certain or exact one. Every user-facing output involving forecast or risk shall carry its associated confidence/uncertainty. |
| NFR-2 | Resilience | Every stage with a component that could fail to converge or be unavailable (the trained neural model, live network access) shall have a defined, working fallback path, so that no single point of failure prevents the system from producing genuine output. |
| NFR-3 | Performance | The physics simulation shall run fast enough, once trained, to process the full forecast ensemble within a timeframe suitable for interactive use (not a multi-hour batch process per scenario). |
| NFR-4 | Data provenance | Every external data source used shall be a verified, accessible, real source at the time of use — not an assumed or unconfirmed one. |
| NFR-5 | Geographic consistency | The coarse regional terrain data and the fine site-scan data shall share a common coordinate reference system, with no unresolved discontinuity at their boundary. |
| NFR-6 | Accessibility of alerts | Alert output shall be understandable by a non-technical recipient without requiring interpretation of raw model output. |
| NFR-7 | Government compatibility | Alert structure shall conform to the CAP schema fields used by India's SACHET system, without requiring a custom, incompatible format. |

---

## 7. Success Metrics

| Metric | Target |
|---|---|
| Forecast lead time | 72 hours, sourced from a verified-skillful forecast model |
| Regional forecast resolution | 2km, achieved via verified downscaling method |
| Site simulation resolution | Sub-meter, via photogrammetry-derived mesh |
| Physics model accuracy (internal validation) | Cross-validated against the independent numerical solver on held-out scenarios |
| Damage ranking completeness | Every structure within the scanned site assigned a ranked risk value with confidence |
| Alert format compliance | 100% of generated alerts pass CAP-XML schema validation |
| Language coverage | Alert text available in at least the region's primary local language plus English |
| Live sensor demonstration | A live reading visibly and correctly updates the running simulation's output within the demo session |
| Fallback integrity | System produces complete, genuine end-to-end output even with the neural model disabled |

---

## 8. Assumptions

- The physical simulation targets a single, specific, real site, not a generalized or synthetic location.
- Regional forecast and river/reservoir data sources are accessed via their existing public data portals, under their existing terms of access.
- The live sensor component is a single handheld unit used for demonstration, not a distributed field deployment.
- Compute for the regional forecast model is available via a cloud/TPU inference environment; no training of that model is required or planned.
- Local calibration data (rainfall gauge history) is used at whatever spatial proximity to the target site is confirmed available at build time.

---

## 9. Dependencies

| Dependency | Nature |
|---|---|
| Published weights for the regional ensemble weather model | External; required for Stage 1 |
| Government river/reservoir and rainfall telemetry data portals | External; required for Stage 1 cross-check and downscaling calibration |
| Digital elevation model source | External; required for terrain input and render |
| Physics model base repository and (if available) pretrained weights | External; required for Stage 2 |
| Photogrammetry capture of the target site | Internal task; required before Stage 2 can be built |
| Sensor hardware procurement | Internal task; required for FR-6/FR-11 |

---

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Neural physics model fails to converge or remains unstable | Numerical solver fallback (FR-12) produces complete output independently |
| Local calibration gauge station is not within useful proximity of the target site | Downscaling model operates as a computed-only estimate; this limitation is stated explicitly rather than assumed away |
| Regional forecast model's compute environment is unavailable at build or demo time | Use of the model's own precomputed/published forecasts for the relevant date window as a substitute |
| Photogrammetry capture has gaps or noise | Mesh cleanup and re-triangulation step is treated as a dedicated, scheduled task, not an assumed-trivial step |
| Live sensor hardware or network fails during demonstration | A pre-recorded assimilation sequence is prepared as a rehearsed fallback, disclosed as such if used |
| Any claimed data source proves inaccessible or different from its documented behavior at build time | Verify directly before building on it; do not proceed on assumption |

---

## 11. Acceptance Criteria

The system is considered to meet this PRD when, in a single end-to-end demonstration:

1. A 72-hour regional forecast is retrieved and displayed with its full ensemble spread.
2. The independent river/reservoir forecast is displayed alongside it.
3. The forecast is shown downscaled to 2km resolution over the target region.
4. The physically scanned site renders in 3D, seamlessly nested within the wider terrain.
5. The water surface animates across the 72-hour window, driven by precomputed physics output, with a visible uncertainty envelope.
6. Buildings recolor according to the damage-risk ranking as water reaches their threshold.
7. The live sensor unit is used to inject a real reading, and the simulation's output and uncertainty envelope visibly respond.
8. A CAP-XML alert is generated and displayed with all required fields populated from real system output, including a genuine certainty value.
9. Alert text is shown in more than one language.
10. Every uncertainty or limitation statement required by NFR-1 is stated aloud during the demonstration, not omitted.

---

## 12. Glossary

| Term | Definition |
|---|---|
| CAP | Common Alerting Protocol — the XML-based international standard for structured public warning messages |
| SACHET | India's CAP-based Integrated Alert System, operated by NDMA |
| Ensemble forecast | A set of multiple plausible forecast trajectories, used to express probability rather than a single deterministic prediction |
| Downscaling | The process of deriving finer-resolution estimates from a coarser-resolution source |
| Fragility/depth-damage curve | A function relating hazard intensity (e.g., water depth) to expected structural damage or loss probability |
| Ghost cell | A mechanism allowing a physics simulation to accept external boundary information without restarting |
| Shallow water equations | A depth-averaged simplification of fluid flow equations, appropriate for flood modeling where horizontal extent greatly exceeds water depth |
