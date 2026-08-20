# STAGE 3 — Complete Build Instructions: Damage Risk Layer
### Drift-proof, hallucination-resistant prompts aligned to the project's Architecture, TRD, and PRD documents

> **Context.** Consumes Stage 2's `SimulationResult` (hazard) and the building/road geometry from Stage 2's GLB ingestion (exposure), applies a vulnerability curve, and produces a ranked, confidence-scored risk list per structure/road segment. This document assumes Stage 2's GLB-based pivot — buildings are `Building_01/02/03`, extracted footprints already exist as `BuildingFootprint` objects, terrain is DEM-interpolated (not surveyed).
>
> **Alignment guarantee.** Formula and field definitions here are transcribed from the Architecture document §4 and the PRD's FR-13/FR-14/FR-15. If this document disagrees with those, they win.

---

# §A. Operating Contract

```md
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
```

---

# §B. Canonical Specifications

## B.1 Environment variables (`backend/stage3/.env.example`)

```
DATABASE_URL=postgresql://localhost:5432/floodsystem
REDIS_URL=redis://localhost:6379/0
HAZARD_THRESHOLD_DEPTH_M=0.3        # config value, human-reviewable, not verified-optimal
VULNERABILITY_CURVE_SOURCE=         # citation string, filled in T3.3
```

## B.2 Data contracts (`backend/stage3/shared/contracts.py`)

> Import `SimulationResult`, `NodeState` from Stage 2 verbatim. Import `BuildingFootprint` from Stage 2's `shared/contracts.py` verbatim. Define new contracts below.

```python
from pydantic import BaseModel
from typing import List, Optional


class RoadSegment(BaseModel):
    segment_id: str
    polyline: List[List[float]]     # [[x, y], ...] real-world meters, site-local frame
    width_m: Optional[float]


class DamageRankEntry(BaseModel):
    structure_id: str               # "Building_01" or a RoadSegment.segment_id
    structure_type: str              # "building" | "road_segment"
    site_id: str
    hazard_score: float
    exposure_score: float
    vulnerability_score: float
    vulnerability_source: str        # citation, never blank
    vulnerability_is_local_calibration: bool = False   # always False unless real local data exists
    risk_score: float
    confidence: float                # from ensemble_agreement_fraction
    rank: int
    peak_hour: int
    peak_depth_m: float
    peak_velocity_mps: float
    peak_rate_of_rise: float
```

## B.3 File structure

```
backend/stage3/
├── CLAUDE.md
├── .env.example
├── shared/contracts.py
├── hazard/
│   └── extract_hazard.py           # T3.1
├── exposure/
│   ├── road_segmentation.py        # T3.2
│   └── exposure_scoring.py         # T3.3
├── vulnerability/
│   └── fragility_curve.py          # T3.4
├── ranking/
│   └── risk_ranking.py             # T3.5
├── routes.py                        # T3.6
├── db.py
├── config.py
└── tests/
```

---

# §C. Tasks

## T3.0 · Scaffolding — [P0] · depends: none

> **PROMPT**
> Files you may touch: everything under `backend/stage3/` (new).
> Requirements: structure per §B.3; `config.py` loading §B.1; `CLAUDE.md` = §A verbatim; `contracts.py` = §B.2, importing Stage 2's `SimulationResult`/`NodeState`/`BuildingFootprint` (confirm real import path from Stage 2's actual code, don't assume); `requirements.txt` pinned (fastapi, pydantic, sqlalchemy, shapely for segment/polygon geometry, numpy, pytest — verify versions).
> **VERIFY:** clean install; import check on all contracts (native + imported); paste output.

## T3.1 · Hazard extraction — `backend/stage3/hazard/extract_hazard.py` · [P0] · depends: T3.0

> **PROMPT**
> Goal: pull the three hazard signals from Stage 2's output, per node/timestep.
> Files you may touch: `backend/stage3/hazard/extract_hazard.py`, `backend/stage3/tests/test_hazard.py`.
> Requirements: implement `extract_peak_hazard(sim_result: SimulationResult, node_ids: List[str]) -> dict` returning, for each requested node id, the peak depth, peak velocity, peak rate-of-rise across the 72-hour window, the hour each peak occurred, and the `ensemble_agreement_fraction` at that peak. Do not average away the peak — a building's risk is driven by its worst moment, not its mean condition across the window.
> **VERIFY:** run against a real (or fixture) `SimulationResult`; paste peak values for at least 3 nodes, confirming the peak hour differs sensibly across nodes (not all identical, unless the underlying data genuinely supports that).

## T3.2 · Road segmentation — `backend/stage3/exposure/road_segmentation.py` · [P1] · depends: T3.0

