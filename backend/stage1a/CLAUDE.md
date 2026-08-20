# ADDENDUM — READ THIS FIRST (2026-08-19)

The body below is the ORIGINAL operating contract, kept verbatim as
historical record per the build doc's own instruction. It is now **out of
date on one point: GenCast.**

**GenCast has been removed entirely.** The human running this project has
no TPU/JAX access or GenCast credentials, and never will for this build.
The `gencast/` module (client, parser, fallback, devdata) was deleted
outright — not deprioritised, not kept as a dead fallback. The directory
that used to be `gencast/` is now `forecast/`, holding only the
model-agnostic orchestration (source chain, Celery task, persistence,
provenance) that survives regardless of which model is behind it.

**Current regional forecast source chain**: **GEFS** (`gefs/` — REAL and
PRIMARY as of 2026-08-20, see the addendum below) → **WeatherNext 2
Cyclones Mini** (`wn2mini/` — real, confirmed-working, a file a human
manually exports from Colab and copies into `data/wn2_mini/`, now the
FALLBACK). If neither produces a forecast, the API returns a 503 — there
is no further fallback.

**2026-08-20 — reconfirmed, do not reopen this.** A document later landed
in this repo (`Flood_system_finial/stage1a_amendment_2_source_priority_correction.md`)
proposing GenCast be restored as a third, last-resort tier. Checked
directly with the project owner: that is not correct — GenCast has no
available credentials and stays fully removed, including as a fallback.
That document has its own superseding notice now. GEFS → WeatherNext 2
Mini is the complete, final chain. Do not resurrect any GenCast code for
any reason without the project owner explicitly asking again, in this
conversation, not via a doc found in the repo.

---

# ADDENDUM 2 — 2026-08-20: GEFS built for real, now the PRIMARY source

Requested directly by the project owner: *"the gefs(0.25) is the main
prediction and weathernext 2 mini is a stub... this helps us to be more
accurate in resolution for downscaling."* GEFS was previously an honest
always-raising stub; it is now a real, working, live-verified client.

**Why:** GEFS's native 0.25° grid (~27.75 km) is ~4× finer than WN2
Mini's 1.0° (~111 km). Stage 1B's terrain-based downscaling starts from
this regional field, so the finer input is a real accuracy gain — which
is the whole point of the change. GEFS is also fully automated (no manual
Colab export step), so it is the correct primary regardless.

