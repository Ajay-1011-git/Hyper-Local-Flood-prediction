# STAGE 4 — Complete Build Instructions: Visualization & Alerting
### Drift-proof, hallucination-resistant prompts aligned to the project's Architecture, TRD, PRD, and User Flow documents

> **Context.** This is the largest remaining stage — it spans backend alert generation (CAP-XML/SACHET) and the full React + Three.js frontend (Operations Dashboard, 3D scene, Citizen View, Alert Composer). It renders Stage 2's GLB-derived terrain and buildings (not a photogrammetry scan), Stage 2's simulation output, Stage 3's damage ranking, and Stage 1B's live sensor data.
>
> **Alignment guarantee.** Tech stack choices are transcribed from the TRD §3.1/§3.2. Page layouts and interaction details are transcribed from the User Flow document. CAP/SACHET field requirements are transcribed from the Architecture §5.5 and PRD FR-20. Where this document is silent, those win.

---

# §A. Operating Contract

```md
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
- Only 3 buildings exist in the demo site (`Building_01/02/03`) plus
  `Road_Network` segments from Stage 3. Do not build UI assuming an
  arbitrary/larger building count.
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
```

---

# §B. Canonical Specifications

## B.1 Environment variables

```
# backend/stage4/.env.example
DATABASE_URL=postgresql://localhost:5432/floodsystem
REDIS_URL=redis://localhost:6379/0
SACHET_SCHEMA_VERSION=              # confirm and fill in during T4A.1
SUPPORTED_LANGUAGES=en,ta           # English + Tamil at minimum, per PRD NFR-6

# frontend/.env.example
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
```

## B.2 Data contracts

**Consumed, unchanged, imported verbatim:** `SimulationResult`, `NodeState`, `TerrainGrid`, `BuildingFootprint`, `AnchorPoint` (Stage 2); `DamageRankEntry`, `RoadSegment` (Stage 3); `SensorReading` (Stage 1B).

**New** (`backend/stage4/shared/contracts.py`):

```python
from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict


class Alert(BaseModel):
    id: str
    site_id: str
    generated_at: datetime
    severity: str          # confirm real CAP severity enum values in T4A.1
    certainty: float       # from ensemble agreement — never a placeholder
    urgency: str            # confirm real CAP urgency enum values in T4A.1
    area_polygon: List[List[float]]   # [[lat, lon], ...]
    effective_time: datetime
    expiry_time: datetime
    cap_xml: str
    text_by_language: Dict[str, str]  # {"en": "...", "ta": "..."}
```

**WebSocket event contract** (`/ws/site/{site_id}`), consumed by the frontend:

```
{ "type": "simulation_update", "payload": { node_states: [...], envelope: {...} } }
{ "type": "sensor_assimilated", "payload": { sensor_id, updated_region } }
{ "type": "ranking_update", "payload": [DamageRankEntry, ...] }
```

## B.3 File structure

```
backend/stage4/
├── CLAUDE.md
├── .env.example
├── shared/contracts.py
├── alerts/
│   ├── cap_generator.py           # T4A.1
│   └── multilingual.py             # T4A.2
├── routes.py                        # T4A.3
├── db.py
├── config.py
└── tests/

frontend/
├── .env.example
├── src/
│   ├── main.tsx
│   ├── api/
│   │   ├── client.ts                # T4B.0 — TanStack Query setup
│   │   └── websocket.ts             # T4B.1
│   ├── store/
│   │   └── sceneStore.ts            # T4B.2 — Zustand
│   ├── scene/
│   │   ├── Terrain.tsx              # T4B.3
│   │   ├── SiteMesh.tsx             # T4B.4 — Building_01/02/03, Road_Network
│   │   ├── WaterSurface.tsx         # T4B.5
│   │   ├── UncertaintyEnvelope.tsx  # T4B.6
│   │   ├── DamageOverlay.tsx        # T4B.7
│   │   └── CameraController.tsx     # T4B.8
│   ├── pages/
│   │   ├── Landing.tsx              # T4C.0
│   │   ├── Dashboard.tsx            # T4C.1
│   │   ├── SiteDetail.tsx           # T4C.2
│   │   ├── AlertComposer.tsx        # T4C.3
│   │   ├── CitizenView.tsx          # T4C.4
│   │   ├── CitizenGuidance.tsx      # T4C.5
│   │   └── About.tsx                # T4C.6
│   └── components/
│       ├── SeverityBadge.tsx
│       ├── TimelineScrubber.tsx
│       ├── SensorStrip.tsx
│       └── RiskRankingList.tsx
└── tests/
```

