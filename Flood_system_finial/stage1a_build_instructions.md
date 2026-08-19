# STAGE 1A — Complete Build Instructions for Claude Code
### Drift-proof, hallucination-resistant prompts aligned to the project's Architecture, TRD, and PRD documents

> **Purpose.** This document builds Stage 1A — regional forecast acquisition (GenCast + CWC) — exactly as specified in the project's Architecture and TRD documents. Every task cites what it implements and copies the shared data contract **verbatim**. Follow tasks in order. Do not skip **§A Operating Contract** or **§B Canonical Specifications** — they are what keep Claude Code from hallucinating, erroring, or drifting.
>
> **Alignment guarantee.** The stack choices, data models, and endpoint shapes below are transcribed directly from the project's Architecture (`flood_system_architecture.md`) and TRD (`flood_system_TRD.md`) documents. If any prompt here seems to disagree with those documents, **those documents win** — stop and reconcile before proceeding.
>
> **Partner module.** Stage 1B (built separately, by a different team member) consumes your output through the `RegionalEnsembleForecast` contract in §B.2. You do not need Stage 1B's code to complete or verify your own work — your task is done when your own endpoints return valid, schema-conforming data, independent of whether Stage 1B exists yet.

---

# §A. Operating Contract — paste this into `CLAUDE.md` first

> This is the standing instruction set for every Claude Code session on this module. Put it verbatim at the top of `CLAUDE.md` in the `stage1a/` module root.

```md
# STAGE 1A — Claude Code Operating Contract (READ EVERY SESSION)

## What Stage 1A is
Stage 1A is the regional forecast acquisition layer of a hyperlocal flood
prediction system. It has exactly two jobs: (1) run GenCast (DeepMind's
open-weights AI ensemble weather model) to produce a 72-hour, 50+ member
regional rainfall ensemble, and (2) fetch an independent river/reservoir
stage forecast from India's Central Water Commission (CWC). Both outputs
are structured into fixed Pydantic contracts and exposed via FastAPI so
Stage 1B (built separately) can consume them.

## GROUND TRUTH (never change without explicit human instruction)
- Stack is FIXED: Python, FastAPI (async), Pydantic, PostgreSQL+PostGIS,
  Redis, Celery. Do not substitute a different framework or database.
- GenCast is inference-only in this project — never write training code
  for it. It runs on published open weights.
- Module boundaries: ALL code for this stage lives under `backend/stage1a/`.
  Do not create files outside this directory. Do not modify Stage 1B's
  directory (`backend/stage1b/`) or Stage 2/3/4 code if present.
- The data contract in §B.2 is shared verbatim with Stage 1B's build
  document. Do not rename fields, change types, or "improve" the schema —
  any change breaks the other team member's independently-built code.

## ANTI-HALLUCINATION RULES (hard rules)
1. Never invent API endpoints, request/response shapes, or SDK method names
   for GenCast, CWC's National Water Data Portal, or India-WRIS. Before
   writing ANY code that calls one of these, search for and read its actual
   current documentation/repository IN THIS SESSION and confirm the exact
   shape. If you cannot verify a shape, STOP and ask the human — do not
   guess and proceed as if verified.
2. Never assume a Python package exists or has a given API without checking
   PyPI/its repository first. Pin the resolved version in `requirements.txt`.
3. If a type or contract already exists in §B.2, IMPORT/reuse it. Never
   create a second, slightly different definition of the same concept.
4. If a requirement below is ambiguous or underspecified, ask ONE
   clarifying question instead of assuming. State any unavoidable
   assumption explicitly in code comments and in the task's completion
   summary.
5. Do not fabricate test results, file contents, or command output. Run
   the actual VERIFY commands and paste their real output.
6. Where CWC/India-WRIS station data cannot be confirmed to actually cover
   a station near the target site (Vellore, Tamil Nadu), do not assume one
   exists — implement the honest `station_proximity_verified: bool = False`
   path and say so explicitly in output.

## ANTI-DRIFT RULES (hard rules)
7. Only create/modify the files listed in a task's "Files you may touch."
   If you must touch another file, list it and explain BEFORE editing.
8. Do not refactor unrelated code. Do not add features not requested in
   the task. Do not restructure the module layout beyond what's specified.
9. Keep the `RegionalEnsembleForecast` and `RiverStageForecast` models
   byte-aligned with §B.2 — field names and types must match exactly.

## QUALITY GATES (must hold at end of every task)
- Python type hints on all functions; `mypy` passes with no errors.
- Pydantic validates ALL external data (GenCast output, CWC responses)
  at the point it enters the system — never pass raw dict/JSON deeper
  into the codebase unvalidated.
- No secrets or API keys committed to code — all via `.env`, loaded
  through a config module, listed in `.env.example` with blank values.
- Every function that persists data is idempotent — re-running it for
  the same forecast window updates/overwrites, it does not duplicate rows.
- Errors are typed and structured (custom exception classes); never
  swallow an exception silently or return a fabricated default value
  in place of a real failure.

## WORKING METHOD (every task)
A. First output a SHORT PLAN: the files you'll create/modify and your
   approach. For any task touching more than one file, WAIT for "go"
   before writing, unless explicitly told to run autonomously.
B. Implement only what the task asks.
C. Run the task's VERIFY commands. Paste the real, actual output. If
   anything fails, fix it before claiming the task done. Do not mark a
   task done on unverified work.
D. Add/extend tests for any new behaviour — no new function ships
   without a corresponding test.
E. Commit once per task, message format: `feat(T1A.<n>): <summary>`
   (or `fix`/`chore` as appropriate).

## DEFINITION OF DONE
A task is done only when: the code runs and imports cleanly, `mypy`
passes, the task's VERIFY block passes with real pasted output, tests
pass, the data model matches §B.2 exactly, and only the files listed
in "Files you may touch" were changed.
```

