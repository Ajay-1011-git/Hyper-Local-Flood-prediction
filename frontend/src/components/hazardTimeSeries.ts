/**
 * Pure per-structure hazard time-series maths (T4C.2) — the "depth,
 * velocity, and rate-of-rise plotted together across the 72-hour window"
 * User Flow §3.3 asks for. Split out for the same reason every other
 * `*Geometry.ts`/pure-logic module in this project is: real, unit-
 * testable maths without mounting a chart.
 *
 * SAME "PEAK NODE" CONVENTION AS STAGE 3's OWN RANKING, NOT A NEW ONE
 * ---------------------------------------------------------------
 * Stage 3's `risk_ranking.py::_structure_peak_hazard` is explicit
 * ("Peak across this structure's own set of nodes, anchored on depth")
 * — at each hour, it finds the one real node with the greatest depth and
 * reports THAT node's depth/velocity/rate_of_rise together, rather than
 * independently maxing each field across different nodes (which could
 * combine a deep-but-slow node's depth with a shallow-but-fast node's
 * velocity — a real hazard state that never actually occurred at any
 * single point). This module mirrors that exact convention per-hour, so
 * this chart and Stage 3's own ranking describe the same real structure
 * the same way.
 */

import type { NodeState } from '../api/types'

export interface HazardTimeSeriesPoint {
  hour: number
  depthM: number
  velocityMps: number
  rateOfRise: number
}

export function computeHazardTimeSeries(
  nodeStatesByHour: Record<number, Record<string, NodeState>>,
  hoursAvailable: number[],
  structureId: string,
): HazardTimeSeriesPoint[] {
  const points: HazardTimeSeriesPoint[] = []

  for (const hour of hoursAvailable) {
    const statesAtHour = nodeStatesByHour[hour] ?? {}
    let peak: NodeState | null = null
    // Deterministic tie-break by node_id, mirroring Stage 3's own
    // `max(sorted(per_node), key=...)` -- `Object.values` iteration
    // order is not itself a real tie-break rule to rely on.
    const candidates = Object.values(statesAtHour)
      .filter((ns) => ns.building_id === structureId || ns.road_segment_id === structureId)
      .sort((a, b) => a.node_id.localeCompare(b.node_id))

    for (const candidate of candidates) {
      if (!peak || candidate.depth_mean_m > peak.depth_mean_m) peak = candidate
    }

    if (!peak) continue
    points.push({
      hour,
      depthM: peak.depth_mean_m,
      velocityMps: peak.velocity_mean_mps,
      rateOfRise: peak.rate_of_rise,
    })
  }

  return points
}

export interface ScaledPoint {
  x: number
  y: number
}

export interface ScaledSeries {
  points: ScaledPoint[]
  maxValue: number
}

/**
 * Maps one real field of `points` into SVG-space (y=0 at top, inverted so
 * a larger value draws higher). Each of depth/velocity/rate-of-rise gets
 * its OWN call (its own y-scale) — three different units plotted on one
 * shared axis would be a real dual/triple-axis chart, which this project
 * avoids per the dataviz convention of one axis per real unit ("small
 * multiples sharing an x-axis", not a combined y-scale).
 */
export function scaleSeries(
  points: HazardTimeSeriesPoint[],
  valueOf: (point: HazardTimeSeriesPoint) => number,
  width: number,
  height: number,
): ScaledSeries {
  if (points.length === 0) return { points: [], maxValue: 1 }

  const hours = points.map((p) => p.hour)
  const minHour = Math.min(...hours)
  const maxHour = Math.max(...hours)
  const hourSpan = maxHour - minHour || 1

  let maxValue = Math.max(...points.map(valueOf))
  if (maxValue <= 0) maxValue = 1 // a real all-zero series is possible; avoid a /0 y-scale

  const scaled = points.map((point) => ({
    x: ((point.hour - minHour) / hourSpan) * width,
    y: height - (valueOf(point) / maxValue) * height,
  }))

  return { points: scaled, maxValue }
}

/** Maps a real hour value (e.g. the timeline's current position) to the
 *  same x-scale `scaleSeries` used, so a marker line lines up exactly
 *  with the real data points around it. */
export function hourToX(hour: number, points: HazardTimeSeriesPoint[], width: number): number {
  if (points.length === 0) return 0
  const hours = points.map((p) => p.hour)
  const minHour = Math.min(...hours)
  const maxHour = Math.max(...hours)
  const hourSpan = maxHour - minHour || 1
  return ((hour - minHour) / hourSpan) * width
}