---

# §C. Tasks

## SECTION A — Backend: Alert Generation

### T4A.0 · Backend scaffolding — [P0] · depends: none

> Files you may touch: everything under `backend/stage4/` (new).
> Requirements: structure per §B.3; `config.py`; `CLAUDE.md` = §A; `contracts.py` = §B.2 plus imports from Stage 2/3/1B; `requirements.txt` pinned (fastapi, pydantic, an XML library — confirm the right one, e.g. `lxml`, in T4A.1 — pytest).
> **VERIFY:** clean install; import check; paste output.

### T4A.1 · CAP-XML generator — `backend/stage4/alerts/cap_generator.py` · [P0] · depends: T4A.0

> **PROMPT**
> Goal: real, schema-valid CAP-XML matching what SACHET expects.
> Requirements: **search for and confirm the real, current CAP schema (namespace URI, exact element names for severity/certainty/urgency/area/effective/expiry, and how SACHET specifically structures these) in this session before writing any XML generation code — do not write against an assumed schema.** Implement `generate_cap_xml(damage_ranking: List[DamageRankEntry], sim_result: SimulationResult, site_polygon: List[List[float]]) -> str`, deriving `severity` and `urgency` from the ranking's top risk scores and time-to-peak, and `certainty` directly from `ensemble_agreement_fraction` — never a hardcoded value. Fill `SACHET_SCHEMA_VERSION` in `.env.example` once confirmed.
> **VERIFY:** paste the source(s) consulted for the schema; generate real XML from a real/fixture `DamageRankEntry` list; validate it against the real schema (an XML schema validator or manual structural check); paste the validation result and the generated XML itself.

### T4A.2 · Multilingual alert text — `backend/stage4/alerts/multilingual.py` · [P1] · depends: T4A.1

> **PROMPT**
> Goal: plain-language alert text in English and Tamil (minimum, per `SUPPORTED_LANGUAGES`), matching the tone specified in User Flow §3.5 (Citizen View) — short, numbered, zero required interpretation.
> Requirements: implement `generate_alert_text(severity: str, top_risk_entries: List[DamageRankEntry], language: str) -> str`, templated per severity level. If generating Tamil text via a translation step you're not fully confident in, flag it explicitly in the output/comments for human review — do not present unreviewed machine translation as final.
> **VERIFY:** paste generated text in both languages for at least two severity levels; note explicitly whether Tamil text has been human-reviewed or flagged as pending review.

### T4A.3 · API routes — `backend/stage4/routes.py` · [P0] · depends: T4A.1, T4A.2

> **PROMPT**
> Requirements: `GET /api/alert/{site_id}` → latest `Alert` with raw `cap_xml` and `text_by_language`, per TRD §5.1. Also implement the WebSocket relay endpoint `/ws/site/{site_id}` if not already implemented by an earlier stage — confirm with Stage 2/3's actual code whether this already exists before building a duplicate.
> **VERIFY:** curl the endpoint; paste real response including full raw CAP-XML.

### T4A.4 · Tests — [P0] · depends: all Section A

> **VERIFY:** `pytest backend/stage4/tests/ -v`; paste real passing output.

---

## SECTION B — Frontend: 3D Scene

### T4B.0 · Project setup + API client — [P0] · depends: none

> Requirements: `npm create vite@latest` (React + TypeScript template — confirm current Vite scaffolding command before running, syntax changes across Vite versions); install react-three-fiber, drei, zustand, @tanstack/react-query, tailwindcss (confirm current install/config steps for each in this session). Implement `api/client.ts` wrapping fetch calls to all backend endpoints defined across Stage 1A/1B/2/3/4A, typed against the real contracts (mirror the Pydantic models as TypeScript interfaces — keep field names identical).
> **VERIFY:** `npm run dev` starts cleanly; a test API call to one real backend endpoint succeeds; paste console output.

### T4B.1 · WebSocket client — `frontend/src/api/websocket.ts` · [P0] · depends: T4B.0

