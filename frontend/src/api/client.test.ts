import { describe, expect, it, vi, afterEach } from 'vitest'
import {
  ApiError,
  STAGE_BASE_URLS,
  fetchAlert,
  fetchDamageRanking,
  fetchDownscaledForecast,
  fetchSimulationResult,
  fetchSiteMeshNodes,
  queryKeys,
  siteMeshUrl,
} from './client'

/**
 * Tests for T4B.0's API client. `fetch` is stubbed — these assert the
 * client builds the REAL, confirmed endpoint paths (read directly from
 * each stage's own route decorators) and fails loudly on non-2xx, rather
 * than testing the backends themselves.
 */

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubFetch(body: unknown, ok = true, status = 200) {
  // Typed with the real (input, init) signature so `mock.calls[0][0]` is
  // a real indexable tuple — a zero-arg `vi.fn(async () => ...)` types
  // calls as `[]`, which is a genuine `tsc` error (TS2493) under this
  // project's `npm run build`, not just a lint nit.
  const spy = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
    ok,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }))
  vi.stubGlobal('fetch', spy)
  return spy
}

describe('endpoint paths match the real backend routes', () => {
  it('builds Stage 4 alert URL with the real path', async () => {
    const spy = stubFetch({ id: 'x' })
    await fetchAlert('vit-vellore')
    expect(spy).toHaveBeenCalledWith(
      `${STAGE_BASE_URLS.stage4}/api/alert/vit-vellore`,
      undefined,
    )
  })

  it('builds Stage 3 damage-ranking URL with the real path', async () => {
    const spy = stubFetch([])
    await fetchDamageRanking('vit-vellore')
    expect(spy).toHaveBeenCalledWith(
      `${STAGE_BASE_URLS.stage3}/api/damage-ranking/vit-vellore`,
      undefined,
    )
  })

  it('builds Stage 2 simulation URL with the real path', async () => {
    const spy = stubFetch({ simulation_id: 'x' })
    await fetchSimulationResult('vit-vellore')
    expect(spy).toHaveBeenCalledWith(
      `${STAGE_BASE_URLS.stage2}/api/simulation/site/vit-vellore`,
      undefined,
    )
  })

  it('uses lat/lon QUERY params for Stage 1B, not a site_id path segment', async () => {
    // Stage 1B's route really is ?lat=&lon= -- a real spec reconciliation
    // documented in that module's own docstring. Getting this wrong would
    // 404 against the real server.
    const spy = stubFetch({ site_id: 'x' })
    await fetchDownscaledForecast(12.969223, 79.155934)
    const calledUrl = String(spy.mock.calls[0][0])
    expect(calledUrl).toContain('/api/forecast/downscaled')
    expect(calledUrl).toContain('lat=12.969223')
    expect(calledUrl).toContain('lon=79.155934')
  })

  it('encodes a site id containing URL-unsafe characters', async () => {
    const spy = stubFetch({ id: 'x' })
    await fetchAlert('site with spaces')
    expect(String(spy.mock.calls[0][0])).toContain('site%20with%20spaces')
  })

  it('builds the Stage 4 site-mesh URL with the real path (T4B.4)', () => {
    expect(siteMeshUrl('vit-vellore')).toBe(
      `${STAGE_BASE_URLS.stage4}/api/site-mesh/vit-vellore`,
    )
  })

  it('encodes a site id in the site-mesh URL', () => {
    expect(siteMeshUrl('site with spaces')).toContain('site%20with%20spaces')
  })

  it('builds the Stage 4 mesh-nodes URL with the real path (T4B.5)', async () => {
    const spy = stubFetch({ site_id: 'x', rows: 1, cols: 1, resolution_m: 1, nodes: [] })
    await fetchSiteMeshNodes('vit-vellore')
    expect(spy).toHaveBeenCalledWith(
      `${STAGE_BASE_URLS.stage4}/api/mesh-nodes/vit-vellore`,
      undefined,
    )
  })
})

describe('error handling', () => {
  it('throws a typed ApiError on non-2xx instead of returning empty data', async () => {
    stubFetch({ detail: 'nope' }, false, 503)
    await expect(fetchAlert('vit-vellore')).rejects.toBeInstanceOf(ApiError)
  })

  it('carries the real status code on the error', async () => {
    stubFetch({ detail: 'nope' }, false, 503)
    await expect(fetchAlert('vit-vellore')).rejects.toMatchObject({ status: 503 })
  })
})

describe('query keys', () => {
  it('are stable and parameterised so a cache entry cannot collide across sites', () => {
    expect(queryKeys.alert('a')).not.toEqual(queryKeys.alert('b'))
    expect(queryKeys.damageRanking('a')).toEqual(['damageRanking', 'a'])
  })
})
