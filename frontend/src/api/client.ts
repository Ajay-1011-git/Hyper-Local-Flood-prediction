/**
 * Typed fetch wrappers for every real backend endpoint — T4B.0.
 *
 * EVERY PATH BELOW WAS READ FROM THE REAL ROUTE DECORATORS, not assumed:
 *   Stage 1A  GET  /api/forecast/regional              (stage1a/routes.py:64)
 *   Stage 1A  GET  /api/forecast/river-stage           (stage1a/routes.py:104)
 *   Stage 1B  GET  /api/forecast/downscaled?lat=&lon=  (stage1b/routes.py:351)
 *   Stage 1B  POST /api/sensor/reading                 (stage1b/routes.py:473)
 *   Stage 2   GET  /api/simulation/site/{site_id}      (stage2/routes.py:131)
 *   Stage 2   POST /api/simulation/assimilate          (stage2/routes.py:148)
 *   Stage 3   GET  /api/damage-ranking/{site_id}       (stage3/routes.py:156)
 *   Stage 4   GET  /api/alert/{site_id}                (stage4/routes.py:152)
 *
 * ONE REAL DEPLOYMENT CAVEAT, DOCUMENTED RATHER THAN PAPERED OVER:
 * this project's five stages each run as their OWN independent FastAPI
 * process on its own port (a real, deliberate architecture decision —
 * see Stage 2's `routes.py` docstring, which explains the same thing for
 * WebSockets). So there is no single `VITE_API_BASE_URL` that serves all
 * of them. `STAGE_BASE_URLS` below maps each stage to its own base URL,
 * each independently overridable by env var. `.env.example` ships the
 * real localhost ports this project's own VERIFY runs have actually
 * used. A real deployment would put a gateway/reverse-proxy in front and
 * collapse these to one origin.
 */

import type {
  Alert,
  DamageRankEntry,
  DownscaledForecastField,
  RegionalEnsembleForecast,
  RiverStageForecast,
  SensorReading,
  SimulationResult,
  SiteMeshNodesResponse,
  SiteTerrainResponse,
} from './types'

const env = import.meta.env

export const STAGE_BASE_URLS = {
  stage1a: env.VITE_STAGE1A_BASE_URL ?? 'http://127.0.0.1:8001',
  stage1b: env.VITE_STAGE1B_BASE_URL ?? 'http://127.0.0.1:8011',
  stage2: env.VITE_STAGE2_BASE_URL ?? 'http://127.0.0.1:8765',
  stage3: env.VITE_STAGE3_BASE_URL ?? 'http://127.0.0.1:8003',
  stage4: env.VITE_STAGE4_BASE_URL ?? 'http://127.0.0.1:8004',
} as const

/** Thrown for any non-2xx response — never silently returns a partial/empty result. */
export class ApiError extends Error {
  // Declared as plain fields (not TS constructor parameter properties):
  // this project's Vite/TS template enables `erasableSyntaxOnly`, under
  // which parameter properties are a real compile error, since they emit
  // runtime code rather than being type-only.
  readonly status: number
  readonly url: string
  readonly body: string

  constructor(status: number, url: string, body: string) {
    super(`${url} failed with HTTP ${status}: ${body.slice(0, 300)}`)
    this.name = 'ApiError'
    this.status = status
    this.url = url
    this.body = body
  }
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new ApiError(response.status, url, await response.text().catch(() => ''))
  }
  return (await response.json()) as T
}

// --------------------------------------------------------------- Stage 1A

export function fetchRegionalForecast(): Promise<RegionalEnsembleForecast> {
  return getJson(`${STAGE_BASE_URLS.stage1a}/api/forecast/regional`)
}

/**
 * Stage 1A's real `RiverStageForecast` — the CWC cross-check card
 * (T4C.1) needs `station_proximity_verified`/`breach_probability`, so
 * this is typed against the real contract now (T4B.0 deliberately left
 * it as `unknown`, before any real consumer needed the actual fields).
 */
export function fetchRiverStageForecast(lat: number, lon: number): Promise<RiverStageForecast> {
  const url = new URL(`${STAGE_BASE_URLS.stage1a}/api/forecast/river-stage`)
  url.searchParams.set('lat', String(lat))
  url.searchParams.set('lon', String(lon))
  return getJson(url.toString())
}

// --------------------------------------------------------------- Stage 1B

/** Note: Stage 1B's route really takes `lat`/`lon` query params, NOT a
 *  `site_id` path segment — a real spec reconciliation documented in that
 *  module's own docstring (the TRD's form won over the build doc's). */
export function fetchDownscaledForecast(lat: number, lon: number): Promise<DownscaledForecastField> {
  const url = new URL(`${STAGE_BASE_URLS.stage1b}/api/forecast/downscaled`)
  url.searchParams.set('lat', String(lat))
  url.searchParams.set('lon', String(lon))
  return getJson(url.toString())
}

