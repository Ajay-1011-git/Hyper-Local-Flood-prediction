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

  return (
    <div data-testid="simplified-map">
      <svg viewBox={`0 0 ${VIEW_SIZE} ${VIEW_SIZE}`} width="100%" style={{ display: 'block' }}>
        <rect x={0} y={0} width={VIEW_SIZE} height={VIEW_SIZE} fill="var(--citizen-panel)" />
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
      </svg>
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
