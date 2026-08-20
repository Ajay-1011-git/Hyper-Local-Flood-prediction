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
  SensorReading,
  SimulationResult,
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

/** Stage 1A's `RiverStageForecast` — kept loosely typed; the frontend only
 *  needs the CWC cross-check INDICATOR (User Flow §3.2), not the full
 *  series, and this project's TS mirrors deliberately cover only the
 *  contracts actually consumed. */
export function fetchRiverStageForecast(lat: number, lon: number): Promise<unknown> {
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

export function fetchSimulationResult(siteId: string): Promise<SimulationResult> {
  return getJson(`${STAGE_BASE_URLS.stage2}/api/simulation/site/${encodeURIComponent(siteId)}`)
}

export function postSimulationAssimilate(reading: SensorReading): Promise<SimulationResult> {
  return getJson(`${STAGE_BASE_URLS.stage2}/api/simulation/assimilate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reading),
  })
}

// ---------------------------------------------------------------- Stage 3

export function fetchDamageRanking(siteId: string): Promise<DamageRankEntry[]> {
  return getJson(`${STAGE_BASE_URLS.stage3}/api/damage-ranking/${encodeURIComponent(siteId)}`)
}

// ---------------------------------------------------------------- Stage 4

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

// ------------------------------------------------- TanStack Query helpers

/** Query keys, centralised so a cache invalidation can't typo a key. */
export const queryKeys = {
  regionalForecast: ['regionalForecast'] as const,
  riverStage: (lat: number, lon: number) => ['riverStage', lat, lon] as const,
  downscaled: (lat: number, lon: number) => ['downscaled', lat, lon] as const,
  simulation: (siteId: string) => ['simulation', siteId] as const,
  damageRanking: (siteId: string) => ['damageRanking', siteId] as const,
  alert: (siteId: string) => ['alert', siteId] as const,
  siteTerrain: (siteId: string) => ['siteTerrain', siteId] as const,
}
