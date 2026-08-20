# Hyperlocal Flood Prediction & Early Warning System
## Complete System Architecture

---

## 1. System Overview

The system produces a 72-hour-advance flood forecast for a specific location, and a physically simulated, sub-meter-resolution prediction of how that location will flood — which street, which building, in what order, how deep, how fast — rendered as an explorable 3D model and packaged into a government-compatible alert.

The architecture is organized into four stages, each with a distinct responsibility:

| Stage | Responsibility | Spatial resolution | Temporal horizon |
|---|---|---|---|
| 1 — Prediction | How much water is coming, and when | 2km | 72 hours |
| 2 — Physics simulation | Exactly what that water does on arrival | Sub-meter | Continuous, driven by Stage 1 |
| 3 — Damage risk | Who and what is affected, ranked | Per-building | Derived from Stage 2 |
| 4 — Visualization & alerting | Communicating the result | N/A | Real-time |

No stage claims precision beyond what its underlying method can actually support. Rainfall is never claimed below 2km; physical simulation is never claimed to extend the forecast horizon; damage estimates are always expressed as a ranked, probabilistic list rather than a single figure.

---

## 2. Stage 1 — Prediction Layer

### 2.1 Regional rainfall ensemble forecast

> **Amendment 3 — 2026-08-20: the regional forecast source is now GEFS (primary) → WeatherNext 2 Cyclones Mini (fallback). GenCast is fully removed.**
> The GenCast description below is preserved as the original design record and is **no longer what the system runs** — it was removed outright (no TPU/JAX access or credentials, ever) and must not be reintroduced, including as a fallback.
> - **GEFS (NOAA Global Ensemble Forecast System), 0.25° / ~27.75km, 31 real members** — primary, fully automated, no manual step. Chosen as primary on 2026-08-20 specifically because its 0.25° grid is ~4× finer than WeatherNext 2 Mini's 1.0°, which directly improves the input to Stage 1B's terrain-based downscaling (§2.3).
> - **WeatherNext 2 Cyclones Mini, 1.0° / ~111km, 8 members** — fallback only; requires a human to run a Colab notebook ahead of time.
>
> Note the coincidence worth not misreading: GEFS's 0.25° resolution happens to match the "~28km (0.25° grid)" figure quoted for GenCast below, but they are unrelated models. Implementation and full live verification: `backend/stage1a/CLAUDE.md` (Addendum 2) and `backend/stage1a/gefs/`. Prior source-priority history: `stage1a_amendment_2_source_priority_correction.md`.

**Model (ORIGINAL DESIGN — superseded, see the amendment note above):** GenCast (Google DeepMind), a diffusion-based AI global ensemble weather model, published in *Nature*, December 2024, released with open code and weights.

**Technical specification:**
- Native spatial resolution: ~28km (0.25° grid)
- Ensemble size: 50+ members per forecast
- Forecast horizon: up to 15 days; this system uses the 0–72 hour window
- Inference cost: a full 15-day, full-ensemble forecast completes in approximately 8 minutes on a single TPU v5 chip
- Performance: outperforms the leading traditional ensemble system (ECMWF ENS) on the majority of verification targets, with the largest margin beyond 36-hour lead times and for extreme-event prediction

**Deployment:** inference only, on published pretrained weights — no training or fine-tuning of this component. Executed via TPU access (Colab or equivalent).

**Output:** a 50+ member ensemble of rainfall/precipitation trajectories across the regional grid, for the full 72-hour window, carried forward as a probability distribution rather than collapsed to a single value.

### 2.2 River and reservoir stage forecast

**Source:** Central Water Commission (CWC), Ministry of Jal Shakti, Government of India.

**Technical specification:**
- Network: 1,300+ gauging stations nationally, approximately 960 telemetry-based
- Forecast method: coupled rainfall-runoff and hydrodynamic modeling, using IMD's quantitative precipitation forecast (QPF) as a primary input, run across 18 separate river-basin models
- Forecast horizon: 7-day lead time
- Self-reported forecast accuracy: above 90%
- Data access: structured, downloadable hourly telemetry (river water level, discharge) via the National Water Data Portal (`nwdp.nwic.gov.in`) and the India Water Resources Information System (`indiawris.gov.in`)

**Role in this system:** an independent hydrological cross-check, running in parallel to Stage 1's meteorological forecast. Where GenCast answers "how much rain," CWC's model answers "does that translate into an actual river or reservoir threshold breach." The two are not merged into one number — both are surfaced, and agreement or disagreement between them is itself a signal communicated downstream.

### 2.3 Hyperlocal downscaling to 2km resolution

