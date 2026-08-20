/**
 * EnsembleFanChart — the regional-ensemble fan chart (T4C.1, User Flow
 * §3.2's "Regional ensemble card"): "GenCast's 50+ member rainfall
 * trajectories ... rendered as translucent overlapping lines that
 * visually thicken where members agree and fan out where they diverge."
 *
 * REAL SOURCE, REAL MEMBER COUNT — NEVER PRESENTED AMBIGUOUSLY
 * ---------------------------------------------------------------
 * GenCast was removed from this project entirely (Stage 1A's own
 * CLAUDE.md addendum, 2026-08-20) — the real source chain is GEFS
 * (primary, 31 members, 0.25°) -> WeatherNext 2 Cyclones Mini (fallback,
 * 8 members, 1.0°). `forecast.source` and `forecast.members.length` are
 * REAL and DIFFER by which one actually answered — this component always
 * labels which one is live, per the honesty principle Stage 1A's
 * amendment establishes. Never says "50+ members" as the doc's own
 * (GenCast-era) prose does; that count doesn't exist in this build.
 *
 * Translucent overlapping SVG polylines (one per real member, low
 * opacity — density IS the "members agree" visual, not a fabricated
 * heat-map) plus one solid brighter line for the real per-hour mean.
 * Per dataviz convention: single conceptual series (rainfall), so no
 * legend box is needed — the two direct labels ("members" via the fan
 * itself, "mean" on its own line) carry identity. A crosshair + tooltip
 * on hover, per the same convention's interaction rule.
 */

import { useMemo, useState } from 'react'

import type { RegionalEnsembleForecast } from '../api/types'
import { forecastSourceLabel } from '../forecastSources'
import {
  computeExceedanceReadout,
  computeFanChartGeometry,
  pointsToPolyline,
} from './fanChartGeometry'

const VIEW_W = 280
const VIEW_H = 130
const PAD_LEFT = 28
const PAD_BOTTOM = 16
const PLOT_W = VIEW_W - PAD_LEFT
const PLOT_H = VIEW_H - PAD_BOTTOM

export interface EnsembleFanChartProps {
  forecast: RegionalEnsembleForecast
}

export function EnsembleFanChart({ forecast }: EnsembleFanChartProps) {
  const geometry = useMemo(() => computeFanChartGeometry(forecast, PLOT_W, PLOT_H), [forecast])
  const readout = useMemo(() => computeExceedanceReadout(forecast), [forecast])
  const [hoverHourIndex, setHoverHourIndex] = useState<number | null>(null)

  if (!geometry) {
    return (
      <p className="font-pixel-body" style={{ color: 'var(--ops-text-dim)', fontSize: '1.1rem' }}>
        No real ensemble trajectory to chart.
      </p>
    )
  }

  const sourceLabel = forecastSourceLabel(forecast.source)

  const handleMove = (event: React.MouseEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const relativeX = event.clientX - rect.left
    const fraction = Math.min(1, Math.max(0, relativeX / rect.width))
    const index = Math.round(fraction * (geometry.hours.length - 1))
    setHoverHourIndex(index)
  }

  const hovered = hoverHourIndex !== null ? geometry.meanLine[hoverHourIndex] : null
  const hoveredHour = hoverHourIndex !== null ? geometry.hours[hoverHourIndex] : null

  return (
    <div>
      <div
        className="font-pixel-body"
        style={{ fontSize: '1rem', color: 'var(--pixel-amber)', marginBottom: 4 }}
        data-testid="fan-chart-source"
      >
        Source: {sourceLabel} — {geometry.memberCount} member{geometry.memberCount === 1 ? '' : 's'}
      </div>

      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        width="100%"
        style={{ display: 'block', overflow: 'visible' }}
        role="img"
        aria-label={`Rainfall ensemble fan chart, ${sourceLabel}, ${geometry.memberCount} members`}
      >
        <g transform={`translate(${PAD_LEFT}, 0)`}>
          {/* Baseline + a mid gridline -- recessive, per dataviz convention. */}
          <line x1={0} y1={PLOT_H} x2={PLOT_W} y2={PLOT_H} stroke="var(--pixel-border)" strokeWidth={1} />
          <line
            x1={0}
            y1={PLOT_H / 2}
            x2={PLOT_W}
            y2={PLOT_H / 2}
            stroke="var(--pixel-border)"
            strokeWidth={1}
            strokeDasharray="2 3"
            opacity={0.6}
          />

          {/* Real per-member trajectories -- translucent; overlap density
              IS the "members agree" signal, not a synthesized band. */}
          {geometry.memberLines.map((line, i) => (
            <polyline
              key={i}
              points={pointsToPolyline(line)}
              fill="none"
              stroke="var(--pixel-accent)"
              strokeWidth={1}
              opacity={0.16}
            />
          ))}

          {/* Real per-hour mean -- the "most likely" line, solid + bright. */}
          <polyline
            points={pointsToPolyline(geometry.meanLine)}
            fill="none"
            stroke="var(--pixel-glow)"
            strokeWidth={2}
          />
          <text
            x={geometry.meanLine.at(-1)?.x ?? 0}
            y={(geometry.meanLine.at(-1)?.y ?? 0) - 4}
            textAnchor="end"
            className="font-data"
            fontSize={9}
            fill="var(--pixel-glow)"
          >
            mean
          </text>

          {/* Hover crosshair + tooltip. */}
          {hovered && (
            <>
              <line
                x1={hovered.x}
                y1={0}
                x2={hovered.x}
                y2={PLOT_H}
                stroke="var(--pixel-glow)"
                strokeWidth={1}
                opacity={0.5}
              />
              <circle cx={hovered.x} cy={hovered.y} r={3} fill="var(--pixel-glow)" />
            </>
          )}

          {/* Invisible hit-area for hover, sized larger than the plot per
              the dataviz convention (hit targets bigger than the mark). */}
          <rect
            x={0}
            y={0}
            width={PLOT_W}
            height={PLOT_H}
            fill="transparent"
            onMouseMove={handleMove}
            onMouseLeave={() => setHoverHourIndex(null)}
          />
        </g>
      </svg>

      <div
        className="font-data"
        style={{ fontSize: '0.75rem', color: 'var(--ops-text-dim)', display: 'flex', justifyContent: 'space-between' }}
      >
        <span>0h</span>
        <span>{Math.round((geometry.hours.at(-1) ?? 0) / 2)}h</span>
        <span>{geometry.hours.at(-1) ?? 0}h</span>
      </div>

      {hovered && hoveredHour !== null && (
        <div
          data-testid="fan-chart-tooltip"
          className="font-data"
          style={{ fontSize: '0.85rem', color: 'var(--pixel-glow)', marginTop: 2 }}
        >
          hour {hoveredHour}: mean {(((PLOT_H - hovered.y) / PLOT_H) * geometry.maxValue).toFixed(2)} mm
        </div>
      )}

      {readout && (
        <p
          className="font-data"
          data-testid="fan-chart-readout"
          style={{ fontSize: '0.8rem', color: 'var(--ops-text-dim)', marginTop: 6 }}
        >
          {readout.exceedingCount} of {readout.totalCount} scenarios at/above the ensemble's own
          90th-percentile cumulative rainfall ({readout.thresholdMm.toFixed(1)} mm) over the{' '}
          {readout.atHour}h window.
        </p>
      )}
    </div>
  )
}

export default EnsembleFanChart