**Real, live-confirmed facts** (fetched and decoded in-session, never
assumed — see `gefs/client.py` and `gefs/parser.py` module docstrings):
- 31 real ensemble members: `c00` control + `p01..p30` (confirmed via
  `GRIB_totalNumber: 30` on a real perturbation member's GRIB metadata).
  `geavg`/`gespr` are derived statistics, never fetched as members.
- Precipitation is GRIB `APCP` → cfgrib short name `tp`, units
  `kg m**-2`, which is 1:1 with mm.
- `GRIB_stepType: accum` accumulates over the interval BETWEEN output
  times, not since init — confirmed empirically (f003/f006/f009 gave
  0.235/0.308/0.121 mm, non-monotonic, ruling out cumulative-since-init),
  so each fetched value is that period's rainfall directly, no diffing.
- 6-hourly cadence here is a STATED SIMPLIFICATION, not the product's
  limit (it publishes 3-hourly): 31 × 12 = 372 requests/cycle instead of
  744. The 0.25° spatial gain this change is for is unaffected.

**Two real transports, S3 primary / NOMADS fallback.** This priority is a
measured decision, not a preference: NOMADS's GRIB-filter CGI is a shared,
rate-limited government service that demonstrably load-shed a real
372-request full-cycle fetch this session (HTTP 302 → HTML error page on
URLs that had succeeded moments earlier), silently costing GEFS the chain
and handing it to WeatherNext. NOAA's Open Data S3 bucket has no such
limit; the honest cost is bandwidth (~287 KB per record — the global APCP
field, since S3 cannot subset server-side — vs NOMADS's ~750 B, i.e.
~107 MB vs ~280 KB per full cycle). That runs out-of-band in Celery once
per 6-hour cycle (TRD §4), so reliability wins. NOMADS is kept as a real
fallback for when S3 is unreachable.

**Three real bugs found and fixed while building this** (all confirmed by
live behaviour, not inspection):
1. httpx's `params=` kwarg REPLACED the URL's existing query string
   rather than merging, silently dropping `file=`/`dir=` — NOMADS then
   returned an HTML error page for every request. Fixed by building one
   complete query string.
2. Redirects weren't followed (`follow_redirects` defaults to False), so
   real 302s were treated as "cycle unavailable".
3. `test_db.py::test_repeated_task_runs_leave_exactly_one_row` called the
   real chain 3× — with GEFS real, that meant ~1100 live requests, and
   its assertion used `wn2mini.build_forecast_id`, so it would have
   FAILED outright once GEFS started succeeding. Now simulates
   GEFS-unavailable (it tests persistence idempotency, not source
   selection).

**Testing convention:** every automated test mocks the network. Chain
tests that exercise the WN2 fallback must simulate GEFS-unavailable, or
they make real live NOMADS/S3 calls and their result depends on live
availability rather than this code. Tests that genuinely hit third-party
services (CWC portal) are now opt-in behind `RUN_LIVE_NETWORK_TESTS=1`
(`tests/conftest.py`'s `requires_live_network`) — they had made the
default suite take ~2 minutes and fail on a government portal's
availability; confirmed real when enabled, and the portal did in fact
time out on one of them.

**Real VERIFY (live, full chain, pasted):**
```
=== FULL CHAIN (GEFS primary, S3 transport) ===
elapsed: 93.0s
source: GEFS
path: gefs
resolution_km: 27.75
generated_at: 2026-08-20 06:00:00+00:00
members: 31
timesteps/member: 12
72h regional-mean rainfall: min=2.84 mean=5.26 max=9.40 mm
member0 first 4 steps: [(6, 0.517), (12, 0.687), (18, 1.182), (24, 0.37)]
```
Suite: 76 passed, 3 skipped in 2.77s (down from 125.85s); mypy clean, 34
source files.

**Downstream note (flagged, not silently absorbed):** GEFS provides 31
members at 27.75 km; WN2 Mini provides 8 at 111 km. Any consumer that
assumed 8 members or 111 km must read `RegionalEnsembleForecast.members`
/ `.resolution_km` rather than hardcoding — the values differ by source,
and `source` says which produced a given forecast.

---

Anywhere below this line says "GenCast," read it as historical context for
why the contracts/architecture look the way they do (§B.2's
`RegionalEnsembleForecast.source` field, the 50+ member language in §E,
etc.) — not as a live requirement. Do not resurrect GenCast-calling code
without the human explicitly asking for it again.

---

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

## ADDENDUM 3 — 2026-08-20: real bug found live-testing GEFS, fixed

Found during a full-system wiring audit (a different session, with the
project owner's explicit go-ahead to fix it): `get_regional_forecast()`
(the whole point of which is to gracefully degrade GEFS → WN2 Mini → 503)
**crashed** on real live network calls (`httpx.RemoteProtocolError`, then
separately `httpx.ReadTimeout`) instead of falling through. Root cause:
`gefs/client.py`'s `_fetch_one_s3`/`_fetch_one` only checked HTTP status
codes on a returned response — neither wrapped the actual `client.get()`
call in a `try/except`, so a real network-level failure (not an HTTP
response at all) propagated uncaught. `cwc/client.py` already had the
correct pattern (`except httpx.HTTPError`, the base class covering both
network and status-code failures) — GEFS's was narrower and missed that
whole class of real failure.

Fixed: both call sites now catch `httpx.HTTPError` and convert it to
`GEFSUnavailableError`, letting the existing retry/transport-fallback
logic (S3 → NOMADS → cycle retry → WN2 Mini) work as originally designed.
5 new regression tests added to `tests/test_gefs_client.py` (network
errors on both S3 call sites, NOMADS retry-then-succeed and
exhausted-retries paths, and an end-to-end S3-network-error →
NOMADS-fallback check) — none of this class of failure was covered
before, which is how it shipped.

Real VERIFY: re-ran the real live fallback chain after the fix —
`source=GEFS, resolution_km=27.75, 31 members, 12 timesteps,
provenance.path=ForecastPath.GEFS` — succeeded cleanly this time (real
network conditions vary run to run; the point of the fix is that a
transient failure no longer crashes the whole chain, not that failures
stop happening). 84/84 tests pass (was 79 — 5 new), mypy clean (34
source files, only the pre-existing Celery stub note).