> **PROMPT**
> Goal: since Stage 2 only loaded `Road_Network` as raw mesh (roads aren't physics obstacles, so Stage 2 never segmented them), do that segmentation here for exposure purposes.
> Files you may touch: `backend/stage3/exposure/road_segmentation.py`, `backend/stage3/tests/test_exposure.py`.
> Requirements: **first confirm how Stage 2 actually exposes the raw `Road_Network` mesh data — check its real ingestion code (T2.1) rather than assuming a data access pattern.** Implement `segment_road_network(road_mesh_data) -> List[RoadSegment]`, deriving reasonable discrete segments from the mesh (e.g., by connected-component analysis or a fixed-length chunking along the road's centerline — confirm which approach fits the actual mesh structure once you've inspected it, don't assume in advance). If the road mesh doesn't cleanly decompose into segments (e.g., it's a single unstructured blob), flag this and ask rather than producing an arbitrary segmentation.
> **VERIFY:** paste the resulting `RoadSegment` list (count and approximate lengths), and confirm the segments' combined extent roughly matches the original `Road_Network` mesh's bounding box.

## T3.3 · Exposure scoring — `backend/stage3/exposure/exposure_scoring.py` · [P0] · depends: T3.2

> **PROMPT**
> Goal: quantify what's exposed at each structure/segment.
> Files you may touch: `backend/stage3/exposure/exposure_scoring.py`, `backend/stage3/tests/test_exposure.py`.
> Requirements: implement `compute_exposure_score(footprint_or_segment, population_density: Optional[float] = None) -> float`. Base exposure on presence/area (a building exists = nonzero exposure) and, if a real, confirmed population-density source is available, weight by it. **If no real population data source has been confirmed and connected, do not estimate a population figure — implement the function to work correctly with `population_density=None`,** per Operating Contract rule 1.
> **VERIFY:** paste exposure scores for all 3 buildings and the road segments from T3.2, with and without a population-density input, confirming the `None` path doesn't fabricate a number.

## T3.4 · Vulnerability / fragility curve — `backend/stage3/vulnerability/fragility_curve.py` · [P0] · depends: T3.0

> **PROMPT**
> Goal: implement a real, cited, published depth-damage or fragility function.
> Files you may touch: `backend/stage3/vulnerability/fragility_curve.py`, `backend/stage3/tests/test_vulnerability.py`.
> Requirements: **search for and confirm a real, published depth-damage or fragility curve appropriate for residential/institutional structures in this session before implementing anything — do not write an unsourced formula.** Record the citation as a string constant, exposed via the `VULNERABILITY_CURVE_SOURCE` env var and the `DamageRankEntry.vulnerability_source` field. Implement `compute_vulnerability(peak_depth_m: float, peak_velocity_mps: float) -> float`, incorporating velocity's effect on damage where the source curve supports it, not depth alone. Set `vulnerability_is_local_calibration = False` always, unless a human explicitly supplies real local calibration data (none exists currently — do not mark this `True` speculatively).
> **VERIFY:** paste the citation used, and the function's output across a range of test depth/velocity inputs, confirming monotonically increasing damage with increasing hazard (a basic sanity property any real fragility curve should have).

## T3.5 · Risk ranking — `backend/stage3/ranking/risk_ranking.py` · [P0] · depends: T3.1, T3.3, T3.4

> **PROMPT**
> Goal: combine hazard × exposure × vulnerability into the final ranked list.
> Files you may touch: `backend/stage3/ranking/risk_ranking.py`, `backend/stage3/tests/test_ranking.py`.
> Requirements: implement `rank_structures(sim_result: SimulationResult, footprints: List[BuildingFootprint], road_segments: List[RoadSegment]) -> List[DamageRankEntry]`, computing risk per structure/segment, sorting descending by `risk_score`, assigning `rank` sequentially, and setting `confidence` from the corresponding `ensemble_agreement_fraction`. Must be deterministic — re-running against identical input produces an identical ranking, including tie-breaking order.
> **VERIFY:** run twice against the same input; paste both outputs and confirm they're byte-identical; paste the final ranked list for the demo site (3 buildings + road segments).

## T3.6 · API route — `backend/stage3/routes.py` · [P0] · depends: T3.5

> **PROMPT**
> Goal: expose per the TRD.
> Files you may touch: `backend/stage3/routes.py`, `backend/stage3/tests/test_routes.py`.
> Requirements: `GET /api/damage-ranking/{site_id}` → returns the ranked `List[DamageRankEntry]`, triggering T3.5's computation if no cached result exists for the current `SimulationResult`, cached in Redis thereafter.
> **VERIFY:** curl the endpoint; paste real JSON response.

## T3.7 · Tests — [P0] · depends: all above

> **VERIFY:** `pytest backend/stage3/tests/ -v`; paste full real passing output.

---

# §D. Build order

| Window | Tasks |
|---|---|
| 1 | T3.0, T3.1 |
| 2 | T3.2, T3.3 |
| 3 | T3.4 |
| 4 | T3.5, T3.6 |
| 5 | T3.7 |

---

# §E. Final acceptance

1. Ranking uses depth, velocity, AND rate-of-rise — confirmed by inspecting `hazard_score`'s inputs, never depth alone. ✅
2. Every `DamageRankEntry` carries a real, cited `vulnerability_source`, never an unsourced number. ✅
3. `vulnerability_is_local_calibration` is `False` throughout, honestly. ✅
4. Population data is either real and confirmed, or genuinely absent — never fabricated. ✅
5. Ranking is deterministic across repeat runs on identical input. ✅
6. Road segments derived from Stage 2's raw `Road_Network` mesh, not invented independently. ✅
7. `pytest`/`mypy` clean; only `backend/stage3/` touched. ✅