**Method:** terrain-based statistical downscaling — a physically motivated technique family (cascade-based orographic downscaling, the Froude Number Method, elevation-based precipitation adjustment factors) that redistributes a coarse rainfall field across finer terrain using elevation, slope, and aspect, rather than a trained generative model.

**Inputs:**
- GenCast's coarse (~28km) rainfall ensemble (Section 2.1)
- Digital elevation model — elevation, slope, and aspect at 2km-cell granularity (Section 2.4)

**Calibration:** the downscaling model's parameters are fit against **Tamil Nadu Water Resources Department (TN WRD)** hourly rainfall telemetry — a real, structured, downloadable dataset (`Rainfall (Telemetry - Hourly), Tamil Nadu SW GW`, via the National Water Data Portal). Historical periods where both a TN WRD gauge reading and a corresponding GenCast forecast exist are compared directly; systematic gaps between the model's computed estimate and the gauge's actual measurement become a correction term applied to the downscaling parameters.

**Output:** a 2km-resolution, ensemble-valued rainfall/inflow field. This field is sampled at the exact coordinates of the Stage 2 simulation site and passed forward as a time-varying boundary condition.

### 2.4 Terrain and post-event validation data

**Source:** Bhuvan (National Remote Sensing Centre, ISRO).

- **DEM:** Cartosat-1-derived elevation data (CartoDEM), 30m (1 arc-second) horizontal resolution, approximately 8m LE90 vertical accuracy. Used as the elevation/slope/aspect input for Section 2.3's downscaling model, and as the surrounding-terrain heightmap in Stage 4's 3D render.
- **Post-event validation:** satellite imagery comparison after a flood event, used to check and recalibrate the model ahead of each subsequent monsoon season. This is an operational, ongoing-use step rather than a one-time build task.

### 2.5 Live sensor input

**Hardware:** a single handheld unit — ESP32 microcontroller (WiFi-enabled) with an HC-SR04 ultrasonic distance sensor, mounted facing downward over a container of water. Approximate cost ₹700–1,200. Optional small OLED display for a live on-device readout.

**Data path:** ESP32 reads the ultrasonic sensor → transmits the reading over WiFi (HTTP or MQTT) to the backend → the backend injects the reading into Stage 2's running simulation as a live boundary-condition update at a marked point in the mesh.

**Role, stated precisely:** this component does not modify Stage 1's forecast and does not extend the 72-hour lead time — both are properties of GenCast alone. Its function is to demonstrate live data assimilation into Stage 2's physics simulation: the model accepting a real-time measurement and visibly updating its output in response.

### 2.6 Stage 1 output

A 2km-resolution, ensemble-valued rainfall/inflow field, cross-checked against CWC's independent river/reservoir forecast, sampled at the Stage 2 simulation site's coordinates, and passed forward as a time-varying boundary condition for the full 72-hour forecast window.

---

## 3. Stage 2 — Hyperlocal Physics Engine

### 3.1 Site capture

**Method:** smartphone or drone video, processed via Structure-from-Motion (SfM) photogrammetry (Meshroom or COLMAP), covering a 50m × 50m target site.

**Accuracy:** centimeter-level, independent of the specific phone/camera used.

**Processing:**
1. Raw SfM reconstruction produces a point cloud / mesh with holes and triangulation artifacts.
2. Mesh cleanup: hole-filling and re-triangulation to produce a mesh usable by a finite-volume solver.
3. Georeferencing: the site's GPS coordinates (from photo/video EXIF data) are used to register the mesh in real-world coordinate space.
4. Elevation anchoring: the mesh's height offset is calibrated against the surrounding 2km DEM's (Section 2.4) elevation value at the same coordinates, so the fine mesh and coarse regional terrain meet without a visible discontinuity at the boundary.

### 3.2 Computational mesh

The cleaned, georeferenced scan becomes a finite-volume computational mesh: cells as graph nodes, adjacency as graph edges. This same mesh serves both the physics computation (below) and the Stage 4 render geometry — one dataset, not two reconciled separately.

**Buildings:** every node falling inside a scanned building footprint is tagged as a **wall/obstacle node** — a no-flow boundary condition. This is a structural, first-class node type in the model architecture, not a post-hoc visual mask; the physics computation itself routes flow around these nodes.

### 3.3 Neural physics model

**Base architecture:** mSWE-GNN (multi-scale hydraulic graph neural network), from the public repository `RBTV1/mSWE-GNN`.

