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

---

## Where §B (canonical specs) lives
This file is §A only (per the build doc's instruction to paste it
verbatim). The full canonical spec — env vars (§B.1), the data contract
(§B.2), and the module file structure (§B.3) — lives in
`Flood_system_finial/stage1b_build_instructions.md` at the repo root.
Consult it before starting any task; the data contract itself is
implemented at `backend/shared/contracts.py` (imported into
`backend/stage1b/shared/contracts.py`).

## Correct import path (differs from T1B.0's literal VERIFY text)

T1B.0's VERIFY line says `python -c "from stage1b.shared.contracts import
...`" — that exact invocation does NOT work with this repo's layout, and
this is not a bug to fix by changing the code. It's a direct, necessary
consequence of the shared-contracts decision made during T1B.0 (confirmed
with the human): `backend/stage1b/shared/contracts.py` re-exports from
`backend/shared/contracts.py` (the single cross-stage source of truth —
see the paragraph above), and that cross-package import only resolves
when `backend` itself is on the path as the top-level package.

**The real, working invocation, from the repo root:**
```
python -c "from backend.stage1b.shared.contracts import DownscaledForecastField, SensorReading"
```
Every test in `backend/stage1b/tests/`, and every script used during this
stage's development, imports this way (`from backend.stage1b...`, `from
backend.shared...`) — that's the actual convention this module uses, not
the literal `stage1b.foo` shorthand in the build doc's prose.

## ADDENDUM — 2026-08-20: real DEM fetched/registered for VIT Vellore (done by Stage 2's session, with explicit permission)

Stage 2 needed a real `dem_metadata` row + real elevation GeoTIFF for the
real VIT Vellore site to unblock its T2.2 terrain interpolation, and the
user explicitly authorized touching Stage 1B for this one task (normally
out of scope per module ownership). What was done, for the record:

1. **Fixed `DATABASE_URL` in `.env`** (gitignored, local-only): it was
   `postgresql://localhost:5432/floodsystem` with no credentials, which
   cannot authenticate against the real running Postgres container
   (`floodsystem`/`floodsystem`, via `docker ps` → `stage1a-postgres`,
   PostGIS 16). Corrected to
   `postgresql://floodsystem:floodsystem@localhost:5432/floodsystem`.
2. **Found and fixed a live schema-drift bug**: the real `dem_metadata`
   table in the shared Postgres had only 5 columns (missing `id`,
   `raster_path` NOT NULL, `grid_resolution_km`, `fetched_at`) —
   created by Stage 2's own integration test calling
   `_metadata.create_all()` on its own read-only column-subset
   `Table` definition (`stage2/terrain/dem_source.py`) before this
   module's real `init_models()` ever ran. Fixed by dropping that
   incomplete table and running `backend.stage1b.db.init_models()` for
   real, producing the correct canonical schema. Stage 2's test that
   caused this was also fixed (no longer calls `create_all` on a table
   it doesn't own; skips cleanly if the table doesn't exist yet instead).
3. **Fetched a real CartoDEM raster** via the already-implemented
   `dem.client.fetch_dem_raster` (Bhoonidhi API, real credentials in
   `.env`, live-verified: real 200 auth response, real ~47MB tile
   download) for a bbox centered on the real site (12.969103, 79.156332
   — confirmed via the GLB's anchor-point fit, not the stale
   `TARGET_SITE_LAT`/`TARGET_SITE_LON` placeholder still in `.env`),
   padded ±0.02° (~2.2km) for catchment context. Real tile:
   `data/dem/dem_e107453e61d9e73f.tif` (1° CartoSat-1 tile,
   lat 12–13°N / lon 79–80°E, EPSG:4326, elevation range roughly
   -551m to 980m raw, with the documented ~7% void-pixel issue).
4. **Ran `dem.processing.compute_and_persist_terrain_grids`** for real
   (`grid_resolution_km=2.0`, matching this module's regional-terrain
   convention), producing a real 3-band terrain GeoTIFF
   (`data/dem/dem_e107453e61d9e73f_terrain.tif`) and updating the
   `dem_metadata` row (`id=1`) with `terrain_grid_path`/
   `grid_resolution_km`. Verified end-to-end: Stage 2's
   `find_terrain_grid_path(12.969103, 79.156332)` resolves this real
   path, and `interpolate_terrain` against it produces real, finite,
   physically plausible elevation values (~118.3–119.3m across the real
   site footprint — not the placeholder 216m used throughout Stage 2's
   synthetic tests/fixtures).