---

# §B. Canonical Specifications (single source of truth)

> Every task below imports from here. Do not paraphrase field names or types.

## B.1 Environment variables (`.env.example`, create at `backend/stage1a/.env.example`)

```
# ---- GenCast (regional ensemble weather forecast) ----
GENCAST_WEIGHTS_PATH=            # path or URL to published GenCast weights
GENCAST_TPU_ENDPOINT=            # TPU/JAX inference endpoint, if using remote compute
GENCAST_PRECOMPUTED_FALLBACK_DIR=./data/gencast_precomputed  # local cache/fallback forecasts

# ---- CWC / India-WRIS (river & reservoir stage forecast) ----
CWC_DATA_PORTAL_BASE_URL=        # confirm exact base URL in T1A.6 before hardcoding
INDIA_WRIS_BASE_URL=             # confirm exact base URL in T1A.6 before hardcoding

# ---- Storage ----
DATABASE_URL=postgresql://localhost:5432/floodsystem
REDIS_URL=redis://localhost:6379/0

# ---- Target site (for river-stage nearest-station lookup) ----
TARGET_SITE_LAT=
TARGET_SITE_LON=
```

## B.2 Data contract (Pydantic — `backend/stage1a/shared/contracts.py`)

> **This exact file must also exist, byte-identical, in Stage 1B's module.** If you and the Stage 1B builder are working in the same repo, this file should be created ONCE in a shared location (`backend/shared/contracts.py`) and imported by both — confirm with the human which arrangement applies before duplicating it.

```python
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
```

## B.3 Module file structure (target end state)

```
backend/stage1a/
├── CLAUDE.md                    # §A, pasted verbatim
├── .env.example                 # §B.1
├── shared/
│   └── contracts.py             # §B.2 (or imported from backend/shared/)
├── gencast/
│   ├── __init__.py
│   ├── client.py                # T1A.2
│   ├── parser.py                # T1A.3
│   ├── fallback.py              # T1A.4
│   └── tasks.py                 # T1A.5 (Celery)
├── cwc/
│   ├── __init__.py
│   ├── client.py                # T1A.6
│   └── parser.py                # T1A.7
├── routes.py                    # T1A.8
├── db.py                        # persistence helpers
├── config.py                    # env loading
└── tests/
    ├── test_gencast.py
    ├── test_cwc.py
    └── test_routes.py
```

---

# §C. Tasks

## T1A.0 · Module scaffolding — `backend/stage1a/` · [P0] · depends: none

