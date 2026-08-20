import { describe, expect, it } from 'vitest'

import { SEVERITY_COLORS, SEVERITY_ORDER, capSeverityToUiSeverity, severityForEntry } from './severity'

describe('severityForEntry', () => {
  it('stays Monitoring before the structure reaches its real peak_hour', () => {
    expect(severityForEntry({ risk_score: 1000, peak_hour: 48 }, 24, 1000)).toBe('Monitoring')
  })

  it('is Critical once the timeline reaches peak_hour with the ranking-max risk_score', () => {
    expect(severityForEntry({ risk_score: 1000, peak_hour: 24 }, 24, 1000)).toBe('Critical')
  })

  it('tiers Warning at the 0.5 normalized breakpoint', () => {
    expect(severityForEntry({ risk_score: 500, peak_hour: 24 }, 24, 1000)).toBe('Warning')
  })

  it('tiers Watch at the 0.25 normalized breakpoint', () => {
    expect(severityForEntry({ risk_score: 250, peak_hour: 24 }, 24, 1000)).toBe('Watch')
  })

  it('stays Monitoring below 0.25 normalized even after peak_hour', () => {
    expect(severityForEntry({ risk_score: 100, peak_hour: 24 }, 24, 1000)).toBe('Monitoring')
  })

  it('never divides by zero when the whole ranking has zero risk', () => {
    expect(severityForEntry({ risk_score: 0, peak_hour: 0 }, 24, 0)).toBe('Monitoring')
  })

  it('clamps a risk_score above the ranking max to Critical, not >100%', () => {
    // Real data should never produce this (max IS the max by construction),
    // but a caller passing a stale/mismatched max must not crash or invert.
    expect(severityForEntry({ risk_score: 2000, peak_hour: 0 }, 24, 1000)).toBe('Critical')
  })

  it('exposes exactly the four real states in low-to-high order', () => {
    expect(SEVERITY_ORDER).toEqual(['Monitoring', 'Watch', 'Warning', 'Critical'])
  })

  it('defines a real color for every severity state', () => {
    for (const state of SEVERITY_ORDER) {
      expect(SEVERITY_COLORS[state]).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
})

describe('capSeverityToUiSeverity', () => {
  it('maps every real CAP severity enum value to a real UI state', () => {
    expect(capSeverityToUiSeverity('Extreme')).toBe('Critical')
    expect(capSeverityToUiSeverity('Severe')).toBe('Warning')
    expect(capSeverityToUiSeverity('Moderate')).toBe('Watch')
    expect(capSeverityToUiSeverity('Minor')).toBe('Monitoring')
  })

  it('falls back to Monitoring for Unknown/unexpected values, never throws', () => {
    expect(capSeverityToUiSeverity('Unknown')).toBe('Monitoring')
    expect(capSeverityToUiSeverity('something-unexpected')).toBe('Monitoring')
  })
})
