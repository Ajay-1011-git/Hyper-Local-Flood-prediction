# STAGE 4 — Claude Code Operating Contract (READ EVERY SESSION)

## What Stage 4 is
Renders the site (Stage 2's DEM-interpolated terrain + GLB buildings) in 3D
with an animated water surface driven by Stage 2's ensemble simulation
output, an uncertainty envelope that narrows on live sensor assimilation,
a damage overlay from Stage 3's ranking, and generates CAP-XML alerts in
multiple languages. Two audiences, two visual registers (dark ops dashboard,
light citizen view) — per the User Flow document's explicit design split.

## GROUND TRUTH (never change without explicit human instruction)
- Frontend stack is FIXED: React + TypeScript, react-three-fiber + drei,
  Vite, Tailwind CSS, Zustand (scene/UI state), TanStack Query (server
  data), native WebSocket API. Do not substitute any of these.
- The rendered terrain is DEM-interpolated, NOT a photogrammetry scan —
  Stage 2's `TerrainGrid.interpolated_from_regional_dem` is `True`. The
  frontend's `/about` page (per User Flow §3.7) must state this honestly
  as one of the platform's disclosed limitations — do not omit it.
- The 3D scene performs ZERO physics computation. Every hydraulic value
  (depth, velocity) comes from Stage 2's precomputed `NodeState` data,
  transmitted as already-aggregated statistics — never raw per-member
  ensemble data (per TRD §6, point 2).
- CORRECTED 2026-08-20 (see backend/stage3/CLAUDE.md's own ground-truth
  correction, confirmed against the real GLB during a full-system wiring
  audit): only **2** buildings exist in the real demo site —
  `Building_01`/`Building_02`. `Building_03` was replaced with garden/
  lawn/road assets in the real 3D model. Plus `Road_Network` segments
  from Stage 3 (41 real segments, see `road_segmentation.py`). Do not
  build UI assuming 3 buildings or an arbitrary/larger count.
- Module boundaries: backend alert code under `backend/stage4/`; frontend
  under `frontend/`. Do not modify Stage 1A/1B/2/3 backend code.

## ANTI-HALLUCINATION RULES
1. Before generating CAP-XML, search for and confirm the actual current
   CAP schema (namespace, exact element names, structure) and India's
   SACHET-specific field usage in this session — do not write XML against
   an assumed/remembered schema. The field CATEGORIES (severity, certainty,
   urgency, area polygon, effective/expiry) are confirmed real from the
   project's Architecture document, but the exact XML element names and
   namespace declaration must be verified, not guessed.
2. Before using react-three-fiber, drei, or any Three.js water-shader
   pattern, confirm current API/import syntax in this session — these
   libraries change between versions, do not assume from memory.
3. Never fabricate multilingual alert text quality — if translating into a
   language you're not confident in, flag it for human review rather than
   presenting machine-translated text as verified-accurate.
4. Do not fabricate screenshots, rendered output, or test results. Paste
   real output/screenshots.
5. If User Flow document details conflict with what's practically buildable
   in the time available, flag the conflict and ask rather than silently
   simplifying or silently building the full spec anyway.

## ANTI-DRIFT RULES
6. Only touch files under `backend/stage4/` and `frontend/`.
7. Do not modify Stage 2/3's contracts — consume `SimulationResult`,
   `TerrainGrid`, `BuildingFootprint`, `DamageRankEntry`, `SensorReading`
   exactly as defined in their respective build documents.
8. Keep the `Alert` contract byte-aligned with what's defined in §B.2 —
   do not add/rename fields without updating this document first.

## QUALITY GATES
- 3D scene maintains a smooth interactive frame rate on standard
  presentation hardware (TRD TNFR-1) — achieved via mesh decimation on the
  wider terrain and precomputed (not live) physics, not through cutting
  visual fidelity on the focal scanned/built site.
- CAP-XML output validates against the real, confirmed CAP schema.
- Every uncertainty/limitation statement required by the project's honesty
  principles is surfaced in the UI (About page, dashboard labels) — not
  only in code comments.
- Citizen view maintains high contrast, tested for outdoor/bright-light
  legibility (User Flow §7).

## WORKING METHOD
Plan → wait for go on multi-file tasks → implement → VERIFY with real
output/screenshots → tests → commit `feat(T4<section>.<n>): <summary>`.

## DEFINITION OF DONE
Code runs, `mypy`/`tsc` clean, VERIFY passes with real pasted output/
screenshots, tests pass, contracts unchanged, only permitted directories
touched.

---

## ADDENDUM — 2026-08-20: environment constraint, confirmed at T4A.0

This session's environment is a terminal with no persistent GUI/browser
session by default. Section B/C's screenshot-based VERIFY steps will use
a real headless-browser tool (confirmed and set up when Section B starts,
not assumed here) to capture genuine rendered output — never a
fabricated or hand-described "screenshot". If no such tool can be made to
work, this will be flagged explicitly before proceeding, per rule 5
above, rather than silently skipping the VERIFY requirement.
