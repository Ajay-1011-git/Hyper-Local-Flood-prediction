/**
 * Pure terrain geometry maths (T4B.3).
 *
 * Kept separate from `Terrain.tsx` so the real displacement/orientation/
 * nodata logic is unit-testable without mounting React or WebGL. The
 * component is then a thin wrapper: geometry decisions live here.
 */

import * as THREE from 'three'

import type { TerrainHeightmap } from '../api/types'

/** Metres per degree of latitude — the same constant Stage 1B/2/4 use. */
export const METERS_PER_DEGREE_LAT = 111_320

export interface EastNorth {
  east: number
  north: number
}

/**
 * Metres east/north of a reference lat/lon.
 *
 * Flat-earth approximation, consistent with how every other stage in this
 * project converts between degrees and metres over this ~4km site.
 */
export function offsetMeters(
  lat: number,
  lon: number,
  refLat: number,
  refLon: number,
): EastNorth {
  return {
    east: (lon - refLon) * METERS_PER_DEGREE_LAT * Math.cos((refLat * Math.PI) / 180),
    north: (lat - refLat) * METERS_PER_DEGREE_LAT,
  }
}

export interface TerrainSurfaceStats {
  /** Real DEM cells that had no data and were placed at the patch mean. */
  nodataCount: number
}

export interface HeightmapGeometryResult {
  geometry: THREE.PlaneGeometry
  stats: TerrainSurfaceStats
  /** Patch centre in scene metres, for positioning the mesh. */
  centre: EastNorth
}

/**
 * Remove faces fully inside `hole` (a lat/lon rect) from a plane geometry.
 *
 * WHY CUTTING, NOT DEPTH-OFFSETTING
 * ---------------------------------------------------------------
 * The regional and site surfaces overlap, and — now that both are read
 * from the same source pixels — they are very nearly coplanar there. A
 * real render showed the result: heavy z-fighting across the whole site
 * patch, which `polygonOffset` only masks from some angles. Lifting the
 * site by an epsilon would trade it for a (small) real cliff.
 *
 * Cutting the covered regional faces removes the overlap entirely, so
 * there is nothing to fight and nothing to lift. This is only safe
 * because the backend snaps the site extent to regional sample lines
 * (see `read_lod_pair`), so the hole's edge lands exactly on regional
 * vertices and the two meshes meet without a gap.
 *
 * A face is dropped only if ALL of its vertices are strictly inside the
 * hole — the ring of faces straddling the boundary is kept, which is
 * what closes the gap between the two LODs.
 */
function cutHole(
  geometry: THREE.PlaneGeometry,
  cols: number,
  hole: { r0: number; r1: number; c0: number; c1: number },
): void {
  const index = geometry.getIndex()
  if (!index) return

  const inside = (vertexIndex: number): boolean => {
    const r = Math.floor(vertexIndex / cols)
    const c = vertexIndex % cols
    // INCLUSIVE bounds. A strict test was tried first and a real test
    // caught it doing nothing: for a hole only two cells across, no
    // triangle has all three vertices strictly interior, so every face
    // survived and the z-fighting remained. Inclusive drops the covered
    // faces while the straddling faces just outside still reference the
    // boundary vertices -- which is what keeps the two LODs stitched.
    return r >= hole.r0 && r <= hole.r1 && c >= hole.c0 && c <= hole.c1
  }

  const kept: number[] = []
  for (let i = 0; i < index.count; i += 3) {
    const a = index.getX(i)
    const b = index.getX(i + 1)
    const c = index.getX(i + 2)
    if (inside(a) && inside(b) && inside(c)) continue
    kept.push(a, b, c)
  }
  geometry.setIndex(kept)
}

/** Grid-index rect of `hole` within a heightmap, or null if they don't overlap. */
export function holeIndicesFor(
  outer: TerrainHeightmap,
  hole: TerrainHeightmap,
): { r0: number; r1: number; c0: number; c1: number } | null {
  const latSpan = outer.max_lat - outer.min_lat
  const lonSpan = outer.max_lon - outer.min_lon
  if (latSpan <= 0 || lonSpan <= 0) return null

  // Row 0 is the north edge, so max_lat maps to row 0.
  const r0 = ((outer.max_lat - hole.max_lat) / latSpan) * (outer.rows - 1)
  const r1 = ((outer.max_lat - hole.min_lat) / latSpan) * (outer.rows - 1)
  const c0 = ((hole.min_lon - outer.min_lon) / lonSpan) * (outer.cols - 1)
  const c1 = ((hole.max_lon - outer.min_lon) / lonSpan) * (outer.cols - 1)

  const rect = {
    r0: Math.round(r0),
    r1: Math.round(r1),
    c0: Math.round(c0),
    c1: Math.round(c1),
  }
  if (rect.r1 - rect.r0 < 2 || rect.c1 - rect.c0 < 2) return null
  return rect
}

