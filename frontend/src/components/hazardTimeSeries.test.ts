import { describe, expect, it } from 'vitest'

import type { NodeState } from '../api/types'
import { computeHazardTimeSeries, hourToX, scaleSeries } from './hazardTimeSeries'

function makeNodeState(overrides: Partial<NodeState>): NodeState {
  return {
    node_id: 'n_0_0',
    hour: 0,
    depth_mean_m: 0,
    depth_min_m: 0,
    depth_max_m: 0,
    velocity_mean_mps: 0,
    velocity_min_mps: 0,
    velocity_max_mps: 0,
    rate_of_rise: 0,
    ensemble_agreement_fraction: 0.8,
    building_id: null,
    road_segment_id: null,
    ...overrides,
  }
}

describe('computeHazardTimeSeries', () => {
  it('skips hours with no real node covering the structure', () => {
    const points = computeHazardTimeSeries({ 0: {} }, [0], 'Building_01')
    expect(points).toHaveLength(0)
  })

  it('picks the single peak-depth node per hour, not independently maxed fields', () => {
    const nodeStatesByHour = {
      24: {
        n_1: makeNodeState({
          node_id: 'n_1',
          building_id: 'Building_01',
          depth_mean_m: 0.5,
          velocity_mean_mps: 5.0, // fast but shallow -- must NOT win
          rate_of_rise: 0.9,
        }),
        n_2: makeNodeState({
          node_id: 'n_2',
          building_id: 'Building_01',
          depth_mean_m: 1.5, // deepest -- this node's own values should win together
          velocity_mean_mps: 0.4,
          rate_of_rise: 0.05,
        }),
      },
    }
    const points = computeHazardTimeSeries(nodeStatesByHour, [24], 'Building_01')
    expect(points).toEqual([{ hour: 24, depthM: 1.5, velocityMps: 0.4, rateOfRise: 0.05 }])
  })

  it('only includes nodes tagged with the real structure_id (building or road)', () => {
    const nodeStatesByHour = {
      12: {
        n_1: makeNodeState({ node_id: 'n_1', building_id: 'Building_02', depth_mean_m: 9 }),
        n_2: makeNodeState({ node_id: 'n_2', road_segment_id: 'Road_Segment_000', depth_mean_m: 0.3 }),
      },
    }
    const points = computeHazardTimeSeries(nodeStatesByHour, [12], 'Road_Segment_000')
    expect(points).toEqual([{ hour: 12, depthM: 0.3, velocityMps: 0, rateOfRise: 0 }])
  })

  it('produces one point per real available hour, in order', () => {
    const nodeStatesByHour = {
      12: { n_1: makeNodeState({ node_id: 'n_1', building_id: 'Building_01', depth_mean_m: 1 }) },
      24: { n_1: makeNodeState({ node_id: 'n_1', building_id: 'Building_01', depth_mean_m: 2 }) },
    }
    const points = computeHazardTimeSeries(nodeStatesByHour, [12, 24], 'Building_01')
    expect(points.map((p) => p.hour)).toEqual([12, 24])
  })
})

describe('scaleSeries', () => {
  const points = [
    { hour: 0, depthM: 0, velocityMps: 0, rateOfRise: 0 },
    { hour: 12, depthM: 2, velocityMps: 1, rateOfRise: 0.5 },
  ]

  it('returns an empty series for no real points, never dividing by zero', () => {
    expect(scaleSeries([], (p) => p.depthM, 100, 50)).toEqual({ points: [], maxValue: 1 })
  })

  it('scales each real field independently -- its own y-axis, not a shared one', () => {
    const depthSeries = scaleSeries(points, (p) => p.depthM, 100, 50)
    const velocitySeries = scaleSeries(points, (p) => p.velocityMps, 100, 50)
    expect(depthSeries.maxValue).toBe(2)
    expect(velocitySeries.maxValue).toBe(1)
    // Same real x position (hour=12) for both -- only y differs.
    expect(depthSeries.points[1].x).toBeCloseTo(velocitySeries.points[1].x, 6)
  })

  it('never divides by zero when every real value is 0', () => {
    const zeroSeries = scaleSeries(points, () => 0, 100, 50)
    expect(zeroSeries.maxValue).toBe(1)
    expect(zeroSeries.points.every((p) => Number.isFinite(p.y))).toBe(true)
  })
})

describe('hourToX', () => {
  it('maps the current hour onto the same x-scale as the real data points', () => {
    const points = [
      { hour: 0, depthM: 0, velocityMps: 0, rateOfRise: 0 },
      { hour: 100, depthM: 0, velocityMps: 0, rateOfRise: 0 },
    ]
    expect(hourToX(50, points, 200)).toBeCloseTo(100, 6)
  })

  it('returns 0 for an empty series rather than throwing', () => {
    expect(hourToX(10, [], 200)).toBe(0)
  })
})