> Requirements: connect to `/ws/site/{site_id}`, handle the three event types in §B.2, auto-reconnect on drop without requiring a page reload (TRD TNFR-5).
> **VERIFY:** simulate a disconnect (stop the backend briefly) and confirm auto-reconnect; paste console log evidence.

### T4B.2 · Scene state store — `frontend/src/store/sceneStore.ts` · [P0] · depends: T4B.1

> Requirements: Zustand store holding current timeline hour, per-node water state, uncertainty envelope, damage ranking, sensor connection status — updated by WebSocket events and by the timeline scrubber's manual position.
> **VERIFY:** unit test confirming a `simulation_update` event correctly updates the store's node state.

### T4B.3 · Terrain rendering — `frontend/src/scene/Terrain.tsx` · [P0] · depends: T4B.2

> **PROMPT**
> Goal: render Stage 1B's wider DEM and Stage 2's site-local `TerrainGrid` as one continuous surface.
> Requirements: fetch Stage 1B's regional DEM heightmap and Stage 2's `TerrainGrid`; render the regional DEM as a decimated (lower-poly) surrounding mesh (per TRD §6, point 3) and the site's `TerrainGrid` at full resolution within it, positioned via the `AnchorPoint`. **Since `interpolated_from_regional_dem` is `True`, do not render this as if it were survey-grade detail** — this is fine visually, but the About page (T4C.6) must state the limitation; this task's job is just correct, seamless rendering, not overclaiming its precision.
> **VERIFY:** screenshot showing the wide terrain and the site-local patch with no visible seam/cliff at their boundary.

### T4B.4 · Site mesh (buildings + roads) — `frontend/src/scene/SiteMesh.tsx` · [P0] · depends: T4B.3

> Requirements: load the same GLB Stage 2 ingested (`Building_01/02/03`, `Road_Network`), positioned on the terrain from T4B.3 via the anchor point.
> **VERIFY:** screenshot confirming buildings sit correctly on the terrain surface (no floating/sinking).

### T4B.5 · Water surface — `frontend/src/scene/WaterSurface.tsx` · [P0] · depends: T4B.4

> **PROMPT**
> Goal: real-time water rendering driven entirely by backend-computed values.
> Requirements: **confirm the current API of your chosen Three.js water-shader approach in this session before writing shader-integration code.** Vertex heights driven directly from the scene store's current `NodeState.depth_mean_m` per timestep — this component computes zero physics, per the Operating Contract.
> **VERIFY:** screenshot of animated water at multiple timeline positions, showing visibly rising/falling levels tied to store state changes.

### T4B.6 · Uncertainty envelope — `frontend/src/scene/UncertaintyEnvelope.tsx` · [P0] · depends: T4B.5

> Requirements: translucent band using `depth_min_m`/`depth_max_m`, visibly narrowing on a `sensor_assimilated` WebSocket event — the defining demo moment (User Flow §3.2), needs a distinct visual treatment (brief pulse/glow) per the User Flow spec.
> **VERIFY:** trigger a test assimilation event; screenshot before/after showing the visible narrowing.

### T4B.7 · Damage overlay — `frontend/src/scene/DamageOverlay.tsx` · [P0] · depends: T4B.4

> Requirements: recolor `Building_01/02/03` and road segments per Stage 3's `DamageRankEntry.risk_score`, using the four-state severity palette (User Flow §1), as the timeline advances past each structure's peak-risk hour.
> **VERIFY:** screenshot at a timeline position where at least one structure has crossed into "Warning" or "Critical" color.

### T4B.8 · Camera controller — `frontend/src/scene/CameraController.tsx` · [P1] · depends: T4B.3, T4B.4

> Requirements: smooth (~2 second) camera transition from the wide regional view into the site-local patch, per User Flow §3.2's description — not an instant cut.
> **VERIFY:** screen recording or frame-sequence screenshots showing the transition in progress, not just start/end states.

### T4B.9 · Frontend tests — [P0] · depends: Section B above

> **VERIFY:** test suite run; paste real output.

---

## SECTION C — Frontend: Pages

### T4C.0 · Landing page — `frontend/src/pages/Landing.tsx` · [P1] · depends: T4B.0

> Requirements: per User Flow §3.1 — status badge, two entry points (Operations Dashboard / Citizen), footer link to About.
> **VERIFY:** screenshot.