> **PROMPT**
> Goal: create the module skeleton so every later task has somewhere to land.
> Files you may touch: everything under `backend/stage1a/` (new directory).
> Requirements: create the folder structure in §B.3 (empty files with module docstrings where code doesn't exist yet); create `config.py` that loads all variables from §B.1 via `pydantic-settings` (verify this package's current API before using — do not assume its interface); create `.env.example` exactly as in §B.1; paste §A verbatim into `CLAUDE.md`; paste §B.2 verbatim into `shared/contracts.py`; initialize `requirements.txt` with pinned versions for: fastapi, pydantic, pydantic-settings, sqlalchemy, psycopg2 (or asyncpg — confirm which fits the project's async requirement before choosing), celery, redis, pytest — verify each package's latest stable version on PyPI before pinning, do not guess a version number.
> **VERIFY:** `pip install -r requirements.txt` completes with no errors; `python -c "from stage1a.shared.contracts import RegionalEnsembleForecast, RiverStageForecast"` runs with no import error; paste both outputs.

## T1A.1 · Database & Redis connection layer — `backend/stage1a/db.py` · [P0] · depends: T1A.0

> **PROMPT**
> Goal: a working, tested connection to PostgreSQL and Redis before any task tries to persist data through it.
> Files you may touch: `backend/stage1a/db.py`, `backend/stage1a/tests/test_db.py`.
> Requirements: implement `get_db_session()` and `get_redis_client()` using the connection strings from `config.py`. Create the PostgreSQL tables for `regional_ensemble_forecast` and `river_stage_forecast` matching §B.2's fields (use SQLAlchemy or raw SQL migration — verify SQLAlchemy's current async session API before using it if choosing that route, do not assume the API from memory). Enable the PostGIS extension if not already enabled, since `lat`/`lon` fields on `RiverStageForecast` should be indexed as geospatial data for later nearest-station queries.
> **VERIFY:** run the migration/table creation against a local PostgreSQL instance; paste the `\dt` (or equivalent) output showing both tables exist; paste a successful `PING` response from the Redis client.

## T1A.2 · GenCast inference client — `backend/stage1a/gencast/client.py` · [P0] · depends: T1A.0

> **PROMPT**
> Goal: run GenCast inference for a given region and time window, returning raw model output.
> Files you may touch: `backend/stage1a/gencast/client.py`, `backend/stage1a/gencast/__init__.py`, `backend/stage1a/tests/test_gencast.py`.
> Requirements: **before writing any inference-calling code, search for and open GenCast's actual repository/documentation in this session and confirm its real Python calling convention, input format, and output shape — do not write code against an assumed API.** Implement `run_gencast_inference(bbox: BoundingBox, forecast_start: datetime) -> <raw model output type, determined by what you find in the real docs>`. This function should call the verified inference path (TPU/JAX per the confirmed docs) and return the model's native output, unparsed — parsing into `RegionalEnsembleForecast` is T1A.3's job, not this one's.
> If GenCast's real invocation requires resources (weights, TPU access) not available in this environment, implement the function to raise a clearly typed `GenCastUnavailableError` rather than returning fabricated data — the fallback path (T1A.4) is the correct way to handle this, not a fake success return.
> **VERIFY:** paste the exact documentation source(s) you consulted to confirm the calling convention; run the function against either real or mocked inference and paste the raw output shape; confirm `GenCastUnavailableError` is raised (not swallowed) when inference cannot run.

## T1A.3 · GenCast output parser — `backend/stage1a/gencast/parser.py` · [P0] · depends: T1A.2

> **PROMPT**
> Goal: convert GenCast's raw native output into the project's `RegionalEnsembleForecast` contract.
> Files you may touch: `backend/stage1a/gencast/parser.py`, `backend/stage1a/tests/test_gencast.py`.
> Requirements: implement `parse_gencast_output(raw_output, bbox: BoundingBox) -> RegionalEnsembleForecast`. Map GenCast's actual member/timestep structure (confirmed in T1A.2) onto `EnsembleMember`/`TimestepValue`. Generate `forecast_id` as a deterministic hash of `(bbox, forecast_start)` so re-running for the same window is idempotent, not a new random ID each time. Validate the result against the Pydantic model before returning — if any required field cannot be populated from the raw output, raise a typed error rather than filling it with a placeholder.
> **VERIFY:** run the parser against a real or fixture-captured raw GenCast output; paste the resulting `RegionalEnsembleForecast` (as JSON) with at least 2 members and a full 72-hour trajectory; confirm re-parsing the same input twice produces the same `forecast_id`.