export function postSensorReading(
  body: { sensor_id: string; distance_cm: number; timestamp: string },
  token: string,
): Promise<SensorReading> {
  return getJson(`${STAGE_BASE_URLS.stage1b}/api/sensor/reading`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Sensor-Token': token },
    body: JSON.stringify(body),
  })
}

// ---------------------------------------------------------------- Stage 2

/**
 * The two real simulation scenarios Stage 2 runs (see its own
 * `precompute.py` docstring). `real` is the honest current forecast;
 * `heavy` is an explicitly-labelled hypothetical at a real IMD rainfall
 * category. Never present `heavy` as a forecast.
 */
export type SimulationScenario = 'real' | 'heavy'

export interface PrecomputeStatus {
  state: 'idle' | 'running' | 'done' | 'failed'
  message: string
  progress: number
  detail?: string | null
}

/** Real, disclosable facts about how a stored simulation was produced. */
export interface SimulationProvenance {
  scenario: SimulationScenario
  is_hypothetical: boolean
  /** Which engine actually produced the shipped numbers. The GNN emulator
   *  is used unless its rollout fails Stage 2's mass-conservation check,
   *  in which case the numerical solver's output is used instead. */
  engine: 'gnn_emulator' | 'numerical_solver'
  mass_conservation_ratio: number
  /** Hours the shipped result actually covers, vs how many the forecast
   *  offers. The solver fallback covers a shorter window than the
   *  emulator would, so these can legitimately differ. */
  hours_covered?: number
  forecast_hours_available?: number
  rainfall_scale_factor: number
  heavy_target_mm_per_24h: number | null
  source_forecast_id: string
  member_count: number
  node_count: number
  edge_count: number
  grid_resolution_m: number
  hazard_threshold_m: number
  validation_depth_mae_m: number
  validation_velocity_mae_mps: number
  training_epochs: number
}

export interface SensorLocation {
  configured: boolean
  reason?: string
  x_m?: number
  y_m?: number
  mount_height_m?: number
  nearest_node_id?: string | null
}

function stage2Url(path: string, scenario?: SimulationScenario): string {
  const url = new URL(`${STAGE_BASE_URLS.stage2}${path}`)
  if (scenario) url.searchParams.set('scenario', scenario)
  return url.toString()
}

export function fetchSimulationResult(
  siteId: string,
  scenario: SimulationScenario = 'real',
): Promise<SimulationResult> {
  return getJson(stage2Url(`/api/simulation/site/${encodeURIComponent(siteId)}`, scenario))
}

export function fetchSimulationProvenance(
  siteId: string,
  scenario: SimulationScenario = 'real',
): Promise<SimulationProvenance> {
  return getJson(
    stage2Url(`/api/simulation/site/${encodeURIComponent(siteId)}/provenance`, scenario),
  )
}

/**
 * Starts a real precompute run. Returns immediately (HTTP 202) — poll
 * `fetchPrecomputeStatus` for real progress.
 *
 * `force` defaults to false: the backend checks whether a previously-
 * computed result for this scenario is still current (Stage 1B's
 * forecast hasn't changed) and reuses it in a few seconds instead of
 * redoing the ~1-2 minute solver+GNN pipeline — see
 * `stage2/routes.py::_run_precompute_job`'s own docstring. Pass
 * `force: true` (the "Re-run simulation" button, once a result already
 * exists) to always recompute.
 */
export function startPrecompute(
  siteId: string,
  scenario: SimulationScenario = 'real',
  force = false,
): Promise<PrecomputeStatus> {
  const url = new URL(stage2Url(`/api/simulation/precompute/${encodeURIComponent(siteId)}`, scenario))
  if (force) url.searchParams.set('force', 'true')
  return getJson(url.toString(), { method: 'POST' })
}

export function fetchPrecomputeStatus(
  siteId: string,
  scenario: SimulationScenario = 'real',
): Promise<PrecomputeStatus> {
  return getJson(
    stage2Url(`/api/simulation/precompute/${encodeURIComponent(siteId)}/status`, scenario),
  )
}

export function fetchSensorLocation(siteId: string): Promise<SensorLocation> {
  return getJson(`${STAGE_BASE_URLS.stage2}/api/sensor/location/${encodeURIComponent(siteId)}`)
}

