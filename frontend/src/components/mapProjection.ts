/**
 * Pure map-projection maths for the Citizen View's simplified map
 * (T4C.4, User Flow §3.5): "no ensemble fans, no technical overlays —
 * just the affected area shaded, with a marker for 'your location' if
 * geolocation is available."
 *
 * A plain equirectangular fit of the real `Alert.area_polygon`
 * (`[[lat, lon], ...]`) into an SVG viewBox — deliberately the simplest
 * real projection (no basemap tiles, no external map service — this
 * view has zero network dependencies beyond the real Alert fetch
 * itself), matching the doc's own "simplified" requirement.
 */

export interface ProjectedPoint {
  x: number
  y: number
}

export interface MapProjection {
  project: (lat: number, lon: number) => ProjectedPoint
}

/**
 * Fits `polygon`'s real bounding box into a `width`x`height` viewBox
 * (with `padding` on every side), north-up (higher latitude draws
 * higher on screen). Returns `null` for a real empty polygon rather
 * than projecting against a meaningless 0-span box.
 */
export function buildMapProjection(
  polygon: number[][],
  width: number,
  height: number,
  padding = 8,
): MapProjection | null {
  if (polygon.length === 0) return null

  const lats = polygon.map((p) => p[0])
  const lons = polygon.map((p) => p[1])
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  const latSpan = maxLat - minLat || 1
  const lonSpan = maxLon - minLon || 1
  const innerW = Math.max(width - 2 * padding, 1)
  const innerH = Math.max(height - 2 * padding, 1)

  return {
    project: (lat, lon) => ({
      x: padding + ((lon - minLon) / lonSpan) * innerW,
      y: padding + (1 - (lat - minLat) / latSpan) * innerH,
    }),
  }
}

export function polygonToSvgPoints(projection: MapProjection, polygon: number[][]): string {
  return polygon.map(([lat, lon]) => {
    const { x, y } = projection.project(lat, lon)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}