### T4C.1 · Operations Dashboard — `frontend/src/pages/Dashboard.tsx` · [P0] · depends: T4B.6, T4B.7, T4B.8

> **PROMPT**
> Goal: the four-zone layout from User Flow §3.2 — top bar, forecast panel (GenCast/WN2-Mini + GEFS ensemble fan chart, CWC cross-check indicator), 3D scene (T4B components), risk ranking list, sensor strip.
> Requirements: forecast panel must correctly label which source (WeatherNext 2 Mini or GEFS) is currently powering the display, per the honesty principle established in Stage 1A's amendment — do not present it ambiguously. Risk ranking list cross-links to the 3D scene (clicking a row highlights the structure) and to Site Detail (T4C.2).
> **VERIFY:** full-page screenshot with all panels populated from real backend data; confirm cross-linking behavior with a real click-through.

### T4C.2 · Site Detail panel — `frontend/src/pages/SiteDetail.tsx` · [P1] · depends: T4C.1

> Requirements: per User Flow §3.3 — slides over the dashboard, hazard time-series chart, full hazard/exposure/vulnerability breakdown, confidence statement, "Include in alert" toggle.
> **VERIFY:** screenshot showing a real structure's full breakdown.

### T4C.3 · Alert Composer — `frontend/src/pages/AlertComposer.tsx` · [P0] · depends: T4A.3, T4C.1

> Requirements: per User Flow §3.4 — raw CAP-XML on one side, human-language language-tabbed preview on the other, simulated "Dispatch" clearly labeled as a demonstration action.
> **VERIFY:** screenshot showing real generated CAP-XML alongside its human preview.

### T4C.4 · Citizen View — `frontend/src/pages/CitizenView.tsx` · [P0] · depends: T4A.3

> Requirements: per User Flow §3.5 — completely separate light/high-contrast visual register, status band, simplified map, numbered action steps, prominent language selector, share button. No ensemble/confidence data shown.
> **VERIFY:** screenshot on a narrow (mobile-width) viewport, confirming legibility and the absence of technical jargon.

### T4C.5 · Citizen Guidance sub-page — [P2] · depends: T4C.4

> **VERIFY:** screenshot.

### T4C.6 · About / Methodology page — `frontend/src/pages/About.tsx` · [P0] · depends: none

> **PROMPT**
> Goal: per User Flow §3.7 — a real product decision, not filler. Must state, in plain language: rainfall isn't resolved below ~2km; the site terrain is DEM-interpolated, not surveyed (per Stage 2's honest `interpolated_from_regional_dem` flag); the live sensor demonstrates assimilation, not forecast improvement; the vulnerability curve is a general, cited approximation, not locally calibrated; which forecast source (WeatherNext 2 Mini vs. GEFS) is powering the current display.
> **VERIFY:** screenshot; confirm every honesty statement listed above is actually present as real, readable text on the page — not just referenced.

---

# §D. Build order

| Window | Tasks |
|---|---|
| 1 | T4A.0, T4A.1, T4B.0, T4B.1 |
| 2 | T4A.2, T4A.3, T4B.2, T4B.3 |
| 3 | T4B.4, T4B.5 |
| 4 | T4B.6, T4B.7, T4B.8 |
| 5 | T4C.0, T4C.1 |
| 6 | T4C.2, T4C.3, T4C.4 |
| 7 | T4C.5, T4C.6, T4A.4, T4B.9 |

---

# §E. Final acceptance

1. CAP-XML validates against a real, session-confirmed schema — not an assumed one. ✅
2. `certainty` in every generated alert traces to real ensemble agreement data. ✅
3. The 3D scene performs zero physics computation — every hydraulic value traces to a backend-computed `NodeState`. ✅
4. The wide DEM terrain and Stage 2's site-local terrain render as one continuous surface with no visible seam. ✅
5. The uncertainty envelope visibly narrows on a real sensor-assimilation event, not a scripted animation. ✅
6. The About page states all required honesty limitations as real, visible text. ✅
7. Citizen View and Operations Dashboard are visually and functionally distinct, per the design split. ✅
8. `pytest`/`mypy` (backend) and the frontend test suite/`tsc` all pass; only `backend/stage4/` and `frontend/` were touched. ✅
