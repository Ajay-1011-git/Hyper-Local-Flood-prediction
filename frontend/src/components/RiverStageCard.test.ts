import { describe, expect, it } from 'vitest'

import type { RiverStageForecast } from '../api/types'
import { deriveState } from './RiverStageCard'

function makeForecast(overrides: Partial<RiverStageForecast> = {}): RiverStageForecast {
  return {
    source: 'CWC',
    station_id: 'test',
    station_name: 'Test Station',
    lat: 12.9,
    lon: 79.1,
    forecast_horizon_hours: 72,
    trajectory: [],
    breach_threshold_m: 5,
    breach_probability: 0.1,
    station_proximity_verified: true,
    ...overrides,
  }
}

describe('deriveState', () => {
  it('is loading while the query is pending', () => {
    expect(deriveState(undefined, undefined, true)).toBe('loading')
  })

  it('is unavailable on a real fetch error', () => {
    expect(deriveState(undefined, new Error('network'), false)).toBe('unavailable')
  })

  it('is no-station when Stage 1A honestly reports no verified nearby station', () => {
    expect(deriveState(makeForecast({ station_proximity_verified: false }), undefined, false)).toBe(
      'no-station',
    )
  })

  it('is unavailable (never fabricated) when breach_probability is null', () => {
    expect(deriveState(makeForecast({ breach_probability: null }), undefined, false)).toBe('unavailable')
  })

  it('agrees when breach_probability crosses the real 0.5 threshold', () => {
    expect(deriveState(makeForecast({ breach_probability: 0.6 }), undefined, false)).toBe('agrees')
  })

  it('diverges below the 0.5 threshold', () => {
    expect(deriveState(makeForecast({ breach_probability: 0.4 }), undefined, false)).toBe('diverges')
  })
})
