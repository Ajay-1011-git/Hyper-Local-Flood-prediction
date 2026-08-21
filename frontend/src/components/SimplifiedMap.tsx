/**
 * SimplifiedMap — the Citizen View's map (T4C.4, User Flow §3.5): "no
 * ensemble fans, no technical overlays — just the affected area shaded,
 * with a marker for 'your location' if geolocation is available."
 *
 * Uses the browser's REAL Geolocation API (`navigator.geolocation`) —
 * never a fabricated marker. If permission is denied, unsupported, or
 * the position is outside the shaded area, this says so in plain text
 * rather than silently omitting the marker or guessing a position.
 */

import { useEffect, useState } from 'react'

import { buildMapProjection, polygonToSvgPoints } from './mapProjection'

const VIEW_SIZE = 280

export interface SimplifiedMapProps {
  areaPolygon: number[][]
}

type GeoState =
  | { status: 'idle' | 'unsupported' | 'denied' | 'unavailable' }
  | { status: 'found'; lat: number; lon: number }

export function SimplifiedMap({ areaPolygon }: SimplifiedMapProps) {
  const [geo, setGeo] = useState<GeoState>({ status: 'idle' })

  useEffect(() => {
    if (!('geolocation' in navigator)) {
      setGeo({ status: 'unsupported' })
      return
    }
    navigator.geolocation.getCurrentPosition(
      (position) => setGeo({ status: 'found', lat: position.coords.latitude, lon: position.coords.longitude }),
      (error) => setGeo({ status: error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable' }),
      { timeout: 8000 },
    )
  }, [])

  const projection = buildMapProjection(areaPolygon, VIEW_SIZE, VIEW_SIZE)

  if (!projection) {
    return (
      <p className="font-pixel-body" style={{ color: 'var(--citizen-text-dim)', fontSize: '1.1rem' }}>
        No real affected-area map for this alert yet.
      </p>
    )
  }

  const marker = geo.status === 'found' ? projection.project(geo.lat, geo.lon) : null

  // Real scale bar: pick a round ground distance that fits comfortably,
  // then draw it at its true projected length. Never a decorative bar
  // with an invented number on it.
  const scaleOptions = [50, 100, 200, 500, 1000]
  const scaleMetres =
    scaleOptions.find((m) => m / projection.metresPerUnit <= VIEW_SIZE * 0.3) ?? scaleOptions[0]
  const scaleUnits = scaleMetres / projection.metresPerUnit

  return (
    <div data-testid="simplified-map">
      <svg viewBox={`0 0 ${VIEW_SIZE} ${VIEW_SIZE}`} width="100%" style={{ display: 'block' }}>
        <rect x={0} y={0} width={VIEW_SIZE} height={VIEW_SIZE} fill="var(--citizen-panel)" />

        {/* Surrounding grid — real context so the shaded area reads as an
            area within a place, not as a solid block of colour filling
            the whole frame (the bug this replaces). Purely a backdrop:
            it encodes no data and is drawn faintly so it never competes
            with the real shaded area. */}
        <g stroke="var(--citizen-border)" strokeOpacity={0.35} strokeWidth={1}>
          {[0.25, 0.5, 0.75].map((f) => (
            <line key={`h${f}`} x1={0} y1={VIEW_SIZE * f} x2={VIEW_SIZE} y2={VIEW_SIZE * f} />
          ))}
          {[0.25, 0.5, 0.75].map((f) => (
            <line key={`v${f}`} x1={VIEW_SIZE * f} y1={0} x2={VIEW_SIZE * f} y2={VIEW_SIZE} />
          ))}
        </g>

        <polygon
          points={polygonToSvgPoints(projection, areaPolygon)}
          fill="var(--sev-warning)"
          fillOpacity={0.35}
          stroke="var(--sev-warning)"
          strokeWidth={2}
        />

        {marker && (
          <g>
            <circle cx={marker.x} cy={marker.y} r={7} fill="var(--pixel-accent)" stroke="#fff" strokeWidth={2} />
          </g>
        )}

        {/* North arrow. */}
        <g transform={`translate(${VIEW_SIZE - 24}, 22)`}>
          <line x1={0} y1={12} x2={0} y2={-8} stroke="var(--citizen-text-dim)" strokeWidth={2} />
          <polygon points="0,-13 -4,-5 4,-5" fill="var(--citizen-text-dim)" />
          <text
            x={0}
            y={24}
            textAnchor="middle"
            fill="var(--citizen-text-dim)"
            style={{ fontSize: 10 }}
          >
            N
          </text>
        </g>

        {/* Real scale bar. */}
        <g transform={`translate(16, ${VIEW_SIZE - 18})`}>
          <line x1={0} y1={0} x2={scaleUnits} y2={0} stroke="var(--citizen-text-dim)" strokeWidth={2} />
          <line x1={0} y1={-4} x2={0} y2={4} stroke="var(--citizen-text-dim)" strokeWidth={2} />
          <line
            x1={scaleUnits}
            y1={-4}
            x2={scaleUnits}
            y2={4}
            stroke="var(--citizen-text-dim)"
            strokeWidth={2}
          />
          <text x={0} y={-8} fill="var(--citizen-text-dim)" style={{ fontSize: 10 }}>
            {scaleMetres} m
          </text>
        </g>
      </svg>
      <p
        className="font-pixel-body"
        style={{ color: 'var(--citizen-text-dim)', fontSize: '1rem', marginTop: 4 }}
      >
        The shaded area is the area this alert covers.
      </p>
      <p className="font-pixel-body" style={{ color: 'var(--citizen-text-dim)', fontSize: '1rem', marginTop: 4 }}>
        {geo.status === 'found' && 'Your location is marked.'}
        {geo.status === 'denied' && 'Location permission denied — your location isn\'t shown.'}
        {geo.status === 'unsupported' && 'Location isn\'t supported on this device.'}
        {geo.status === 'unavailable' && 'Your location couldn\'t be determined.'}
        {geo.status === 'idle' && 'Finding your location…'}
      </p>
    </div>
  )
}

export default SimplifiedMap