## T1A.4 · GenCast fallback loader — `backend/stage1a/gencast/fallback.py` · [P1] · depends: T1A.3

> **PROMPT**
> Goal: when live inference is unavailable (`GenCastUnavailableError`), load a precomputed forecast instead of failing the whole pipeline.
> Files you may touch: `backend/stage1a/gencast/fallback.py`, `backend/stage1a/tests/test_gencast.py`.
> Requirements: implement `load_precomputed_forecast(bbox: BoundingBox, forecast_start: datetime) -> RegionalEnsembleForecast`, reading from `GENCAST_PRECOMPUTED_FALLBACK_DIR`. If no matching precomputed file exists for the requested window, raise a typed `NoFallbackAvailableError` — do not silently return an empty or fabricated forecast. Wire this as the fallback path in a new `get_regional_forecast(bbox, forecast_start)` function that tries live inference first, falls back on `GenCastUnavailableError`, and clearly logs/marks in the returned object's metadata which path was used (add a non-breaking way to signal this — check with the human before adding a field to the shared contract, since that contract must stay byte-aligned with Stage 1B's copy).
> **VERIFY:** with `GENCAST_TPU_ENDPOINT` intentionally unset/invalid, confirm `get_regional_forecast` falls back correctly and returns a valid `RegionalEnsembleForecast`; paste the output and confirm which path (live/fallback) was used is discoverable.

## T1A.5 · GenCast Celery task + persistence — `backend/stage1a/gencast/tasks.py` · [P0] · depends: T1A.1, T1A.4

> **PROMPT**
> Goal: run GenCast forecasting as a background job, not inline in a request handler, and persist the result.
> Files you may touch: `backend/stage1a/gencast/tasks.py`, `backend/stage1a/tests/test_gencast.py`.
> Requirements: **before writing Celery task code, verify Celery's current task-definition API in this session — do not assume the decorator/config syntax from memory.** Implement a Celery task `generate_regional_forecast_task(bbox_dict, forecast_start_iso)` that calls `get_regional_forecast`, persists the resulting `RegionalEnsembleForecast` to PostgreSQL (via `db.py`) keyed by `forecast_id`, caches it in Redis with a TTL matching the forecast window, and is idempotent — re-running for the same window updates the existing row rather than inserting a duplicate.
> **VERIFY:** trigger the task twice for the same window; paste evidence (a DB query) showing exactly one row exists for that `forecast_id`, not two.

## T1A.6 · CWC / India-WRIS data client — `backend/stage1a/cwc/client.py` · [P0] · depends: T1A.0

> **PROMPT**
> Goal: fetch real river/reservoir gauge data from CWC's data infrastructure.
> Files you may touch: `backend/stage1a/cwc/client.py`, `backend/stage1a/cwc/__init__.py`, `backend/stage1a/tests/test_cwc.py`.
> Requirements: **before writing any request code, search for and confirm the actual current access method for CWC data — the National Water Data Portal (`nwdp.nwic.gov.in`) and/or India-WRIS (`indiawris.gov.in`) — in this session. Confirm the real base URL, whether it's a direct file download, a REST API, or requires a different access pattern, and the real response format (CSV/JSON/other). Do not write code against an assumed REST shape.** Implement `fetch_station_list() -> List[dict]` and `fetch_station_data(station_id: str) -> raw response`, using whatever access pattern you actually confirmed. If the confirmed access method differs materially from a simple GET request (e.g., requires a download-then-parse step), implement it as found — do not force it into an assumed shape.
> **VERIFY:** paste the exact source(s) consulted to confirm the access method; run `fetch_station_list()` and paste at least 3 real station entries with their coordinates.

## T1A.7 · CWC nearest-station lookup + parser — `backend/stage1a/cwc/parser.py` · [P0] · depends: T1A.6

