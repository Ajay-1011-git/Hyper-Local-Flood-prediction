# Technical Requirements Document (TRD)
## Hyperlocal Flood Prediction & Early Warning System — Web Application

**Document status:** Final
**Implementation target:** Web application (browser client + backend services)

---

## 1. Purpose and Scope

This document specifies the technical implementation of the system defined in the PRD and Architecture documents, as a web application. It defines the technology stack, component boundaries, data contracts, and — specifically — the performance and reliability engineering decisions required to run genuinely heavy computation (ensemble physics simulation, 3D rendering, real-time sensor assimilation) smoothly, without lag or failure, in a live demonstration context.

---

## 2. System Context

The system is a client-server web application with four cooperating compute domains:

1. **Browser client** — 3D rendering, dashboards, user interaction.
2. **Application backend** — orchestration, data-source integration, API surface, real-time push.
3. **ML/physics compute layer** — GNN inference, numerical solver execution, forecast downscaling.
4. **Hardware layer** — the ESP32 sensor unit, communicating over WiFi to the backend.

The single most important architectural decision governing every choice below is this: **heavy computation must never happen on the request path the user is actively waiting on.** The 72-hour ensemble physics simulation is computed ahead of time and served as precomputed results; only the live sensor-assimilation update happens genuinely in real time, and it is scoped narrowly enough (a local ghost-cell update, not a full resimulation) to actually be fast.

---

## 3. Technology Stack — Selection and Justification

### 3.1 Frontend

| Layer | Choice | Justification |
|---|---|---|
| Framework | **React** (with TypeScript) | Component model fits the multi-view UI (3D scene, forecast dashboard, ranked list, alert panel) cleanly; TypeScript's static typing catches an entire class of data-shape bugs before runtime — directly relevant to the "no bugs" requirement, since this system passes complex nested data (ensemble arrays, mesh geometry, sensor payloads) between many components. |
| 3D rendering | **Three.js via react-three-fiber (R3F)**, with the **drei** helper library | R3F expresses the Three.js scene graph as React components, so scene state (water level, uncertainty envelope, damage colors) updates through normal React state rather than manual imperative Three.js calls scattered through the codebase — fewer places for state and rendering to drift out of sync, which is a common source of "it looks wrong but only sometimes" bugs in hand-rolled Three.js apps. |
| Build tool | **Vite** | Near-instant hot-reload during development, which matters directly for a tight build timeline; native TypeScript and ES module support with no extra configuration burden. |
| Styling | **Tailwind CSS** | Utility classes avoid the accumulation of ad hoc, conflicting CSS rules that tend to produce visual bugs under time pressure. |
| Client state | **Zustand** for UI/scene state, **TanStack Query** for server data fetching | Zustand integrates cleanly with R3F's render loop without the boilerplate of Redux; TanStack Query handles caching, retry, and loading/error states for REST calls automatically, removing a common source of "stale data shown after a failed fetch" bugs. |
| Real-time updates | **native WebSocket API** (or Socket.IO client if reconnection handling is needed) | The live sensor-assimilation demo requires push, not poll — polling would either lag behind the actual reading or waste requests. |

### 3.2 Backend

| Layer | Choice | Justification |
|---|---|---|
| Language | **Python** | Mandatory in practice, not just preference: the physics model (PyTorch/PyTorch Geometric), the numerical solver, and the downscaling computation are all most directly implemented in the same ecosystem as the ML stack, avoiding a cross-language serialization boundary that would itself be a bug and latency source. |
| API framework | **FastAPI** | Native `async`/`await` support means the API server's event loop is never blocked while a background computation runs — critical here, since GNN inference and data-source fetches are exactly the kind of operation that would otherwise freeze the whole server for every connected client. Pydantic-based request/response validation (built into FastAPI) rejects malformed data at the boundary instead of letting it propagate into the simulation and fail silently deep inside. Automatic OpenAPI schema generation also gives a single source of truth for the frontend-backend contract, reducing drift between what the frontend sends and what the backend expects. |
| Background/heavy jobs | **FastAPI `BackgroundTasks`** for lightweight jobs; **Celery with Redis as broker** for the genuinely heavy ones (full ensemble simulation runs, model fine-tuning) | Ensemble simulation across 50 members must not run inline in a request handler — Celery workers process it out-of-band, and the frontend is notified via WebSocket when results are ready, rather than holding an HTTP connection open for a long-running computation. |
| Real-time push | **FastAPI's native WebSocket support**, backed by **Redis pub/sub** for message routing if multiple backend workers are involved | Keeps the "sensor reading arrived → simulation updated → frontend should update" path a genuine push, not a polling loop. |

