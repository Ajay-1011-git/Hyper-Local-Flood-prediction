/**
 * HazardTimeSeriesChart — Site Detail's real time-series (T4C.2, User
 * Flow §3.3): "depth, velocity, and rate-of-rise plotted together across
 * the 72-hour window, with the current timeline position marked."
 *
 * THREE SMALL MULTIPLES, ONE SHARED X-AXIS — NOT A TRIPLE-AXIS CHART
 * ---------------------------------------------------------------
 * Depth (m), velocity (m/s), and rate-of-rise (m/hr) are three different
 * units/scales. Per the dataviz convention ("two measures of different
 * scale -> two charts, small multiples, or indexed to a common base" —
 * never a dual/multi-axis chart, the #1 real chart mistake), this is
 * three stacked mini line charts sharing one real x-axis (hour), each
 * with its OWN correctly-scaled y-axis — "plotted together" as one
 * visual group, never combined onto one misleading shared y-scale.
 */

import { useMemo } from 'react'

import type { NodeState } from '../api/types'
import {
  computeHazardTimeSeries,
  hourToX,
  scaleSeries,
  type HazardTimeSeriesPoint,
} from './hazardTimeSeries'

const CHART_W = 260
const SUB_H = 46
const GAP = 10

interface SubChartProps {
  label: string
  unit: string
  color: string
  points: HazardTimeSeriesPoint[]
  valueOf: (point: HazardTimeSeriesPoint) => number
  currentHour: number
}

function SubChart({ label, unit, color, points, valueOf, currentHour }: SubChartProps) {
  const { points: scaled, maxValue } = useMemo(
    () => scaleSeries(points, valueOf, CHART_W, SUB_H),
    [points, valueOf],
  )
  const markerX = useMemo(() => hourToX(currentHour, points, CHART_W), [points, currentHour])
  const polyline = scaled.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const latest = points.at(-1)

  return (
    <div style={{ marginBottom: GAP }}>
      <div
        className="font-data"
        style={{ fontSize: '0.7rem', color: 'var(--ops-text-dim)', display: 'flex', justifyContent: 'space-between' }}
      >
        <span>
          {label} ({unit})
        </span>
        <span>max {maxValue.toFixed(2)}</span>
      </div>
      <svg viewBox={`0 0 ${CHART_W} ${SUB_H}`} width="100%" height={SUB_H} style={{ display: 'block' }}>
        <line x1={0} y1={SUB_H} x2={CHART_W} y2={SUB_H} stroke="var(--pixel-border)" strokeWidth={1} />
        {points.length > 0 && (
          <line
            x1={markerX}
            y1={0}
            x2={markerX}
            y2={SUB_H}
            stroke="var(--pixel-amber)"
            strokeWidth={1}
            strokeDasharray="2 2"
          />
        )}
        {scaled.length > 1 && <polyline points={polyline} fill="none" stroke={color} strokeWidth={2} />}
      </svg>
      {latest && (
        <div className="font-data" style={{ fontSize: '0.75rem', color }}>
          at hour {currentHour <= (points.at(-1)?.hour ?? 0) ? currentHour : latest.hour}:{' '}
          {valueOf(points.find((p) => p.hour === currentHour) ?? latest).toFixed(2)} {unit}
        </div>
      )}
    </div>
  )
}

export interface HazardTimeSeriesChartProps {
  nodeStatesByHour: Record<number, Record<string, NodeState>>
  hoursAvailable: number[]
  structureId: string
  currentHour: number
}

export function HazardTimeSeriesChart({
  nodeStatesByHour,
  hoursAvailable,
  structureId,
  currentHour,
}: HazardTimeSeriesChartProps) {
  const points = useMemo(
    () => computeHazardTimeSeries(nodeStatesByHour, hoursAvailable, structureId),
    [nodeStatesByHour, hoursAvailable, structureId],
  )

  if (points.length === 0) {
    return (
      <p className="font-data" style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)' }}>
        No real per-hour node data for this structure yet.
      </p>
    )
  }

  return (
    <div data-testid="hazard-time-series-chart">
      <SubChart
        label="Depth"
        unit="m"
        color="var(--pixel-accent)"
        points={points}
        valueOf={(p) => p.depthM}
        currentHour={currentHour}
      />
      <SubChart
        label="Velocity"
        unit="m/s"
        color="var(--sev-watch)"
        points={points}
        valueOf={(p) => p.velocityMps}
        currentHour={currentHour}
      />
      <SubChart
        label="Rate of rise"
        unit="m/hr"
        color="var(--sev-warning)"
        points={points}
        valueOf={(p) => p.rateOfRise}
        currentHour={currentHour}
      />
    </div>
  )
}

export default HazardTimeSeriesChart
