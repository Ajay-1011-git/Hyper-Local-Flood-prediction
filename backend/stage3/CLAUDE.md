# STAGE 3 — Claude Code Operating Contract (READ EVERY SESSION)

## What Stage 3 is
Computes risk = hazard × exposure × vulnerability per building and per road
segment, using Stage 2's simulation output as hazard, Stage 2's GLB-derived
geometry as exposure, and a published fragility/depth-damage curve as
vulnerability. Outputs a ranked list with a confidence value per entry.

## GROUND TRUTH (never change without explicit human instruction)
- Only 3 buildings exist in this project's demo site: Building_01/02/03,
  per Stage 2's `BuildingFootprint` contract. Do not assume more buildings
  exist or generalize to an arbitrary count without checking Stage 2's
  actual output first.
- Hazard signal is depth AND velocity AND rate-of-rise together — never
  rank by depth alone. This is a explicit, non-negotiable project decision
  (established because depth-only ranking underestimates damage from fast,
  shallow flows).
- Vulnerability is a GENERAL, published approximation, not locally
  calibrated to VIT Vellore. This must be stated in the output data, not
  just in documentation — see §B.2's `vulnerability_is_local_calibration`
  field, which must always be `False` unless a human explicitly provides
  real local calibration data (none currently exists).
- Module boundaries: all code under `backend/stage3/`. Do not modify
  `backend/stage2/` or Stage 1A/1B. Import contracts, do not redefine them.

## ANTI-HALLUCINATION RULES
1. Never fabricate a population-density figure for the site. If no real
   population data source is confirmed available, omit population from
   exposure entirely rather than estimating it — this matches PRD §4.1's
   scope ("population density where available").
2. Never invent a specific numeric vulnerability/fragility curve without
   citing a real published source. If asked to implement one, search for
   and use an actual published depth-damage function, and record its
   source in code comments and in the output's `vulnerability_source` field
   — do not write an unsourced formula and label it a "fragility curve."
3. Road segmentation: Stage 2's Operating Contract confirms `Road_Network`
   was loaded as raw mesh geometry in T2.1 but was never subdivided into
   discrete segments (Stage 2 didn't need this — roads aren't obstacles in
   the physics simulation). That segmentation is this stage's job. Before
   writing segmentation code, confirm how Stage 2 actually exposes the raw
   `Road_Network` mesh data (check Stage 2's real code/API, don't assume
   a data access pattern).
4. Do not fabricate VERIFY output. Paste real numbers.

## ANTI-DRIFT RULES
5. Only touch files under `backend/stage3/`.
6. Do not modify Stage 2's contracts or its computational mesh. Read-only
   consumption of `SimulationResult` and `BuildingFootprint`.
7. Keep `DamageRankEntry` byte-aligned with what Stage 4 expects — confirm
   against the Stage 4 build document before finalizing field names.

## QUALITY GATES
- Type hints throughout; `mypy` clean.
- Every score (hazard/exposure/vulnerability/risk) is explainable — the
  output must retain the sub-scores, not just the final risk number, per
  PRD's Site Detail page requirement (user-flow §3.3).
- Idempotent computation: re-running for the same `SimulationResult` id
  produces the same ranking, not a new random ordering.

## WORKING METHOD
Plan → wait for go on multi-file tasks → implement → VERIFY with real
pasted output → tests → commit `feat(T3.<n>): <summary>`.

## DEFINITION OF DONE
Code runs, `mypy` clean, VERIFY passes with real output, tests pass,
contract matches Stage 4's expectation, only `backend/stage3/` touched.

---

## STOP — read this before implementing T3.1 or later

`SimulationResult` and `NodeState` (which every task from T3.1 onward
depends on) are **NOT a confirmed contract**. Every Stage 2/3/4 build doc
says to import them "verbatim from Stage 2," but no document in
`Flood_system_finial/` actually defines their fields — the docs reference
"an earlier combined Stage 2/3/4 document" that does not exist in this
repo (confirmed: grepped every field name across all four stage docs plus
the TRD; TRD §5.3's `SimulationNode` is the closest precedent and doesn't
match the newer docs' vocabulary or field names).

What exists right now, in `backend/shared/contracts.py`, is a
**reconstructed draft** — built by cross-referencing every direct
field/attribute mention found across the four stage docs (each field
individually commented CONFIRMED or UNCONFIRMED with its source). It is
there so Stage 3's scaffolding (T3.0) and prep work aren't blocked, and so
whoever builds Stage 2 sees an existing proposal to correct rather than
inventing their own independently (avoiding the exact duplicate-contracts
mistake already caught once during the Stage 1A/1B merge).

**Do not write T3.1 onward's actual business logic against the
UNCONFIRMED fields as if they were settled.** Confirm the real shape once
Stage 2's T2.6 (GNN)/T2.7 (ensemble aggregation) actually exists and
produces real output — or get it confirmed directly by whoever builds
Stage 2, in `backend/shared/contracts.py`, before depending on it.

### Added during T3.5 (2026-08-20) — `NodeState.building_id` / `road_segment_id`

T3.5's `rank_structures` needs to group hazard by structure, but
`NodeState` as drafted had no such link — `ComputationalMeshNode` (which
Stage 2's own doc confirms carries `building_id` for wall nodes) is
Stage-2-internal, never passed downstream. Added `building_id: Optional[str]`
and `road_segment_id: Optional[str]` to `NodeState` to close this gap,
with explicit user sign-off. Same caveat as everything else in this
section: UNCONFIRMED against Stage 2's real output, must be corrected
once Stage 2 exists — Ajay may instead expose `ComputationalMeshNode`
itself downstream, or use different field names.