### 3.3 ML / Physics Compute Layer

| Component | Choice | Justification |
|---|---|---|
| Regional ensemble forecast | **GenCast**, run via **JAX** on TPU (Colab/Cloud TPU access) | This is the model's native, published inference environment; running it anywhere else would mean re-implementing published, tested inference code for no benefit. Because a full ensemble forecast takes only minutes, this runs as a scheduled/on-demand batch job, not a live request-path dependency. |
| Hyperlocal physics model | **PyTorch + PyTorch Geometric**, serving the fine-tuned `RBTV1/mSWE-GNN` model | PyTorch Geometric is the framework the base model is already implemented in — using it directly avoids a costly and bug-prone reimplementation in a different framework. |
| Numerical solver (training data + fallback) | **Python + NumPy/SciPy** | No need for a compiled-language solver at this problem scale (a single 50m × 50m mesh); NumPy's vectorized operations are fast enough, and staying in Python keeps this component consistent with the rest of the ML pipeline and easy to swap in as a live fallback without a language boundary. |
| Model serving | Loaded directly in a dedicated Python worker process (not a separate model-serving framework like TorchServe) | At this system's scale — one fixed model, one fixed mesh, a single demo deployment — a full model-serving framework adds operational complexity without a corresponding benefit; a plain in-process model held in memory, called directly from Celery tasks, is simpler and has fewer moving parts to fail. |

### 3.4 Data Storage

| Layer | Choice | Justification |
|---|---|---|
| Primary database | **PostgreSQL with the PostGIS extension** | This system is fundamentally geospatial — DEM tiles, building footprints, mesh node coordinates, sensor location, gauge-station locations. PostGIS provides native geospatial types and spatial queries (e.g., "find the nearest gauge station to this site"), replacing what would otherwise be manually implemented, bug-prone distance and containment calculations. |
| Time-series data (sensor readings, ensemble forecast values over time) | Stored in PostgreSQL as structured tables, indexed on timestamp and location | At this system's data volume (one demo site, one sensor, one forecast run at a time), a dedicated time-series database is unnecessary operational overhead; PostgreSQL with proper indexing handles it directly. |
| Large binary/geometry assets (photogrammetry mesh, DEM rasters) | Stored as files (**glTF/GLB** for meshes, **GeoTIFF** for DEM rasters) on disk, referenced by path from PostgreSQL | Keeps large binary payloads out of the relational database (which handles them poorly) while keeping a single, queryable source of truth for what exists and where. |
| Caching / job broker | **Redis** | Serves two roles: Celery's task broker/result backend, and a cache for precomputed ensemble results so an already-computed forecast scenario is never recomputed unnecessarily. |

### 3.5 Hardware / Firmware

| Component | Choice | Justification |
|---|---|---|
| Firmware | **Arduino framework (C++) on ESP32** | The most standard, well-documented path for this exact microcontroller/sensor combination; minimizes firmware-level bugs by using well-tested libraries rather than a less common alternative. |
| Communication protocol | **Simple HTTP POST** from the ESP32 directly to a dedicated FastAPI ingestion endpoint | For a single sensor unit, introducing an MQTT broker adds a component that can fail (broker uptime, topic misconfiguration) for no benefit at this scale — a direct HTTP call to one known endpoint is the fewest moving parts, which is the right choice when demo-day reliability is the priority. |

### 3.6 Deployment for Demonstration

