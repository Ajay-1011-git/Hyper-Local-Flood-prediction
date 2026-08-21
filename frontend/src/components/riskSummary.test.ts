import { describe, expect, it } from 'vitest'

import type { DamageRankEntry } from '../api/types'
import { confidencePercent, depthLabel, hazardSummary } from './riskSummary'

function makeEntry(overrides: Partial<DamageRankEntry> = {}): DamageRankEntry {
  return {
    structure_id: 'Building_01',
    structure_type: 'building',
    site_id: 'test',
    hazard_score: 1,
    exposure_score: 1,
    vulnerability_score: 0.5,
    vulnerability_source: 'test',
    vulnerability_is_local_calibration: false,
    risk_score: 1,
    confidence: 0.82,
    rank: 1,
    peak_hour: 24,
    peak_depth_m: 1.2,
    peak_velocity_mps: 1.4,
    peak_rate_of_rise: 0.05,
    ...overrides,
  }
}

describe('hazardSummary', () => {
  it('matches the User Flow doc\'s own example shape', () => {
    expect(hazardSummary(makeEntry())).toBe('1.2m depth, fast flow, rising')
  })

  it('describes moderate and calm flow at the real named thresholds', () => {
    expect(hazardSummary(makeEntry({ peak_velocity_mps: 0.5 }))).toContain('moderate flow')
    expect(hazardSummary(makeEntry({ peak_velocity_mps: 0.1 }))).toContain('calm flow')
  })

  it('describes falling and steady trends from real rate_of_rise', () => {
    expect(hazardSummary(makeEntry({ peak_rate_of_rise: -0.02 }))).toContain('falling')
    expect(hazardSummary(makeEntry({ peak_rate_of_rise: 0 }))).toContain('steady')
  })
})

describe('confidencePercent', () => {
  it('rounds the real confidence fraction to a whole percent', () => {
    expect(confidencePercent(makeEntry({ confidence: 0.826 }))).toBe(83)
  })
})

describe('depthLabel', () => {
  it('shows real centimetre-scale water instead of collapsing it to 0.0m', () => {
    // 7cm of standing water on a road is a real, rankable hazard; the
    // previous toFixed(1) rendered it as "0.0m".
    expect(depthLabel(0.0718)).toBe('7cm')
    expect(depthLabel(0.0007)).toBe('0cm')
  })

  it('keeps metres for water deep enough for the unit to matter', () => {
    expect(depthLabel(0.46)).toBe('0.5m')
    expect(depthLabel(1.62)).toBe('1.6m')
  })
})
