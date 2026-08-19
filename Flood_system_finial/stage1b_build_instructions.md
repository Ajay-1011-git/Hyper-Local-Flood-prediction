# STAGE 1B — Complete Build Instructions for Claude Code
### Drift-proof, hallucination-resistant prompts aligned to the project's Architecture, TRD, and PRD documents

> **Purpose.** This document builds Stage 1B — terrain data, hyperlocal downscaling calibrated against real gauge history, and the live sensor hardware path — exactly as specified in the project's Architecture and TRD documents. Every task copies the shared data contract **verbatim**. Follow tasks in order. Do not skip **§A Operating Contract** or **§B Canonical Specifications**.
>
> **Alignment guarantee.** The stack choices, data models, and endpoint shapes below are transcribed directly from the project's Architecture (`flood_system_architecture.md`) and TRD (`flood_system_TRD.md`) documents. If any prompt here seems to disagree with those documents, **those documents win** — stop and reconcile before proceeding.
>
> **Partner module.** Stage 1A (built separately, by a different team member) produces the `RegionalEnsembleForecast` you consume in §C's downscaling tasks. You do not need Stage 1A's running code to build most of this module — mock the contract for standalone development and testing (§B.2), and integrate against the real endpoint only once both modules exist.

---

# §A. Operating Contract — paste this into `CLAUDE.md` first

```md
# STAGE 1B — Claude Code Operating Contract (READ EVERY SESSION)

## What Stage 1B is
Stage 1B has three jobs: (1) fetch and process a digital elevation model
(DEM) for the target region from Bhuvan/NRSC, (2) fetch Tamil Nadu Water
Resources Department (TN WRD) rainfall telemetry and use it to calibrate
a terrain-based statistical rainfall-downscaling model that turns Stage
1A's ~28km regional forecast into a 2km-resolution field, and (3) run
the live sensor hardware path — an ESP32 + HC-SR04 unit posting readings
to an ingestion endpoint. This is NOT a trained generative downscaling
model (no CorrDiff, no StormScope) — it is a lightweight, physically
motivated model using elevation/slope/aspect, calibrated against real
local rainfall gauge history.

## GROUND TRUTH (never change without explicit human instruction)
- Stack is FIXED: Python, FastAPI (async), Pydantic, PostgreSQL+PostGIS,
  Redis. Firmware is C++/Arduino framework on ESP32. Do not substitute.
- Downscaling method is FIXED as terrain-based statistical downscaling
  (elevation/slope/aspect adjustment). Do not implement or introduce a
  trained neural downscaling model here — that was evaluated and
  explicitly ruled out for this project (no available regional training
  data/checkpoint).
- Sensor communication is FIXED as plain HTTP POST from the ESP32 to a
  FastAPI endpoint. Do not introduce MQTT or any message broker for the
  hardware path — this is a deliberate single-unit reliability decision.
- Module boundaries: ALL code for this stage lives under `backend/stage1b/`
  and `firmware/`. Do not create files outside these directories. Do not
  modify Stage 1A's directory (`backend/stage1a/`) or Stage 2/3/4 code.
- The data contract in §B.2 is shared verbatim with Stage 1A's build
  document for `RegionalEnsembleForecast`. Do not rename fields or change
  types — this breaks the other team member's independently-built code.

## ANTI-HALLUCINATION RULES (hard rules)
1. Never invent API endpoints, download formats, or response shapes for
   Bhuvan or the National Water Data Portal. Before writing ANY code that
   calls one of these, search for and read its actual current
   documentation/portal IN THIS SESSION and confirm the exact shape. One
   specific TN WRD dataset endpoint has already been directly confirmed
   to exist as of this writing — `https://nwdp.nwic.gov.in/dataset/
   rainfall-telemetry-hourly-tamil-nadu-sw-gw` — but its exact CSV column
   structure has NOT been confirmed and must be checked by actually
   fetching and inspecting it in this session before writing a parser
   against assumed column names.
2. Never assume a Python or Arduino library exists or has a given API
   without checking its registry/repository first. Pin resolved versions.
3. If a type or contract already exists in §B.2, IMPORT/reuse it. Never
   create a second, slightly different definition of the same concept.
4. If a requirement below is ambiguous or underspecified, ask ONE
   clarifying question instead of assuming. State any unavoidable
   assumption explicitly in code comments and in the task's completion
   summary.
5. Do not fabricate test results, file contents, or command output. Run
   the actual VERIFY commands and paste their real output.
6. Where a TN WRD or nearby gauge station cannot be confirmed to actually
   exist within a useful distance of the target site (Vellore, Tamil
   Nadu), do not assume one does — implement the honest
   `calibration_confidence = "computed_only_no_nearby_station"` path.

## ANTI-DRIFT RULES (hard rules)
7. Only create/modify the files listed in a task's "Files you may touch."
   If you must touch another file, list it and explain BEFORE editing.
8. Do not refactor unrelated code. Do not add features not requested.
9. Keep `DownscaledForecastField` and `SensorReading` byte-aligned with
   §B.2 — field names and types must match exactly, since Stage 2 (built
   separately) consumes them unmodified.

## QUALITY GATES (must hold at end of every task)
- Python type hints on all functions; `mypy` passes with no errors.
- Pydantic validates ALL external data (DEM metadata, TN WRD CSV rows,
  sensor payloads) at the point it enters the system.
- No secrets or API keys committed to code — via `.env`, listed blank
  in `.env.example`.
- Every function that persists data is idempotent.
- Errors are typed and structured; never swallow an exception silently.
- The `calibration_confidence` field must always reflect a real, checked
  condition — never hardcoded to a positive value.

## WORKING METHOD (every task)
A. First output a SHORT PLAN: files you'll create/modify, your approach.
   For tasks touching more than one file, WAIT for "go" unless told to
   run autonomously.
B. Implement only what the task asks.
C. Run the task's VERIFY commands. Paste real output. Fix before
   claiming done.
D. Add/extend tests for new behaviour.
E. Commit once per task: `feat(T1B.<n>): <summary>` (or fix/chore).

## DEFINITION OF DONE
A task is done only when: code runs and imports cleanly, `mypy` passes,
the VERIFY block passes with real pasted output, tests pass, the data
model matches §B.2 exactly, and only permitted files changed.
```