**The application must be able to run fully on a single laptop with no live internet dependency during the actual demonstration.** This is a reliability decision, not a convenience one: venue WiFi is a real, common failure point, and this system's most impressive moments (the 3D water simulation, the ranked damage list, the CAP-XML alert) depend on data that can and should be fully precomputed and cached ahead of time.

- GenCast's ensemble forecast, CWC/TN WRD data, and the DEM are fetched and cached locally before the demo.
- The trained/fine-tuned physics model is loaded locally.
- Only the live sensor unit's WiFi connection (to the presenter's own laptop hotspot, not venue WiFi) is required to be live during the demonstration, and this is the one piece explicitly designed with a rehearsed fallback (Section 7).

---

## 4. Component Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Browser Client (React)                │
│  ┌──────────────┐ ┌───────────────┐ ┌──────────────────┐ │
│  │ 3D Scene (R3F)│ │ Forecast Panel│ │ Alert/Ranking UI │ │
│  └──────┬───────┘ └───────┬───────┘ └────────┬─────────┘ │
│         │  REST (TanStack Query)  │  WebSocket (live)     │
└─────────┼──────────────────────────┼──────────────────────┘
          │                          │
┌─────────▼──────────────────────────▼──────────────────────┐
│                  FastAPI Application Server                 │
│  ┌────────────┐ ┌─────────────┐ ┌────────────────────────┐│
│  │ REST routes│ │ WebSocket    │ │ Sensor ingestion route  ││
│  │            │ │ manager      │ │ (HTTP POST from ESP32)  ││
│  └─────┬──────┘ └──────┬──────┘ └────────────┬────────────┘│
└────────┼────────────────┼──────────────────────┼────────────┘
         │                │                       │
┌────────▼────────────────▼───────────────────────▼───────────┐
│         Celery Workers (heavy/background computation)         │
│  ┌────────────┐ ┌───────────────┐ ┌─────────────────────┐   │
│  │ GenCast job│ │ Downscaling +  │ │ mSWE-GNN inference /  │   │
│  │ (TPU)      │ │ CWC/TNWRD fetch│ │ ghost-cell assimilation│  │
│  └────────────┘ └───────────────┘ └─────────────────────┘   │
└────────────────────────────┬───────────────────────────────┘
                              │
                 ┌────────────▼────────────┐
                 │  PostgreSQL + PostGIS    │
                 │  Redis (cache/broker)    │
                 │  File store (mesh/DEM)   │
                 └──────────────────────────┘
```

---

## 5. API Contracts

### 5.1 REST endpoints (representative)

```
GET  /api/forecast/regional
  → returns GenCast ensemble summary (mean, spread) for the target region

GET  /api/forecast/downscaled?lat={}&lon={}
  → returns the 2km-resolution ensemble field at the given coordinates

GET  /api/forecast/river-stage
  → returns CWC's independent river/reservoir forecast for the region

GET  /api/simulation/site/{site_id}
  → returns the precomputed Stage 2 simulation result for the demo site:
    per-node, per-timestep depth/velocity/rate-of-rise, ensemble envelope

GET  /api/damage-ranking/{site_id}
  → returns the ranked building/road risk list with confidence values

GET  /api/alert/{site_id}
  → returns the generated CAP-XML alert plus multilingual text variants

POST /api/sensor/reading
  body: { "sensor_id": string, "distance_cm": number, "timestamp": ISO8601 }
  → ingests a live reading from the ESP32; triggers the assimilation job
    and a WebSocket broadcast of the updated state
```

### 5.2 WebSocket events

```
Client subscribes to: /ws/site/{site_id}

Server → Client events:
  { "type": "simulation_update", "payload": { node_states, envelope } }
  { "type": "sensor_assimilated", "payload": { sensor_id, new_reading, updated_region } }
  { "type": "ensemble_ready", "payload": { forecast_id } }
```

### 5.3 Data model — key entities

```
EnsembleForecast
  id, source (GenCast/CWC), region, generated_at,
  members: [ { member_id, trajectory: [ {t, rainfall_mm} ] } ]

