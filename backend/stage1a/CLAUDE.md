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
