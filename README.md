# Hyperlocal Flood Prediction & Early Warning System

A 72-hour-advance flood forecast for a specific location, plus a physically
simulated, sub-meter-resolution prediction of how that location floods —
rendered as an explorable 3D model and packaged into a government-compatible
alert. See the design docs in [`Flood_system_finial/`](Flood_system_finial/)
for the full picture:

- [`flood_system_PRD.md`](Flood_system_finial/flood_system_PRD.md) — product requirements
- [`flood_system_architecture.md`](Flood_system_finial/flood_system_architecture.md) — the four-stage system architecture
- [`flood_system_TRD.md`](Flood_system_finial/flood_system_TRD.md) — technology stack and engineering decisions
- [`flood_system_user_flow.md`](Flood_system_finial/flood_system_user_flow.md) — end-to-end user flow
- [`stage1a_build_instructions.md`](Flood_system_finial/stage1a_build_instructions.md) / [`stage1b_build_instructions.md`](Flood_system_finial/stage1b_build_instructions.md) — the two build tracks below

## Repo layout

```
backend/
├── stage1a/    # regional forecast acquisition — this branch (feat/stage1a)
├── stage1b/    # DEM + downscaling + sensor ingest — feat/stage1b
└── shared/     # cross-stage contracts, if used
Flood_system_finial/
└── *.md        # the design docs listed above
```

The project is split into two independently-built backend modules that share
one data contract:

- **Stage 1A** (`backend/stage1a/`) — runs on this branch. Regional
  rainfall ensemble acquisition (WeatherNext 2 Cyclones Mini, with GEFS and
  a legacy GenCast path as fallbacks) and CWC/National Water Data Portal
  river-stage telemetry, exposed over FastAPI.
- **Stage 1B** (`backend/stage1b/`) — built separately, `feat/stage1b`
  branch. DEM acquisition/processing, terrain-based downscaling, TN WRD
  data, and the ESP32 sensor ingestion path.

Both consume the same `RegionalEnsembleForecast` / `RiverStageForecast`
Pydantic contracts (§B.2 of the build instructions) — kept as
byte-identical per-module copies (`backend/stage1a/shared/contracts.py`)
rather than a single shared import, so the two branches can be built and
tested independently without a merge conflict on a common file.

## Stage 1A — what's built

- `GET /api/forecast/regional` — latest regional rainfall ensemble.
  Source chain: GEFS (not yet implemented) → **WeatherNext 2 Cyclones
  Mini** (real, working — a manually-run Colab export) → legacy GenCast
  live-inference/synthetic-fallback pair (kept as the final resort; GenCast
  live inference needs a TPU/JAX stack not available in dev).
- `GET /api/forecast/river-stage?lat={}&lon={}` — nearest CWC telemetry
  station's recent water-level readings, with a real, computed
  `station_proximity_verified` flag (not assumed true).
- PostgreSQL+PostGIS storage, Redis caching, Celery task for out-of-band
  generation, full test suite (`pytest`, mocked external calls) and `mypy`
  clean.

### Setup

```bash
cd backend/stage1a
python3.13 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
docker compose up -d              # PostgreSQL+PostGIS and Redis
cp .env.example .env              # fill in TARGET_SITE_LAT/LON etc.
```

Get a real forecast file (WeatherNext 2 Mini requires a one-time manual
Colab run — see `data/wn2_mini/README.md`), then:

```bash
cd backend                        # so `stage1a` resolves as a package
./stage1a/.venv/bin/python -m uvicorn stage1a.routes:app --reload
./stage1a/.venv/bin/python -m pytest stage1a/tests/ -v
./stage1a/.venv/bin/mypy --config-file stage1a/pyproject.toml stage1a
```

### Merging with `feat/stage1b`

Both branches only touch their own `backend/stage1<a|b>/` directory, so a
merge should be conflict-free except possibly `.gitignore` (diff and
combine both sets of rules rather than taking one side). Neither branch's
`.env` files or generated data (`data/`, `.venv/`, DB volumes) are
committed — each collaborator brings up their own local Postgres/Redis and
copies their own forecast exports into place; nothing here depends on the
other stage's runtime environment to build or test independently.