**How it works:**
- The model's propagation rule is derived directly from an explicit finite-volume discretization of the shallow water (Saint-Venant) equations — a depth-averaged 2D formulation, not full 3D Navier-Stokes.
- Node inputs: current hydraulic state (depth, velocity), plus static mesh properties (elevation, slope, cell area, edge length, edge orientation).
- Node outputs: hydraulic state at the next timestep, applied autoregressively (each prediction feeds back in as the next step's input) to produce an extended simulation.
- The number of message-passing layers is set in relation to the timestep between predictions, consistent with the Courant–Friedrichs–Lewy (CFL) stability condition governing explicit numerical solvers of the same equations.
- **Time-varying boundary conditions** — including Stage 1's inflow field and Section 2.5's live sensor reading — are injected via **ghost cells**, letting the model accept new boundary information mid-simulation without needing a fresh initial-condition setup.

**Published benchmark performance:** mean absolute error of 0.05m for water depth and 0.003 m²/s for unit discharge on unseen topographies; in a real-world case study (Netherlands), the model was adapted to a specific real site using only one fine-tuning sample, achieving 0.12m MAE and a computational speed-up of over 700× versus the numerical solver it replaces.

**Training approach for this system:** fine-tune from the repository's pretrained weights (if available) rather than training from randomly initialized weights, following the same low-data adaptation pathway demonstrated in the published Netherlands validation.

**Training data generator:** a self-written 2D shallow-water finite-volume solver, implementing the Saint-Venant equations directly, run approximately 50–150 times over the scanned mesh with varying inflow rate/intensity to produce supervised training trajectories. This solver also serves as Section 3.6's fallback.

**Loss function:** a hybrid objective —
1. Supervised term: predicted depth/velocity vs. the numerical solver's output at the next timestep.
2. Physics-residual term: computed via automatic differentiation, penalizing violation of shallow-water mass and momentum conservation.

### 3.4 Ensemble propagation

Because the trained model's inference cost is a small fraction of the numerical solver's, all of Stage 1's ensemble members (Section 2.1–2.3) are run through the model independently. The output at any point in the mesh is therefore a distribution, not a single value — e.g., "18 of 50 scenarios exceed 50cm depth by hour 48, rising to 34 of 50 by hour 72."

### 3.5 Live data assimilation

Section 2.5's live sensor reading enters the running simulation through the same ghost-cell mechanism used for Stage 1's boundary conditions. The model's state at and near the marked sensor location updates in response to the real measurement without requiring a full simulation restart.

### 3.6 Fallback path

If the neural model is not fully converged or stable, the numerical finite-volume solver (Section 3.3) — run directly across a reduced ensemble of Stage 1's members — produces genuine physically grounded output and can drive the complete system end to end on its own.

---

## 4. Stage 3 — Damage Risk Layer

**Formula:** `risk = hazard × exposure × vulnerability`, computed independently for each building and road segment within the scanned site.

**Hazard** — derived from Stage 2's output at each location and timestep:
- Water depth
- Flow velocity
- Rate of rise (depth change per unit time)
- Ensemble agreement fraction (what proportion of Stage 1's scenarios produce this outcome)

Depth alone is not used as the hazard signal: velocity and rate-of-rise materially affect structural damage independent of depth, and are included explicitly rather than discarded.

**Exposure** — building footprints and road segments extracted directly from the Stage 2 photogrammetry scan; population density included where available.

**Vulnerability** — a published depth-damage or fragility curve, applied as a general approximation. Fragility-curve formulations are used in preference to deterministic depth-damage functions specifically because they carry an uncertainty distribution rather than a single point estimate, which propagates naturally into the ranked output below.

**Output:** a ranked list of buildings/road segments by computed risk, each with an attached confidence value derived from Stage 2's ensemble agreement fraction — e.g., "Building 14: high risk, 41 of 50 scenarios."

---

## 5. Stage 4 — Visualization and Alerting

### 5.1 3D terrain rendering

**Engine:** Three.js.

**Composition:** the wide-area 2km DEM (Section 2.4) is rendered as a height-mapped terrain mesh; the fine, georeferenced Stage 2 scan (Section 3.1) is inserted at its true coordinates within that terrain, elevation-anchored to its boundary. Both are rendered as a single continuous scene — the fine mesh reads as a high-detail region of the same terrain, not a separately loaded model.

### 5.2 Water surface

An existing open-source Three.js water-rendering approach (real-time reflection/refraction/wave shading, e.g. following the pattern of `jeantimex/threejs-water` or the purpose-built hydrological visualization library `uihilab/Hydro3DJS`) renders the water surface. Vertex heights at each timestep are set directly from Stage 2's precomputed depth output — the renderer performs no physics computation of its own; it displays already-computed values.

### 5.3 Uncertainty visualization

Because Stage 2's output is ensemble-valued (Section 3.4), the water surface is rendered with a translucent "possible extent" envelope surrounding a solid "most-likely extent." When Section 2.5's live sensor reading is assimilated, this envelope visibly narrows in response — communicating the data-assimilation mechanism directly, rather than only updating a numeric readout.

### 5.4 Damage overlay

Buildings and road segments in the render recolor according to Stage 3's ranked output as the simulated water reaches their computed risk threshold.

### 5.5 Alert generation

**Format:** CAP-XML (Common Alerting Protocol), structured to match the field schema used by India's SACHET system (National Disaster Management Authority) — severity, certainty, urgency, area polygon, effective/expiry time.

**Certainty field:** populated directly from Stage 1/2's ensemble agreement fraction, not a static or arbitrary value.

**Delivery:** templated alert text generated per severity level, translated into multiple languages for the affected population.

---

## 6. End-to-End Data Flow

1. GenCast produces a 72-hour, 50+ member regional rainfall ensemble (Section 2.1).
2. CWC's independent hydrological model produces a parallel river/reservoir-stage forecast for the same window (Section 2.2).
3. The rainfall ensemble is downscaled to 2km resolution via the terrain-based model, calibrated against TN WRD gauge history (Section 2.3).
4. The 2km field is sampled at the Stage 2 site's coordinates and passed as a time-varying boundary condition, injected via ghost cells (Section 3.3).
5. The physics model propagates all ensemble members forward across the scanned mesh, producing depth/velocity/rate-of-rise distributions at every node and timestep (Section 3.4).
6. If the live sensor is active, its reading is assimilated into the running simulation through the same ghost-cell pathway (Section 3.5).
7. Stage 3 computes hazard × exposure × vulnerability per building/road segment from Stage 2's output, producing a ranked, confidence-scored list.
8. Stage 4 renders the terrain, water surface, uncertainty envelope, and damage overlay in Three.js, and generates the CAP-XML alert with certainty populated from real ensemble agreement.

---

## 7. Technology Stack

| Component | Tool / Library |
|---|---|
| Regional weather ensemble | GenCast (open weights, TPU/JAX inference) |
| River/reservoir data | CWC / National Water Data Portal API |
| Rainfall calibration data | TN WRD / National Water Data Portal API |
| DEM source | Bhuvan / NRSC CartoDEM |
| Photogrammetry | Meshroom or COLMAP |
| Physics model base | `RBTV1/mSWE-GNN` |
| GNN framework | PyTorch + PyTorch Geometric |
| Physics-residual loss | PyTorch autograd |
| Numerical solver | Self-written 2D shallow-water finite-volume solver (Python) |
| 3D rendering | Three.js |
| Water shader | `jeantimex/threejs-water` pattern or `uihilab/Hydro3DJS` |
| Alert format | CAP-XML, SACHET-schema-compatible |
| Sensor microcontroller | ESP32 |
| Sensor | HC-SR04 ultrasonic |
| Sensor connectivity | WiFi (HTTP/MQTT) |

---

## 8. Hardware Specification

| Component | Detail |
|---|---|
| Microcontroller | ESP32 dev board, WiFi-enabled |
| Sensor | HC-SR04 ultrasonic distance sensor, downward-facing |
| Demo vessel | Small clear container |
| Power | USB power bank |
| Optional | Small OLED display for on-device readout |
| Approximate total cost | ₹700–1,200 |
| Accuracy class | ±0.5–1cm (ultrasonic ranging) |

---

## 9. System Design Principles

- **No claim exceeds its method's actual resolution.** Rainfall is never asserted below 2km; the live sensor is never described as improving Stage 1's forecast; damage is never presented as a single exact figure.
- **Every prediction is ensemble-valued, not deterministic**, from Stage 1 through Stage 3 — output is a distribution with a stated agreement fraction, not a single number presented as fact.
- **Physics computation and rendering are strictly separated.** Three.js displays precomputed values; it performs no simulation of its own.
- **Buildings and obstacles are physical constraints inside the computation**, not decorative geometry placed over an unaware simulation.
- **The system degrades to a working fallback at every stage that could fail** — the numerical solver substitutes for the neural model if needed, ensuring there is no failure mode that produces no usable output.

---

## 10. Proposed Repository Structure

```
flood-system/
├── stage1_prediction/
│   ├── gencast_inference/
│   ├── cwc_client/
│   ├── tnwrd_client/
│   ├── downscaling/
│   └── dem_utils/
├── stage2_physics/
│   ├── photogrammetry/
│   ├── mesh_processing/
│   ├── numerical_solver/
│   ├── mswe_gnn/
│   └── sensor_assimilation/
├── stage3_damage/
│   ├── hazard_calc/
│   ├── exposure_data/
│   └── vulnerability_curves/
├── stage4_visualization/
│   ├── threejs_app/
│   ├── water_shader/
│   ├── alert_generator/
│   └── multilingual_templates/
├── hardware/
│   └── esp32_firmware/
└── data/
    ├── dem/
    ├── scanned_mesh/
    └── training_trajectories/
```