5. Both `.tif` files are gitignored (`data/dem/`, matches `*.tif`), not
   committed — this is real local data, not a fixture. `dem_raster_path`
   is `data/dem/...` (relative to the repo root); run any script that
   consumes it from there.
6. **Not addressed / still open**: the `TARGET_SITE_LAT`/`TARGET_SITE_LON`
   values in `.env` (12.9165, 79.1325) were left unchanged — they're
   ~6km from the real site's anchor-fit location and look like a stale
   placeholder from before the real 3D model was surveyed, but updating
   them wasn't asked for and may affect Stage 1B's own downscaling
   target-site logic in ways only the module's owner should decide.
   Flag for the teammate.

## ADDENDUM — 2026-08-20: deep audit of Stage 1B (DEM, TN WRD, downscaling, wiring)

Everything below was found by running Stage 1B's real code against real
data and real infrastructure, not by inspection.

### Confirmed genuinely real and working (no change needed)

1. **TN WRD telemetry is real**: a live CKAN fetch returned **174,340 real
   rows across 145 real stations**, spanning 2003-04-24 → 2026-08-18.
2. **The nearest-station lookup is real and now favourable**: against the
   corrected site coordinates (12.969223, 79.155934 — the real
   GLB-surveyed anchor, standardized earlier the same day), the real
   `Vellore` station is **2.944 km** away, so
   `calibration_confidence = "calibrated_nearby_station"` is a real,
   earned value — not the honest-fallback path.
3. **DEM/terrain sampling is real**: the real registered terrain GeoTIFF
   samples at the real site to `elevation=119.63m, slope=0.328°,
   aspect=152.37°` — physically plausible for Vellore, not NaN or a
   placeholder.
4. **The route works end-to-end, live**: real uvicorn + real curl →
   HTTP 200, `X-Regional-Forecast-Source: stage1a_live` (real Stage 1A
   integration), `site_id=vit-vellore`, real non-zero downscaled values,
   real DB persistence, and `X-Cache: miss → hit-redis` with byte-identical
   bodies (18.7s → 0.046s).

### Two real defects found and fixed

5. **`fit_calibration` (T1B.6) was permanently dead code.** It was fully
   built and tested, but **nothing in production ever called it** —
   `routes.py` hardcoded `IDENTITY_COEFFICIENTS`. That was correct when
   written (Stage 1A had no archive), but it meant the path would never
   run *even once the archive existed*. Stage 1A now really does persist
   every forecast it serves, so this was fixed: new
   `downscaling/calibration_data.py` builds real matched (observed,
   coarse) pairs from Stage 1A's real `regional_ensemble_forecast` table
   plus real TN WRD readings, and `_get_calibration_coefficients` now
   attempts a **real fit**, falling back to identity only as a *measured*
   outcome. Real log line from the live run:

       Calibration attempted against real data and declined: 0 matched
       sample(s) (need 20) from 8 archived regional forecast(s) and 1167
       reading(s) at station 'Vellore' — using identity/no-op coefficients

   **Downscaling is therefore still a pass-through today, and that is the
   honest state, not a bug**: the real `Vellore` station's readings stop
   at 2026-08-08, while the archive's forecasts are valid from 2026-08-19
   — an 11-day gap, so zero overlap. It will begin fitting for real, by
   itself, once both sides advance far enough to overlap by
   `MIN_CALIBRATION_SAMPLES` (20) matched pairs. Note the real
   single-station limit: one station means one constant terrain triple,
   so only the intercept is ever identifiable — `fit_calibration` reports
   the rest via `unidentifiable_terrain_parameters` rather than
   fabricating terrain coefficients.

6. **The TN WRD fetch was uncached, on the per-request path.** The old
   call site's comment claimed it was "cheap enough ... to do
   per-request"; measured live, it is **~24MB / 174,340 rows / ~16-17s**.
   Fixed with an in-process TTL cache (`TELEMETRY_CACHE_TTL_S = 1800s`,
   deliberately under the dataset's own hourly update cadence, so no real
   update can be missed), plus `force_refresh=True` to bypass. Measured
   after the fix: **16.00s → 0.0000s** on the second call.
   A regression this introduced was caught by the suite and fixed too:
   the module-level cache leaked between tests
   (`test_fetch_deduplicates_across_resources` failed `0 == 2`, i.e. zero
   downloads attempted) — `tests/conftest.py` now clears it around every
   test.

### Verification

`pytest backend/stage1b/tests/` → **88 passed** (was 78; 10 new: 3 cache
tests, 7 calibration-data tests including real Postgres round-trips).
`mypy .` from `backend/stage1b/` → clean, 31 source files.