> **PROMPT**
> Goal: find the station nearest the target site and structure its data into `RiverStageForecast`.
> Files you may touch: `backend/stage1a/cwc/parser.py`, `backend/stage1a/tests/test_cwc.py`.
> Requirements: implement `find_nearest_station(target_lat, target_lon, stations: List[dict]) -> dict` using a real distance calculation (e.g., haversine) against the station list from T1A.6 — not an assumption. Implement `parse_station_forecast(raw_data, station: dict, target_lat, target_lon, proximity_threshold_km: float) -> RiverStageForecast`, setting `station_proximity_verified = True` only if the computed distance is within `proximity_threshold_km` (make this a config value, default conservatively, e.g. 25km, and flag this default as something the human should review, not a verified-correct number). If no station is found within threshold, still return a `RiverStageForecast` from the nearest available station but with `station_proximity_verified = False` — never fail silently or fabricate a closer station.
> **VERIFY:** run against real fetched station data for `TARGET_SITE_LAT`/`TARGET_SITE_LON` (Vellore); paste the resulting `RiverStageForecast` including the actual computed distance to the nearest station and the resulting `station_proximity_verified` value.

## T1A.8 · FastAPI routes — `backend/stage1a/routes.py` · [P0] · depends: T1A.5, T1A.7

> **PROMPT**
> Goal: expose both forecasts over HTTP exactly as specified in the TRD.
> Files you may touch: `backend/stage1a/routes.py`, `backend/stage1a/tests/test_routes.py`.
> Requirements: implement, per `flood_system_TRD.md` §5.1:
> ```
> GET /api/forecast/regional
>   → returns the latest cached RegionalEnsembleForecast for the configured
>     target region, triggering T1A.5's Celery task if none exists for the
>     current 72h window
>
> GET /api/forecast/river-stage?lat={}&lon={}
>   → returns the RiverStageForecast for the nearest station to the given
>     coordinates, via T1A.7
> ```
> Both responses must validate against their Pydantic model before being returned (FastAPI does this automatically via `response_model` — use it, do not manually serialize).
> **VERIFY:** start the FastAPI app; `curl` both endpoints; paste both real JSON responses, confirming they validate against §B.2's schema.

## T1A.9 · Test suite completion — `backend/stage1a/tests/` · [P0] · depends: T1A.8

> **PROMPT**
> Goal: a complete, passing test suite covering every task above.
> Files you may touch: everything under `backend/stage1a/tests/`.
> Requirements: ensure unit tests exist for the GenCast parser (T1A.3), the fallback path (T1A.4), the CWC nearest-station distance calculation (T1A.7), and integration tests for both routes (T1A.8) using mocked external calls (do not hit real GenCast/CWC infrastructure in the automated test suite — mock at the client boundary). Add a test confirming the full flow's idempotency (T1A.5's duplicate-prevention).
> **VERIFY:** `pytest backend/stage1a/tests/ -v`; paste the full real output showing all tests passing.

---

# §D. Build order (time-boxed)

| Window | Tasks | Outcome |
|---|---|---|
| Hour 0–2 | T1A.0, T1A.1 | Module scaffolding, DB/Redis connections working |
| Hour 2–6 | T1A.2, T1A.3 | GenCast inference verified and parsing correctly |
| Hour 6–8 | T1A.4, T1A.5 | Fallback path + Celery/persistence working, idempotent |
| Hour 8–11 | T1A.6, T1A.7 | CWC data client + nearest-station lookup working |
| Hour 11–13 | T1A.8 | Both API routes live and returning valid data |
| Hour 13–15 | T1A.9 | Full test suite passing |

---

# §E. Final acceptance — "Stage 1A is completely built" when:

1. `GET /api/forecast/regional` returns a real, schema-valid `RegionalEnsembleForecast` with 50+ members, sourced from either live GenCast inference or the documented fallback, with the active path discoverable. ✅
2. `GET /api/forecast/river-stage?lat={}&lon={}` returns a real, schema-valid `RiverStageForecast`, with `station_proximity_verified` reflecting a real, computed distance check — not assumed true. ✅
3. Re-triggering forecast generation for the same window does not create duplicate database rows. ✅
4. Every external API call (GenCast, CWC/India-WRIS) was implemented against a documentation source actually opened and confirmed in-session, not assumed from memory — cited in each task's VERIFY output. ✅
5. `pytest backend/stage1a/tests/ -v` passes completely, with real pasted output. ✅
6. `mypy backend/stage1a/` passes with no errors. ✅
7. Only files under `backend/stage1a/` (plus the shared contract location, if agreed) were created or modified. ✅

> If all seven hold, Stage 1A is built exactly as specified — ready for Stage 1B and Stage 2 to consume its output.