---

# §B. Canonical Specifications (single source of truth)

## B.1 Environment variables (`.env.example`, create at `backend/stage1b/.env.example`)

```
# ---- Bhuvan / NRSC (DEM) ----
BHUVAN_ACCESS_METHOD=            # confirm real access method in T1B.2 before hardcoding
BHUVAN_DEM_PRODUCT=CartoDEM      # per project's confirmed DEM source

# ---- TN WRD (rainfall calibration) ----
TNWRD_DATASET_URL=https://nwdp.nwic.gov.in/dataset/rainfall-telemetry-hourly-tamil-nadu-sw-gw
# ^ confirmed to exist; verify exact CSV schema in T1B.4 before parsing

# ---- Storage ----
DATABASE_URL=postgresql://localhost:5432/floodsystem
REDIS_URL=redis://localhost:6379/0
DEM_RASTER_STORAGE_DIR=./data/dem

# ---- Target site ----
TARGET_SITE_ID=vellore_demo_site_01
TARGET_SITE_LAT=
TARGET_SITE_LON=

# ---- Sensor ingestion ----
SENSOR_INGEST_TOKEN=             # simple shared-secret auth for the ESP32's POST requests
```

## B.2 Data contract (Pydantic — `backend/stage1b/shared/contracts.py`)

> Import `RegionalEnsembleForecast` byte-identical from Stage 1A's contract (§B.2 of the Stage 1A document) — do not redefine it here. The models below are Stage 1B's own outputs.

```python
from pydantic import BaseModel
from datetime import datetime
from typing import List


class DownscaledTimestepValue(BaseModel):
    hour: int
    inflow_mm: float


class DownscaledEnsembleMember(BaseModel):
    member_id: int          # must match the source RegionalEnsembleForecast's member_id
    trajectory: List[DownscaledTimestepValue]


class DownscaledForecastField(BaseModel):
    site_id: str
    site_lat: float
    site_lon: float
    resolution_km: float = 2.0
    calibration_source: str = "TN WRD"
    calibration_confidence: str   # "calibrated_nearby_station" | "computed_only_no_nearby_station"
    source_forecast_id: str       # traces back to RegionalEnsembleForecast.forecast_id
    generated_at: datetime
    members: List[DownscaledEnsembleMember]


class SensorReading(BaseModel):
    sensor_id: str
    site_id: str
    distance_cm: float
    timestamp: datetime
    assimilated: bool = False
```

