import { describe, expect, it } from 'vitest'

import type { RegionalEnsembleForecast } from '../api/types'
import { computeExceedanceReadout, computeFanChartGeometry, pointsToPolyline } from './fanChartGeometry'

function makeForecast(memberRainfall: number[][]): RegionalEnsembleForecast {
  return {
    forecast_id: 'test',
    source: 'GEFS',
    region_bbox: { min_lat: 0, max_lat: 1, min_lon: 0, max_lon: 1 },
    generated_at: '2026-08-21T00:00:00Z',
    resolution_km: 27.75,
    members: memberRainfall.map((trajectory, i) => ({
      member_id: i,
      trajectory: trajectory.map((rainfall_mm, hourIndex) => ({
        hour: hourIndex * 6,
        rainfall_mm,
      })),
    })),
  }
}

describe('computeFanChartGeometry', () => {
  it('returns null for an empty ensemble rather than dividing by zero', () => {
    expect(computeFanChartGeometry(makeForecast([]), 300, 140)).toBeNull()
  })

  it('maps one point per member per real hour', () => {
    const forecast = makeForecast([
      [1, 2, 3],
      [2, 4, 6],
    ])
    const geometry = computeFanChartGeometry(forecast, 300, 140)!
    expect(geometry.memberCount).toBe(2)
    expect(geometry.memberLines).toHaveLength(2)
    expect(geometry.memberLines[0]).toHaveLength(3)
    expect(geometry.hours).toEqual([0, 6, 12])
  })

  it('the mean line is the real per-hour average, not one member copied', () => {
    const forecast = makeForecast([
      [0, 10],
      [10, 0],
    ])
    const geometry = computeFanChartGeometry(forecast, 100, 100)!
    // Both hours average to 5 -- with maxValue=10, y should sit at the
    // vertical midpoint (50) for both real mean points.
    expect(geometry.meanLine[0].y).toBeCloseTo(50, 5)
    expect(geometry.meanLine[1].y).toBeCloseTo(50, 5)
  })

  it('never divides by zero when every real member reports zero rainfall', () => {
    const forecast = makeForecast([[0, 0], [0, 0]])
    const geometry = computeFanChartGeometry(forecast, 100, 100)!
    expect(Number.isFinite(geometry.meanLine[0].y)).toBe(true)
    expect(geometry.maxValue).toBeGreaterThan(0)
  })
})

describe('pointsToPolyline', () => {
  it('formats points as an SVG polyline points string', () => {
    expect(pointsToPolyline([{ x: 1, y: 2 }, { x: 3.456, y: 7 }])).toBe('1.00,2.00 3.46,7.00')
  })
})

describe('computeExceedanceReadout', () => {
  it('returns null for an empty ensemble', () => {
    expect(computeExceedanceReadout(makeForecast([]))).toBeNull()
  })

  it('counts real members at/above the ensemble\'s own 90th percentile cumulative total', () => {
    // 10 members, cumulative totals 10..100 in steps of 10 -- p90 index
    // floor(10*0.9)=9 -> the 10th (largest) value, so exactly 1 member
    // is >= its own 90th percentile by construction.
    const members = Array.from({ length: 10 }, (_, i) => [((i + 1) * 10)])
    const readout = computeExceedanceReadout(makeForecast(members))!
    expect(readout.totalCount).toBe(10)
    expect(readout.exceedingCount).toBe(1)
    expect(readout.thresholdMm).toBe(100)
  })

  it('reports the real last hour in the trajectory', () => {
    const readout = computeExceedanceReadout(makeForecast([[1, 2, 3, 4]]))!
    expect(readout.atHour).toBe(18) // hourIndex 3 * 6
  })
})
