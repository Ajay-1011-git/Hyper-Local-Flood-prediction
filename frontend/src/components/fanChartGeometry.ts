/**
 * Pure fan-chart maths (T4C.1) — split from `EnsembleFanChart.tsx` for the
 * same reason `terrainGeometry.ts`/`waterGeometry.ts` are split from their
 * components: real logic, unit-testable without mounting anything.
 *
 * Renders Stage 1A's real `RegionalEnsembleForecast` (per-member rainfall
 * trajectories, real member count — 31 for GEFS, 8 for WN2 Mini,
 * confirmed to vary by source in that stage's own CLAUDE.md) as a fan:
 * every member's real trajectory, plus the real per-hour mean/min/max
 * band computed here from them — never a fabricated "typical" scenario.
 */

import type { RegionalEnsembleForecast } from '../api/types'

export interface FanChartPoint {
  x: number
  y: number
}

export interface FanChartGeometry {
  /** One polyline-ready point array per real ensemble member. */
  memberLines: FanChartPoint[][]
  /** The real per-hour mean across all members — drawn as the solid
   *  "most likely" line on top of the translucent fan. */
  meanLine: FanChartPoint[]
  hours: number[]
  minValue: number
  maxValue: number
  memberCount: number
}

/**
 * Maps `forecast.members[*].trajectory` into SVG-space points for a
 * `viewBoxWidth`x`viewBoxHeight` chart (y=0 at the top, per SVG
 * convention — higher rainfall draws HIGHER on screen via inversion).
 *
 * Assumes every member shares the same real hour grid (true for both
 * real sources this project uses — confirmed structurally: each
 * `EnsembleMember.trajectory` is built from the same fetch cycle).
 */
export function computeFanChartGeometry(
  forecast: RegionalEnsembleForecast,
  viewBoxWidth: number,
  viewBoxHeight: number,
): FanChartGeometry | null {
  const hours = forecast.members[0]?.trajectory.map((t) => t.hour) ?? []
  if (hours.length === 0 || forecast.members.length === 0) return null

  const maxHour = Math.max(...hours)
  const minHour = Math.min(...hours)
  const hourSpan = maxHour - minHour || 1

  let maxValue = 0
  const meanByHour: number[] = []
  for (let i = 0; i < hours.length; i += 1) {
    let sum = 0
    for (const member of forecast.members) {
      const v = member.trajectory[i]?.rainfall_mm ?? 0
      sum += v
      if (v > maxValue) maxValue = v
    }
    meanByHour.push(sum / forecast.members.length)
  }
  // A real value of exactly 0 would divide-by-zero the y-scale; a flat
  // all-zero forecast is a real (if boring) possibility, not fabricated
  // headroom.
  if (maxValue <= 0) maxValue = 1

  const toPoint = (hour: number, value: number): FanChartPoint => ({
    x: ((hour - minHour) / hourSpan) * viewBoxWidth,
    y: viewBoxHeight - (value / maxValue) * viewBoxHeight,
  })

  const memberLines = forecast.members.map((member) =>
    member.trajectory.map((t) => toPoint(t.hour, t.rainfall_mm)),
  )
  const meanLine = hours.map((hour, i) => toPoint(hour, meanByHour[i]))

  return {
    memberLines,
    meanLine,
    hours,
    minValue: 0,
    maxValue,
    memberCount: forecast.members.length,
  }
}

export function pointsToPolyline(points: FanChartPoint[]): string {
  return points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ')
}

export interface ExceedanceReadout {
  exceedingCount: number
  totalCount: number
  thresholdMm: number
  atHour: number
}

/**
 * "N of M scenarios exceed threshold by hour X" (User Flow §3.2's own
 * example phrasing). No hazard threshold exists in the real
 * `RegionalEnsembleForecast` contract (that's Stage 2's depth-based
 * `hazard_threshold_m`, a different unit/stage entirely) — rather than
 * invent an external rainfall-mm threshold, this uses the ensemble's OWN
 * 90th-percentile cumulative total (summed rainfall across the whole
 * real trajectory) as the reference "severe scenario" band, at the
 * LAST real hour in the forecast. Self-referential, always computable,
 * never a fabricated meteorological number.
 */
export function computeExceedanceReadout(forecast: RegionalEnsembleForecast): ExceedanceReadout | null {
  if (forecast.members.length === 0) return null
  const cumulativeTotals = forecast.members.map((member) =>
    member.trajectory.reduce((sum, t) => sum + t.rainfall_mm, 0),
  )
  const sorted = [...cumulativeTotals].sort((a, b) => a - b)
  const p90Index = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.9))
  const thresholdMm = sorted[p90Index]
  const exceedingCount = cumulativeTotals.filter((total) => total >= thresholdMm).length
  const lastHour = forecast.members[0]?.trajectory.at(-1)?.hour ?? 0

  return {
    exceedingCount,
    totalCount: forecast.members.length,
    thresholdMm,
    atHour: lastHour,
  }
}