/**
 * Build a `PlaneGeometry` displaced by a real heightmap.
 *
 * The plane is built in the XY plane (three.js's default for
 * `PlaneGeometry`) and displaced along local +Z. `Terrain.tsx` then
 * rotates it -90° about X, which turns local +Z into world +Y (up) and
 * local +Y into world north — so grid row 0 (the north edge, `max_lat`)
 * maps directly to the plane's first row with no flip.
 *
 * Nodata (`null`) vertices are placed at the mean of the patch's REAL
 * cells and counted in `stats.nodataCount`. A mesh cannot carry a hole at
 * a vertex, so something must be chosen; the count is surfaced so the UI
 * discloses it rather than presenting filled cells as measured data.
 */
/**
 * Snap a patch's boundary vertices onto the coarser LOD's straight edges.
 *
 * WHY THIS IS NEEDED (a real crack, seen in a real render)
 * ---------------------------------------------------------------
 * The site patch's corners sample exactly the same source pixels as the
 * regional grid, so they match to 0.000m — verified. But BETWEEN those
 * corners the site has `stitchStep - 1` extra vertices that the regional
 * mesh knows nothing about: the regional simply draws a straight edge
 * from one coarse vertex to the next. Wherever the real terrain curves,
 * the fine edge therefore sits above or below that straight line, and the
 * gap shows as thin dark slivers along the boundary — which is exactly
 * the "visible seam" T4B.3 forbids. (Chasing this as a shadow artifact
 * first ruled that out: removing shadows changed nothing.)
 *
 * Forcing the boundary ring onto the same straight line the coarse mesh
 * draws closes the crack exactly. This is a rendering-only adjustment
 * confined to the outermost ring of the finer patch — interior elevations,
 * which are what any measurement or overlay would read, are untouched.
 * It is the standard LOD edge-stitch, not a fudge factor.
 */
function stitchBoundary(
  position: THREE.BufferAttribute,
  rows: number,
  cols: number,
  stitchStep: number,
): void {
  if (stitchStep < 2) return

  const lerpRun = (
    indexAt: (i: number) => number,
    length: number,
  ): void => {
    for (let start = 0; start + stitchStep < length; start += stitchStep) {
      const end = Math.min(start + stitchStep, length - 1)
      const zStart = position.getZ(indexAt(start))
      const zEnd = position.getZ(indexAt(end))
      for (let k = 1; k < end - start; k += 1) {
        const t = k / (end - start)
        position.setZ(indexAt(start + k), zStart + (zEnd - zStart) * t)
      }
    }
  }

  lerpRun((c) => c, cols) // north edge
  lerpRun((c) => (rows - 1) * cols + c, cols) // south edge
  lerpRun((r) => r * cols, rows) // west edge
  lerpRun((r) => r * cols + (cols - 1), rows) // east edge
}

export function buildHeightmapGeometry(
  heightmap: TerrainHeightmap,
  refLat: number,
  refLon: number,
  hole?: { r0: number; r1: number; c0: number; c1: number } | null,
  stitchStep = 0,
): HeightmapGeometryResult {
  const { rows, cols, elevation_grid, min_lat, max_lat, min_lon, max_lon } = heightmap

  const sw = offsetMeters(min_lat, min_lon, refLat, refLon)
  const ne = offsetMeters(max_lat, max_lon, refLat, refLon)
  const widthM = ne.east - sw.east
  const depthM = ne.north - sw.north

  let sum = 0
  let finite = 0
  for (const row of elevation_grid) {
    for (const v of row) {
      if (v !== null) {
        sum += v
        finite += 1
      }
    }
  }
  const meanElevation = finite > 0 ? sum / finite : 0

  const geometry = new THREE.PlaneGeometry(widthM, depthM, cols - 1, rows - 1)
  const position = geometry.attributes.position as THREE.BufferAttribute
  let nodataCount = 0

  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const raw = elevation_grid[r]?.[c] ?? null
      if (raw === null) nodataCount += 1
      position.setZ(r * cols + c, raw === null ? meanElevation : raw)
    }
  }
  if (stitchStep > 1) stitchBoundary(position, rows, cols, stitchStep)
  position.needsUpdate = true
  if (hole) cutHole(geometry, cols, hole)
  geometry.computeVertexNormals()

  return {
    geometry,
    stats: { nodataCount },
    centre: {
      east: (sw.east + ne.east) / 2,
      north: (sw.north + ne.north) / 2,
    },
  }
}
