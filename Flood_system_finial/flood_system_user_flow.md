# Web Application — User Flow & Experience Design

## Hyperlocal Flood Prediction & Early Warning System

---

## 1. Design Philosophy

Two audiences use this platform, and they need to feel like different products, not one dashboard with a language toggle:

- **The operations view** (disaster management officers, emergency responders, and — in the hackathon context — the judging panel) needs density, precision, and control: forecasts, ensembles, ranked lists, live sensor telemetry, all visible and manipulable at once.
- **The citizen view** needs the opposite: one clear status, one clear instruction, no jargon, readable in bright sunlight on a cracked phone screen with patchy signal.

The design system reflects this split deliberately rather than compromising both into a middle ground that serves neither.

**Ops view — dark, control-room aesthetic.** A dark background makes the 3D water render and severity colors read with far more visual punch than they would on white, and it's genuinely easier on the eyes through an extended monitoring session — this is a legitimate operational choice, not just a stylistic one.

**Citizen view — light, high-contrast, generous touch targets.** Optimized for a five-second glance outdoors, not a considered session at a desk.

**Shared severity language across both.** Four states, one color vocabulary, used consistently everywhere in the app so a color never means something different depending on which screen you're looking at:

| State | Color | Meaning |
|---|---|---|
| Monitoring | Blue | No elevated risk detected |
| Watch | Amber | Elevated probability, still distant in time |
| Warning | Orange | Significant probability, action window open |
| Critical | Red | High-confidence, near-term hazard |

---

## 2. Information Architecture

```
/                          Landing
/dashboard                 Operations Dashboard (primary view)
/dashboard/site/:id        Site Detail (building/segment drill-down)
/dashboard/alert           Alert Composer & Dispatch
/dashboard/sensor          Live Sensor Panel
/citizen                   Citizen Alert View
/citizen/guidance          "What to do" action steps
/about                     Methodology & Honesty Statement page
```

---

## 3. Page-by-Page Design

### 3.1 Landing (`/`)

**Purpose:** orient any visitor in under five seconds and route them to the right experience.

**Layout:**
- Full-bleed background: a subtle, slowly panning satellite/terrain view of the demo region.
- Center: platform name/mark, one-line description ("72-hour flood forecasting, down to the street"), and a live status badge pulling the current severity state (e.g., a calm blue "Monitoring — Vellore District" badge under normal conditions).
- Two clear entry points, visually distinct: a solid, prominent **"Open Operations Dashboard"** button, and a lighter **"Check my area"** link for citizen access.
- A small, persistent footer link to `/about` — visible but not competing for attention.

**Why this layout:** a judge or officer should never have to hunt for the dashboard; a citizen arriving from an SMS link should never have to see the ops dashboard first.

---

### 3.2 Operations Dashboard (`/dashboard`)

This is the centerpiece screen — the one doing the most work in a live demonstration. Laid out as a four-zone grid:

```
┌─────────────────────────────────────────────────────────────┐
│  TOP BAR: Site name · Severity badge · Time-to-event · 🌐    │
├───────────────┬─────────────────────────────┬─────────────────┤
│               │                               │                 │
│  FORECAST     │        3D SCENE               │   RISK RANKING  │
│  PANEL        │   (terrain → site zoom)        │   (scrollable   │
│  (left)       │   + timeline scrubber          │    list)        │
│               │                               │                 │
├───────────────┴─────────────────────────────┴─────────────────┤
│  SENSOR STRIP: connection status · last reading · assimilate   │
└─────────────────────────────────────────────────────────────┘
```

