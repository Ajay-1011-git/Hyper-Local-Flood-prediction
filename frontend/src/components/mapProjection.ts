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
  /** Real ground metres one SVG unit covers — lets the caller draw a
   *  truthful scale bar instead of an unlabelled shape. */
  metresPerUnit: number
}

const METRES_PER_DEGREE_LAT = 111_320

/**
 * Fits `polygon` into a `width`x`height` viewBox, north-up (higher
 * latitude draws higher on screen). Returns `null` for a real empty
 * polygon rather than projecting against a meaningless 0-span box.
 *
 * TWO REAL FIXES OVER THE ORIGINAL STRETCH-TO-FIT VERSION
 * ---------------------------------------------------------------
 * 1. ONE shared metres-per-unit scale for both axes, with longitude
 *    degrees converted at `cos(lat)`. The original scaled latitude and
 *    longitude spans independently, which stretched the real shape to
 *    the viewBox's aspect ratio — a ~230m x 130m site drew as a square.
 * 2. `fitFraction` leaves real margin around the shaded area. The
 *    original filled the box edge-to-edge, so this project's own
 *    `area_polygon` (a rectangle — Stage 4 sends the site bounding box)
 *    rendered as a solid block of colour with no visible surroundings,
 *    reading as an empty coloured box rather than a map. The area has to
 *    sit INSIDE something to read as an area.
 */
export function buildMapProjection(
  polygon: number[][],
  width: number,
  height: number,
  padding = 8,
  fitFraction = 0.55,
): MapProjection | null {
  if (polygon.length === 0) return null

  const lats = polygon.map((p) => p[0])
  const lons = polygon.map((p) => p[1])
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  const midLat = (minLat + maxLat) / 2
  const midLon = (minLon + maxLon) / 2

  const metresPerDegreeLon = METRES_PER_DEGREE_LAT * Math.cos((midLat * Math.PI) / 180)
  // `|| 1` keeps a degenerate single-point polygon finite (it has no
  // real extent to fit, so any non-zero span works).
  const spanXm = (maxLon - minLon) * metresPerDegreeLon || 1
  const spanYm = (maxLat - minLat) * METRES_PER_DEGREE_LAT || 1

  const innerW = Math.max(width - 2 * padding, 1)
  const innerH = Math.max(height - 2 * padding, 1)
  // Units per metre — the SMALLER of the two axes' fits, so the real
  // shape always fits and neither axis is stretched.
  const unitsPerMetre = Math.min((innerW * fitFraction) / spanXm, (innerH * fitFraction) / spanYm)

  return {
    metresPerUnit: 1 / unitsPerMetre,
    project: (lat, lon) => ({
      x: width / 2 + (lon - midLon) * metresPerDegreeLon * unitsPerMetre,
      y: height / 2 - (lat - midLat) * METRES_PER_DEGREE_LAT * unitsPerMetre,
    }),
  }
}

export function polygonToSvgPoints(projection: MapProjection, polygon: number[][]): string {
  return polygon.map(([lat, lon]) => {
    const { x, y } = projection.project(lat, lon)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}