## B.3 Module file structure (target end state)

```
backend/stage1b/
├── CLAUDE.md
├── .env.example
├── shared/
│   └── contracts.py             # §B.2 (RegionalEnsembleForecast imported, not redefined)
├── dem/
│   ├── __init__.py
│   ├── client.py                 # T1B.2
│   └── processing.py             # T1B.3
├── tnwrd/
│   ├── __init__.py
│   ├── client.py                  # T1B.4
│   └── nearest_station.py         # T1B.5
├── downscaling/
│   ├── __init__.py
│   ├── calibration.py             # T1B.6
│   ├── model.py                   # T1B.7
│   └── orchestrator.py            # T1B.8
├── sensor/
│   ├── __init__.py
│   └── ingest.py                  # T1B.11
├── routes.py                      # T1B.9, T1B.11
├── db.py
├── config.py
└── tests/

firmware/
└── sensor_unit/
    └── sensor_unit.ino             # T1B.10
```

---

# §C. Tasks

## T1B.0 · Module scaffolding — `backend/stage1b/` · [P0] · depends: none

> **PROMPT**
> Goal: create the module skeleton.
> Files you may touch: everything under `backend/stage1b/` and `firmware/sensor_unit/` (new directories).
> Requirements: create the folder structure in §B.3; `config.py` loading §B.1's variables via `pydantic-settings` (verify its current API before use); `.env.example` exactly as §B.1; §A pasted verbatim into `CLAUDE.md`; §B.2 pasted into `shared/contracts.py`, importing `RegionalEnsembleForecast` from Stage 1A's module if present in the same repo, otherwise defining a local copy explicitly marked as "MUST match Stage 1A's contract exactly — sync before integration"; `requirements.txt` pinned (fastapi, pydantic, pydantic-settings, sqlalchemy, rasterio or a confirmed-current alternative for GeoTIFF handling, requests, pytest — verify each on PyPI, do not guess versions).
> **VERIFY:** `pip install -r requirements.txt` completes with no errors; `python -c "from stage1b.shared.contracts import DownscaledForecastField, SensorReading"` runs clean; paste both outputs.

## T1B.1 · Database & Redis connection layer — `backend/stage1b/db.py` · [P0] · depends: T1B.0

> **PROMPT**
> Goal: working connections before any later task persists data.
> Files you may touch: `backend/stage1b/db.py`, `backend/stage1b/tests/test_db.py`.
> Requirements: implement `get_db_session()` and `get_redis_client()`. Create PostgreSQL tables for `downscaled_forecast_field` and `sensor_reading` matching §B.2's fields, with PostGIS geometry columns for `site_lat`/`site_lon`. Create a `dem_metadata` table referencing the raster file path (per the project's convention: large binaries as files, referenced from the DB, not stored as blobs).
> **VERIFY:** paste `\dt` output showing all three tables; paste a successful Redis `PING`.

## T1B.2 · Bhuvan DEM client — `backend/stage1b/dem/client.py` · [P0] · depends: T1B.0

> **PROMPT**
> Goal: fetch the CartoDEM raster covering the target region from Bhuvan.
> Files you may touch: `backend/stage1b/dem/client.py`, `backend/stage1b/dem/__init__.py`, `backend/stage1b/tests/test_dem.py`.
> Requirements: **before writing request code, search for and confirm Bhuvan's actual current DEM access/download method in this session — whether it's a direct download portal, a WMS/WCS service, or requires manual export — and confirm the real format returned. Do not assume a REST API shape.** Implement `fetch_dem_raster(bbox: BoundingBox) -> <path to downloaded raster file>` using whatever access pattern is actually confirmed, saving to `DEM_RASTER_STORAGE_DIR`.
> **VERIFY:** paste the source(s) consulted to confirm the access method; run the fetch for the target region's bounding box; confirm a real raster file exists at the returned path and paste its file size and format (e.g., via `gdalinfo` or `rasterio` inspection — verify which tool's API is current before using it).