**Top bar.** Site name, the four-state severity badge (Section 1), a countdown-style "time to peak scenario" readout, and a language selector (affects only citizen-facing text previews, not the operational UI itself, which stays in the operator's working language).

**Forecast panel (left).** Two stacked cards:
- *Regional ensemble card*: a fan chart — GenCast's 50+ member rainfall trajectories over the 72-hour window, rendered as translucent overlapping lines that visually thicken where members agree and fan out where they diverge. A small numeric readout beneath: "34 of 50 scenarios exceed threshold by hour 60."
- *River/reservoir cross-check card*: CWC's independent forecast, shown as a simple two-state indicator — a green "Independent government model agrees" or an amber "Divergence detected" — deliberately terse, because its entire UX job is to answer one question at a glance: does a second, independent source back this up.

**3D scene (center).** The main visual. Opens wide, showing the 2km terrain with the regional rainfall animating as a translucent overlay across it. A single click or the timeline's "zoom" marker smoothly flies the camera down into the scanned 50m×50m site — this transition is deliberately slow and cinematic (roughly 2 seconds), not an instant cut, because the continuity of that motion is what visually proves "this is one system," per the architecture's geo-referencing design. Below the viewport: a horizontal 72-hour timeline scrubber with a play/pause control; dragging it animates the water surface rising and flowing through the scanned streets, with the translucent uncertainty envelope visible around the solid "most likely" water surface. A small toggle above the scene switches between "most likely," "envelope," and "worst case" render modes.

**Risk ranking (right).** A vertically scrolling list, each row showing: structure name/ID, a small colored risk chip (matching the four-state palette), a confidence percentage, and a one-line hazard summary ("1.2m depth, fast flow, rising"). Rows are sorted by risk descending by default. Clicking a row navigates to Site Detail (3.3) and simultaneously highlights that structure in the 3D scene — the two views are always cross-linked, never independent.

**Sensor strip (bottom).** A slim, persistent bar: a connection-status dot (green/gray), the sensor's last reading, and — specifically for the demonstration — a clearly labeled **"Simulate live reading"** affordance sitting right next to the real hardware input path, so the same UI acts identically whether the reading comes from the physical device or the rehearsed fallback (Section 7 of the TRD). When a reading arrives, this strip briefly highlights, and the corresponding change ripples visibly into the 3D scene's uncertainty envelope narrowing — the single most important animated moment in the whole app, and it's deliberately given a distinct visual treatment (a brief pulse/glow) so it reads unambiguously as "something just happened," not lost among the dashboard's other constant motion.

---

### 3.3 Site Detail (`/dashboard/site/:id`)

Opened from a ranking-list click or a direct click on a building in the 3D scene. Slides in as a right-hand panel over the dashboard (not a full navigation away — the 3D scene and ranking list stay visible behind it) so the operator never loses context.

**Contents:**
- Structure name, ID, and a small thumbnail crop of its 3D render.
- A time-series chart: depth, velocity, and rate-of-rise plotted together across the 72-hour window, with the current timeline position marked.
- The full hazard × exposure × vulnerability breakdown, shown as three labeled sub-scores feeding the final risk number — not just the final number, so an officer can see *why* a structure ranks where it does.
- A confidence statement in plain language: "41 of 50 forecast scenarios place this structure above the critical threshold."
- A "Include in alert" toggle, feeding directly into the Alert Composer.

---

### 3.4 Alert Composer & Dispatch (`/dashboard/alert`)

**Purpose:** the moment the ranked model output becomes a real, sendable message — and the page most directly answering the brief's "government integration" and "multilingual alerts" requirements.

**Layout:** two-column split.
- **Left — raw CAP-XML.** Rendered in a monospace, syntax-highlighted block, showing the actual generated schema fields (severity, certainty, urgency, area polygon, effective/expiry) populated with real values pulled live from the current forecast state — shown raw and unstyled deliberately, because seeing the actual schema output is what makes "SACHET-compatible" a checkable claim rather than an assertion.
- **Right — human preview.** A tabbed language switcher (matching the top bar's language list) rendering the same alert as a citizen would actually see it — this is a live preview of the Citizen View (3.5), not a separate mockup, so what's demonstrated here is provably what gets sent.

**Bottom:** a single, clearly-labeled **"Dispatch"** action. In the hackathon build this triggers a simulated send with a success confirmation, explicitly labeled as a demonstration action rather than a real integration — an honest UI choice consistent with the project's stated design principle of never overclaiming.

---

### 3.5 Citizen Alert View (`/citizen`)

A completely different visual register from the dashboard — light background, large type, minimal chrome.

**Layout, top to bottom, single column, mobile-first:**
1. A full-width status band in one of the four severity colors, with a short, plain-language headline ("Rising water expected near you within 48 hours").
2. A simplified map — no ensemble fans, no technical overlays — just the affected area shaded, with a marker for "your location" if geolocation is available.
3. Three to five short, numbered action steps in large type ("Move valuables above 1 meter," "Avoid [named street] after 6pm today").
4. A prominent language selector at the top of the screen (not buried in a settings menu), since language accessibility is a core requirement, not an afterthought.
5. A "Share with family" button, generating a shareable link/message.

**Deliberately absent:** confidence percentages, ensemble counts, hazard breakdowns — anything that would require interpretation. The citizen view's entire design goal is zero required interpretation.

### 3.6 Guidance sub-page (`/citizen/guidance`)

A calmer, secondary page reachable from the main citizen alert — general flood-safety guidance not tied to the live event, for someone who wants to prepare ahead of an active warning. Same visual language as 3.5, lower urgency tone.

---

### 3.7 About / Methodology (`/about`)

**Purpose:** this page is a deliberate product decision, not documentation filler. It's where the system's honesty principles (Architecture §9) become something a visitor can actually read, rather than something only stated verbally during a demo.

**Contents, in plain language:**
- What the system does and does not claim (e.g., "we don't predict rainfall below 2km — here's why, and here's what we do instead").
- A short, non-technical explanation of the forecast chain (weather ensemble → river cross-check → physical simulation → damage ranking).
- The data sources used, named plainly, with links where public.
- A note on the live sensor's actual role — proving a mechanism, not powering the forecast.

This page is a quiet but real differentiator: most flood-tech demos hide their limitations; this one publishes them.

---

## 4. User Journeys

### 4.1 Operations officer / demonstration journey (primary)

1. Lands on `/dashboard` — severity badge and forecast panel are the first things seen, establishing "this is live and current" immediately.
2. Reads the regional ensemble fan chart and the CWC cross-check indicator — a genuine decision point: does the officer trust this forecast? The UI is built to make that judgment easy, not to make it for them.
3. Drags the 72-hour timeline scrubber — watches the 3D scene's camera fly from the wide regional view into the scanned site as the water visibly rises.
4. Notices the ranking list reordering as the timeline advances past different structures' risk thresholds.
5. Clicks the top-ranked structure — Site Detail slides in, showing the hazard breakdown and confidence statement.
6. Returns to the dashboard; the sensor strip receives a live reading (hardware or rehearsed fallback) — watches the uncertainty envelope visibly narrow in the 3D scene, the defining "wow" moment of the demo.
7. Navigates to Alert Composer — reviews the raw CAP-XML, switches through language previews, dispatches (simulated).
8. Optionally visits `/about` to show the stated limitations openly — a deliberate trust-building beat late in the demo, not hidden.

### 4.2 Citizen journey

1. Receives an alert link (conceptually via SMS/push — not built in this scope) and opens `/citizen`.
2. Sees the severity band and headline instantly — no login, no navigation required.
3. Reads the numbered action steps.
4. Switches language if the default isn't their preferred one.
5. Optionally taps through to `/citizen/guidance` for general preparedness information, or shares the alert with family.

---

## 5. Interaction & State Details

- **Loading states:** the 3D scene shows a low-poly wireframe placeholder of the terrain while the full mesh streams in, rather than a blank screen or a generic spinner — keeps the geographic context visible even mid-load.
- **Empty/no-data state:** if a forecast hasn't run yet (e.g., first load of the day), the dashboard shows a calm "Awaiting next forecast cycle" state rather than an error, with a visible last-updated timestamp.
- **Error state (data source unavailable):** each panel (regional forecast, river cross-check, sensor) fails independently and visibly — a small inline warning within just that card, never a full-page failure, consistent with the system's fallback-at-every-stage design principle.
- **Connection loss (WebSocket):** the sensor strip shows a "Reconnecting…" state and silently resumes on reconnect, per TRD §8 (TNFR-5), without requiring a manual refresh.

---

## 6. Responsive Behavior

- **Operations Dashboard:** designed desktop-first (this is a control-room tool, realistically used on a laptop or larger display during a demo); on a narrower viewport, the three-column grid stacks vertically in the order Forecast → 3D Scene → Ranking, with the sensor strip pinned to the bottom throughout.
- **Citizen View:** designed mobile-first from the outset — the primary and only realistic use case for a resident checking a flood alert.

---

## 7. Accessibility Considerations

- Severity is never communicated by color alone — every colored badge or chip carries a text label ("Warning," "Critical") alongside it.
- The citizen view maintains high color contrast throughout, tested specifically for outdoor/bright-light legibility, not just standard screen contrast ratios.
- All interactive elements (timeline scrubber, ranking rows, language selector) are keyboard-navigable, not mouse/touch-only.
- Language selection is a first-class, always-visible control on both the dashboard and citizen view — never nested in a settings menu.
