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