## T1B.3 · DEM processing (elevation/slope/aspect) — `backend/stage1b/dem/processing.py` · [P0] · depends: T1B.2

> **PROMPT**
> Goal: derive the elevation, slope, and aspect grids the downscaling model needs.
> Files you may touch: `backend/stage1b/dem/processing.py`, `backend/stage1b/tests/test_dem.py`.
> Requirements: implement `compute_terrain_grids(raster_path: str, grid_resolution_km: float = 2.0) -> dict` returning elevation, slope, and aspect values on a 2km grid covering the region (use `rasterio`/`numpy` or a confirmed-current geospatial library — verify the exact function names for slope/aspect computation, e.g., whether you're hand-deriving via `numpy.gradient` or using a library function, rather than assuming one exists with a guessed name). Persist the grid to `dem_metadata` (T1B.1) plus the array data to a file (e.g., `.npy` or GeoTIFF) referenced from the DB row.
> **VERIFY:** run against the T1B.2 raster; paste the shape and value ranges (min/max) of the elevation, slope, and aspect arrays produced; confirm the values are physically plausible for Vellore's terrain (not all zeros, not NaN-filled).

## T1B.4 · TN WRD rainfall client — `backend/stage1b/tnwrd/client.py` · [P0] · depends: T1B.0

> **PROMPT**
> Goal: download and parse the TN WRD hourly rainfall telemetry dataset.
> Files you may touch: `backend/stage1b/tnwrd/client.py`, `backend/stage1b/tnwrd/__init__.py`, `backend/stage1b/tests/test_tnwrd.py`.
> Requirements: fetch the CSV from `TNWRD_DATASET_URL` (already confirmed to exist as a real dataset page — but **fetch it directly in this session and inspect the actual returned column names before writing any parsing code that assumes a schema**). Implement `fetch_rainfall_telemetry() -> pandas.DataFrame` (or equivalent), with columns normalized to at minimum: station identifier, latitude, longitude, timestamp, rainfall value. If the real CSV's columns differ from this minimal expectation, adapt the normalization to what's actually present — do not force-fit invented column names.
> **VERIFY:** paste the actual raw column headers found in the downloaded CSV; paste 3 real parsed rows after normalization.

## T1B.5 · Nearest station lookup — `backend/stage1b/tnwrd/nearest_station.py` · [P0] · depends: T1B.4

> **PROMPT**
> Goal: determine whether a usable TN WRD station exists near the target site, honestly.
> Files you may touch: `backend/stage1b/tnwrd/nearest_station.py`, `backend/stage1b/tests/test_tnwrd.py`.
> Requirements: implement `find_nearest_tnwrd_station(target_lat, target_lon, stations_df) -> tuple[station_row, distance_km]` using a real haversine calculation. Implement `get_calibration_confidence(distance_km, threshold_km: float = 25.0) -> str`, returning `"calibrated_nearby_station"` or `"computed_only_no_nearby_station"` based on the real computed distance — the threshold is a config value to be reviewed by the human, not treated as verified-correct.
> **VERIFY:** run against `TARGET_SITE_LAT`/`TARGET_SITE_LON` (Vellore) and the real station list from T1B.4; paste the nearest station found, the real computed distance in km, and the resulting confidence string.

## T1B.6 · Calibration fitting — `backend/stage1b/downscaling/calibration.py` · [P1] · depends: T1B.5

> **PROMPT**
> Goal: fit a correction factor comparing the downscaling model's computed estimate against real TN WRD historical readings.
> Files you may touch: `backend/stage1b/downscaling/calibration.py`, `backend/stage1b/tests/test_downscaling.py`.
> Requirements: implement `fit_calibration(historical_tnwrd_readings, historical_regional_estimates) -> dict` (returning correction coefficients per terrain-adjustment parameter). If `calibration_confidence` from T1B.5 is `"computed_only_no_nearby_station"`, this function should return identity/no-op coefficients and clearly log that no real calibration was possible — never fabricate a correction from data that doesn't exist.
> **VERIFY:** with real nearby TN WRD data (if found in T1B.5) or synthetic test fixtures if none exists, paste the fitted coefficients and confirm the identity/no-op path triggers correctly when no station is available.

## T1B.7 · Downscaling model core — `backend/stage1b/downscaling/model.py` · [P0] · depends: T1B.3, T1B.6

> **PROMPT**
> Goal: implement the terrain-based statistical downscaling calculation itself.
> Files you may touch: `backend/stage1b/downscaling/model.py`, `backend/stage1b/tests/test_downscaling.py`.
> Requirements: implement `downscale_rainfall(coarse_value_mm: float, elevation, slope, aspect, calibration_coeffs: dict) -> float`, applying the terrain-adjustment relationship (elevation/slope/aspect based orographic adjustment) per the project's Architecture document §2.3, modified by the calibration coefficients from T1B.6. This is a deterministic function — same inputs must always produce the same output (required for the idempotency quality gate).
> **VERIFY:** run with a fixed set of test inputs; paste the output; confirm re-running with identical inputs produces an identical result.

## T1B.8 · Downscaling orchestration — `backend/stage1b/downscaling/orchestrator.py` · [P0] · depends: T1B.7

> **PROMPT**
> Goal: consume a full `RegionalEnsembleForecast` and produce the final `DownscaledForecastField`.
> Files you may touch: `backend/stage1b/downscaling/orchestrator.py`, `backend/stage1b/tests/test_downscaling.py`.
> Requirements: implement `generate_downscaled_field(regional_forecast: RegionalEnsembleForecast, site_id, site_lat, site_lon) -> DownscaledForecastField`, applying T1B.7's function per-member, per-timestep, using T1B.3's terrain grids at the site's location. Set `calibration_confidence` and `source_forecast_id` correctly. This must work against either a real `RegionalEnsembleForecast` fetched from Stage 1A's live endpoint, or a manually constructed mock object matching the contract exactly — for development before Stage 1A's endpoint exists, use a mock fixture, clearly labeled as such, not a fabricated "real" call.
> **VERIFY:** run against a mock `RegionalEnsembleForecast` fixture with at least 2 members; paste the resulting `DownscaledForecastField`, confirming `member_id` values match between input and output and `source_forecast_id` traces correctly.

## T1B.9 · FastAPI route for downscaled output — `backend/stage1b/routes.py` · [P0] · depends: T1B.8, T1B.1

> **PROMPT**
> Goal: expose the downscaled forecast per the TRD.
> Files you may touch: `backend/stage1b/routes.py`, `backend/stage1b/tests/test_routes.py`.
> Requirements: implement, per `flood_system_TRD.md` §5.1:
> ```
> GET /api/forecast/downscaled?site_id={}
>   → returns the latest DownscaledForecastField for the given site,
>     fetching the current RegionalEnsembleForecast from Stage 1A's
>     endpoint (or a configured mock during standalone development)
> ```
> Persist the result via `db.py`, cached in Redis, idempotent per forecast window.
> **VERIFY:** start the app; `curl` the endpoint; paste the real JSON response validating against §B.2.

## T1B.10 · ESP32 firmware — `firmware/sensor_unit/sensor_unit.ino` · [P0] · depends: none

> **PROMPT**
> Goal: firmware reading the HC-SR04 sensor and posting to the ingestion endpoint.
> Files you may touch: `firmware/sensor_unit/sensor_unit.ino` and any supporting header files in the same directory.
> Requirements: **verify the current, correct Arduino ESP32 WiFi and HTTPClient library API in this session before writing connection code — do not assume method signatures from memory, as ESP32 Arduino core APIs have changed across versions.** Implement: WiFi connection with the presenter's hotspot credentials (via a separate, git-ignored `secrets.h`, not hardcoded); HC-SR04 distance reading on a fixed interval (e.g., every 2 seconds); HTTP POST to the ingestion endpoint with a JSON body matching `SensorReading` (sensor_id, site_id, distance_cm, timestamp), including `SENSOR_INGEST_TOKEN` as a header for basic auth; visible serial-monitor logging of every reading and POST result for debugging during rehearsal.
> **VERIFY:** flash to real hardware; paste serial monitor output showing successful WiFi connection, real sensor readings, and successful (200-status) POST confirmations over at least 5 consecutive readings.

## T1B.11 · Sensor ingestion endpoint — `backend/stage1b/sensor/ingest.py` + `routes.py` · [P0] · depends: T1B.1

> **PROMPT**
> Goal: accept, validate, persist, and broadcast live sensor readings.
> Files you may touch: `backend/stage1b/sensor/ingest.py`, `backend/stage1b/sensor/__init__.py`, `backend/stage1b/routes.py`, `backend/stage1b/tests/test_sensor.py`.
> Requirements: implement, per the TRD:
> ```
> POST /api/sensor/reading
>   body: SensorReading (validated by Pydantic)
>   header: matches SENSOR_INGEST_TOKEN, reject with 401 if not
>   → persists the reading, broadcasts via WebSocket on
>     /ws/site/{site_id} with event type "sensor_reading_received"
>     (confirm this exact event shape against Stage 2/3/4's build
>     document if available, to avoid a mismatched contract there too)
> ```
> **VERIFY:** POST a real reading via `curl` with a valid token; paste the 200 response; paste evidence the reading was persisted (DB query) and confirm a WebSocket test client receives the broadcast event; also POST with an invalid token and paste the resulting 401.

## T1B.12 · Test suite completion — `backend/stage1b/tests/` · [P0] · depends: all above

> **PROMPT**
> Goal: complete, passing test suite.
> Files you may touch: everything under `backend/stage1b/tests/`.
> Requirements: ensure coverage of the terrain-adjustment math (T1B.7) determinism, the calibration honesty path (T1B.6, T1B.5's confidence flagging), the downscaling orchestration (T1B.8) using a mock `RegionalEnsembleForecast`, and the sensor ingestion endpoint (T1B.11) including the auth-rejection case. Mock all external network calls (Bhuvan, TN WRD) in automated tests.
> **VERIFY:** `pytest backend/stage1b/tests/ -v`; paste full real passing output.

---

# §D. Build order (time-boxed)

| Window | Tasks | Outcome |
|---|---|---|
| Hour 0–2 | T1B.0, T1B.1 | Scaffolding, DB/Redis working |
| Hour 2–5 | T1B.2, T1B.3 | Real DEM fetched and processed into terrain grids |
| Hour 5–8 | T1B.4, T1B.5 | TN WRD data fetched, nearest-station honesty check working |
| Hour 8–9 | T1B.6 | Calibration fitting (or honest no-op) working |
| Hour 9–11 | T1B.7, T1B.8 | Downscaling model producing valid `DownscaledForecastField` from mock input |
| Hour 11–12 | T1B.9 | API route live |
| Hour 12–14 | T1B.10 | Firmware flashed, posting real readings |
| Hour 14–15 | T1B.11 | Ingestion endpoint + WebSocket broadcast working end to end with real hardware |
| Hour 15–16 | T1B.12 | Full test suite passing |

---

# §E. Final acceptance — "Stage 1B is completely built" when:

1. A real DEM raster for the Vellore region is fetched and processed into elevation/slope/aspect grids — not placeholder/synthetic terrain data. ✅
2. `find_nearest_tnwrd_station` reports a real, computed distance and an honest `calibration_confidence`, never assumed positive. ✅
3. `GET /api/forecast/downscaled?site_id={}` returns a valid `DownscaledForecastField`, `source_forecast_id`-traceable to a real (or clearly mocked, during standalone dev) `RegionalEnsembleForecast`. ✅
4. The physical ESP32 unit successfully posts real readings to `POST /api/sensor/reading`, which persists and broadcasts them over WebSocket. ✅
5. Every external API/data source touchpoint (Bhuvan, TN WRD, ESP32 libraries) was implemented against documentation actually opened and confirmed in-session — cited in each task's VERIFY output. ✅
6. `pytest backend/stage1b/tests/ -v` passes completely with real pasted output. ✅
7. `mypy backend/stage1b/` passes with no errors. ✅
8. Only files under `backend/stage1b/` and `firmware/sensor_unit/` were created or modified. ✅

> If all eight hold, Stage 1B is built exactly as specified — ready to integrate with Stage 1A's output and hand off to Stage 2.