export function postSimulationAssimilate(reading: SensorReading): Promise<SimulationResult> {
  return getJson(`${STAGE_BASE_URLS.stage2}/api/simulation/assimilate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reading),
  })
}

// ---------------------------------------------------------------- Stage 3

export function fetchDamageRanking(
  siteId: string,
  scenario: SimulationScenario = 'real',
): Promise<DamageRankEntry[]> {
  const url = new URL(`${STAGE_BASE_URLS.stage3}/api/damage-ranking/${encodeURIComponent(siteId)}`)
  // Stage 3 ranks against whichever Stage 2 scenario is named, so this
  // must travel with the request -- see its own routes.py docstring.
  url.searchParams.set('scenario', scenario)
  return getJson(url.toString())
}

// ---------------------------------------------------------------- Stage 4

/**
 * The DRAFT alert — derived automatically from the current simulation and
 * ranking. Always returns something, and is what the Alert Composer
 * previews. NOT what the public sees: see `fetchActiveAlert`.
 */
export function fetchAlert(siteId: string): Promise<Alert> {
  return getJson(`${STAGE_BASE_URLS.stage4}/api/alert/${encodeURIComponent(siteId)}`)
}

/**
 * Terrain heightmaps for the 3D scene (T4B.3).
 *
 * Served by Stage 4, not Stage 2, because neither Stage 1B's regional DEM
 * nor Stage 2's `TerrainGrid` was ever exposed over HTTP — see
 * `backend/stage4/terrain/dem_proxy.py`'s module docstring. Returns 503
 * (never a synthetic flat surface) if no real DEM covers the site.
 */
export function fetchSiteTerrain(siteId: string): Promise<SiteTerrainResponse> {
  return getJson(`${STAGE_BASE_URLS.stage4}/api/terrain/${encodeURIComponent(siteId)}`)
}

/**
 * URL of the site mesh GLB (`Building_01/02` + `Road_Network`) for the 3D
 * scene (T4B.4). Not `getJson` — the response body is a binary GLB, not
 * JSON; `SiteMesh.tsx` hands this URL straight to drei's `useGLTF`, which
 * does its own fetch/parse. See `backend/stage4/scene/site_mesh.py` for
 * why this is pre-transformed server-side into `Terrain.tsx`'s exact
 * scene frame, rather than shipping the georeferencing fit to redo here.
 */
export function siteMeshUrl(siteId: string): string {
  return `${STAGE_BASE_URLS.stage4}/api/site-mesh/${encodeURIComponent(siteId)}`
}

/**
 * Real per-node `(x_m, z_m, elevation_m)` for Stage 2's computational
 * mesh (T4B.5) — see `backend/stage4/scene/mesh_nodes.py`'s docstring.
 * Unlike site-mesh, this has no placeholder fallback: a 503 here means
 * genuinely no real node positions exist, never a fabricated grid.
 */
export function fetchSiteMeshNodes(siteId: string): Promise<SiteMeshNodesResponse> {
  return getJson(`${STAGE_BASE_URLS.stage4}/api/mesh-nodes/${encodeURIComponent(siteId)}`)
}

// ------------------------------------------------- TanStack Query helpers

/** Query keys, centralised so a cache invalidation can't typo a key. */
/**
 * The alert currently IN EFFECT for the public, if any.
 *
 * Rejects with a 404 `ApiError` when nothing has been issued — the honest
 * "no warning in effect" state. A draft alert existing is not the same as
 * a warning having been issued; only a real operator pressing Issue in
 * the Alert Composer makes one public.
 */
export function fetchActiveAlert(siteId: string): Promise<Alert> {
  return getJson(`${STAGE_BASE_URLS.stage4}/api/alert/${encodeURIComponent(siteId)}/active`)
}

/** Publish the current draft alert to the Citizen View. */
export function issueAlert(siteId: string): Promise<Alert> {
  return getJson(`${STAGE_BASE_URLS.stage4}/api/alert/${encodeURIComponent(siteId)}/issue`, {
    method: 'POST',
  })
}

/** Stand down the active alert. Idempotent, and returns 204 (no body). */
export async function withdrawAlert(siteId: string): Promise<void> {
  const url = `${STAGE_BASE_URLS.stage4}/api/alert/${encodeURIComponent(siteId)}/withdraw`
  const response = await fetch(url, { method: 'POST' })
  if (!response.ok) {
    throw new ApiError(response.status, url, await response.text().catch(() => ''))
  }
}

export const queryKeys = {
  regionalForecast: ['regionalForecast'] as const,
  riverStage: (lat: number, lon: number) => ['riverStage', lat, lon] as const,
  downscaled: (lat: number, lon: number) => ['downscaled', lat, lon] as const,
  simulation: (siteId: string, scenario: SimulationScenario = 'real') =>
    ['simulation', siteId, scenario] as const,
  simulationProvenance: (siteId: string, scenario: SimulationScenario = 'real') =>
    ['simulationProvenance', siteId, scenario] as const,
  precomputeStatus: (siteId: string, scenario: SimulationScenario = 'real') =>
    ['precomputeStatus', siteId, scenario] as const,
  sensorLocation: (siteId: string) => ['sensorLocation', siteId] as const,
  damageRanking: (siteId: string) => ['damageRanking', siteId] as const,
  alert: (siteId: string) => ['alert', siteId] as const,
  activeAlert: (siteId: string) => ['activeAlert', siteId] as const,
  siteTerrain: (siteId: string) => ['siteTerrain', siteId] as const,
  siteMesh: (siteId: string) => ['siteMesh', siteId] as const,
  meshNodes: (siteId: string) => ['meshNodes', siteId] as const,
}