SimulationNode
  node_id, site_id, lat, lon, elevation,
  is_wall_node: bool,
  states: [ { t, depth_m, velocity_mps, rate_of_rise } ]

SensorReading
  sensor_id, site_id, distance_cm, timestamp, assimilated: bool

DamageRankEntry
  structure_id, site_id, hazard_score, exposure_score,
  vulnerability_score, risk_score, confidence, rank

Alert
  id, site_id, generated_at, severity, certainty, urgency,
  area_polygon, effective_time, expiry_time, text_by_language: {}
```

---

## 6. Performance Engineering

The requirement to run "very heavy processes smoothly, without lag" is addressed through four specific, deliberate decisions, not general optimization effort:

1. **Precompute, don't compute-on-demand.** The full 72-hour, multi-member simulation is run once, ahead of time, and stored. The browser never waits on a physics computation — it requests already-computed results. Only the sensor-assimilation update computes live, and it is scoped to a local ghost-cell update rather than a full re-simulation, which published benchmarks show completing in a small fraction of a second.

2. **Never transmit raw ensemble data to the browser.** With up to 50 ensemble members × thousands of mesh nodes × dozens of timesteps, sending raw per-member data to the client would be both unnecessary and slow. The backend computes ensemble statistics (mean, min/max envelope, agreement fraction) server-side and transmits only the aggregated result — exactly what the 3D scene actually needs to render.

3. **Separate the render mesh from the physics mesh where their resolution needs diverge.** The physics computation runs on the full-fidelity photogrammetry mesh; the rendered geometry can use a decimated (simplified) version of the same mesh for the wider 2km surrounding terrain, while keeping full detail only on the immediate scanned patch the camera is focused on — reducing the polygon count Three.js has to render per frame without reducing simulation accuracy.

4. **Cache aggressively and idempotently.** Regional forecast, downscaling, and CWC/TN WRD data are fetched once and cached in Redis/PostgreSQL; repeated requests for the same forecast window are served from cache, not recomputed.

---

## 7. Reliability and Bug-Prevention Strategy

- **Type safety end to end**: TypeScript on the frontend, Pydantic models on the backend, sharing a single OpenAPI-derived contract — a mismatched field name or type is caught at build/request time, not discovered live during the demo.
- **Validated data at every external boundary**: incoming sensor readings, fetched government data, and DEM files are schema-validated on arrival; malformed data is rejected and logged rather than silently propagating into the simulation.
- **Fallback at every stage that depends on an external or trained component** (per the Architecture document): the numerical solver substitutes for the neural model; a rehearsed, disclosed pre-recorded sequence substitutes for the live sensor if its connection fails during the demo; locally cached forecast data substitutes for a live API call if network access is unavailable.
- **Local-first demo deployment** (Section 3.6): removes the most common live-demo failure mode — dependency on venue network conditions — entirely from the critical path.
- **Automated validation of the physics model against the numerical solver** on held-out scenarios before the model is trusted for the demo, rather than assumed correct after training completes.
- **End-to-end rehearsal of the full acceptance-criteria checklist** (as defined in the PRD) before presentation, run against the actual deployed build, not a development environment that may differ from it.

---

## 8. Non-Functional Technical Requirements

| ID | Requirement |
|---|---|
| TNFR-1 | The 3D scene shall maintain a smooth interactive frame rate on standard presentation hardware (a modern laptop with an integrated or discrete GPU), achieved via the mesh-decimation and precomputation strategies in Section 6. |
| TNFR-2 | Sensor-to-visible-update latency (from ESP32 reading to visible change in the rendered uncertainty envelope) shall be low enough to read as "real-time" to a human observer. |
| TNFR-3 | The application shall be fully operable with no live internet connection during demonstration, per Section 3.6. |
| TNFR-4 | All API responses shall conform to their declared schema; schema violations shall be rejected at the boundary, not handled downstream. |
| TNFR-5 | The system shall recover to a working state automatically if the WebSocket connection drops and reconnects, without requiring a full page reload. |
