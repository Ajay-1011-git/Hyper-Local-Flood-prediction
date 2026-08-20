/**
 * T4B.3 — terrain geometry tests.
 *
 * These test the real displacement/seam maths against real-shaped
 * heightmaps (same field names and value ranges the live Stage 4 endpoint
 * returns for VIT Vellore), not the WebGL render itself — the rendered
 * output is verified separately by a real headless-browser screenshot,
 * per this stage's VERIFY requirement.
 */

import { describe, expect, it } from 'vitest'
import * as THREE from 'three'

import type { TerrainHeightmap } from '../api/types'
import { buildHeightmapGeometry, holeIndicesFor, offsetMeters } from './terrainGeometry'

/** A heightmap shaped exactly like the real endpoint's, with a known ramp. */
function rampHeightmap(overrides: Partial<TerrainHeightmap> = {}): TerrainHeightmap {
  const rows = 3
  const cols = 3
  // Row 0 = north edge. Values rise west->east so we can assert orientation.
  const grid: (number | null)[][] = [
    [100, 110, 120],
    [100, 110, 120],
    [100, 110, 120],
  ]
  return {
    min_lat: 12.968,
    max_lat: 12.97,
    min_lon: 79.154,
    max_lon: 79.156,
    rows,
    cols,
    resolution_m: 30,
    elevation_grid: grid,
    min_elevation_m: 100,
    max_elevation_m: 120,
    nodata_cell_count: 0,
    ...overrides,
  }
}

describe('offsetMeters', () => {
  it('returns zero at the reference point', () => {
    const o = offsetMeters(12.969, 79.155, 12.969, 79.155)
    expect(o.east).toBeCloseTo(0, 6)
    expect(o.north).toBeCloseTo(0, 6)
  })

  it('maps increasing latitude to +north and increasing longitude to +east', () => {
    const o = offsetMeters(12.97, 79.156, 12.969, 79.155)
    expect(o.north).toBeGreaterThan(0)
    expect(o.east).toBeGreaterThan(0)
  })
})

describe('buildHeightmapGeometry', () => {
  it('displaces every vertex to its real elevation', () => {
    const { geometry } = buildHeightmapGeometry(rampHeightmap(), 12.969, 79.155)
    const pos = geometry.attributes.position as THREE.BufferAttribute
    const zs = Array.from({ length: pos.count }, (_, i) => pos.getZ(i))
    // Only the three real elevations appear — nothing invented in between.
    expect(new Set(zs.map((z) => Math.round(z)))).toEqual(new Set([100, 110, 120]))
  })

  it('sizes the plane to the heightmap real-world extent in metres', () => {
    const hm = rampHeightmap()
    const { geometry } = buildHeightmapGeometry(hm, 12.969, 79.155)
    geometry.computeBoundingBox()
    const box = geometry.boundingBox!
    const sw = offsetMeters(hm.min_lat, hm.min_lon, 12.969, 79.155)
    const ne = offsetMeters(hm.max_lat, hm.max_lon, 12.969, 79.155)
    expect(box.max.x - box.min.x).toBeCloseTo(ne.east - sw.east, 3)
    expect(box.max.y - box.min.y).toBeCloseTo(ne.north - sw.north, 3)
  })

  it('places nodata vertices at the mean of REAL cells and counts them', () => {
    const hm = rampHeightmap({
      elevation_grid: [
        [100, null, 120],
        [100, 110, 120],
        [100, 110, 120],
      ],
      nodata_cell_count: 1,
    })
    const { geometry, stats } = buildHeightmapGeometry(hm, 12.969, 79.155)
    expect(stats.nodataCount).toBe(1)

    const realValues = [100, 120, 100, 110, 120, 100, 110, 120]
    const mean = realValues.reduce((a, b) => a + b, 0) / realValues.length
    const pos = geometry.attributes.position as THREE.BufferAttribute
    // The null sits at row 0, col 1 -> vertex index 1.
    expect(pos.getZ(1)).toBeCloseTo(mean, 6)
  })

  it('produces coincident edge elevations for two windows sharing a boundary', () => {
    // The real seamlessness guarantee: both patches are windows on ONE
    // raster, so a shared edge carries identical elevations. Here the
    // "site" patch reuses the regional patch's eastern column.
    const regional = rampHeightmap()
    const site = rampHeightmap({
      min_lon: 79.156,
      max_lon: 79.158,
      elevation_grid: [
        [120, 130, 140],
        [120, 130, 140],
        [120, 130, 140],
      ],
      min_elevation_m: 120,
      max_elevation_m: 140,
    })

    const a = buildHeightmapGeometry(regional, 12.969, 79.155)
    const b = buildHeightmapGeometry(site, 12.969, 79.155)
    const posA = a.geometry.attributes.position as THREE.BufferAttribute
    const posB = b.geometry.attributes.position as THREE.BufferAttribute

    // Regional's east column (index 2 of each row) vs site's west column (index 0).
    for (let r = 0; r < 3; r += 1) {
      expect(posA.getZ(r * 3 + 2)).toBeCloseTo(posB.getZ(r * 3 + 0), 6)
    }
  })
})

describe('LOD hole cutting', () => {
  /** A coarse 7x7 outer patch and a finer patch covering its middle. */
  const outer = rampHeightmap({
    rows: 7,
    cols: 7,
    elevation_grid: Array.from({ length: 7 }, () => Array(7).fill(100)),
    min_lat: 12.96,
    max_lat: 12.978,
    min_lon: 79.15,
    max_lon: 79.168,
  })
  const inner = rampHeightmap({
    rows: 3,
    cols: 3,
    elevation_grid: Array.from({ length: 3 }, () => Array(3).fill(100)),
    min_lat: 12.966,
    max_lat: 12.972,
    min_lon: 79.156,
    max_lon: 79.162,
  })

  it('locates the inner patch inside the outer grid', () => {
    const hole = holeIndicesFor(outer, inner)
    expect(hole).not.toBeNull()
    expect(hole!.r1).toBeGreaterThan(hole!.r0)
    expect(hole!.c1).toBeGreaterThan(hole!.c0)
  })

  it('removes covered faces so the two LODs cannot z-fight', () => {
    const hole = holeIndicesFor(outer, inner)!
    const without = buildHeightmapGeometry(outer, 12.969, 79.159)
    const withHole = buildHeightmapGeometry(outer, 12.969, 79.159, hole)
    expect(withHole.geometry.getIndex()!.count).toBeLessThan(
      without.geometry.getIndex()!.count,
    )
  })

  it('keeps the boundary ring, so no gap opens between the LODs', () => {
    const hole = holeIndicesFor(outer, inner)!
    const { geometry } = buildHeightmapGeometry(outer, 12.969, 79.159, hole)
    const index = geometry.getIndex()!
    // Every vertex ON the hole boundary must still be referenced by some
    // surviving face -- otherwise the outer mesh would pull away from the
    // inner patch and leave a visible gap.
    const referenced = new Set<number>()
    for (let i = 0; i < index.count; i += 1) referenced.add(index.getX(i))
    for (let c = hole.c0; c <= hole.c1; c += 1) {
      expect(referenced.has(hole.r0 * outer.cols + c)).toBe(true)
      expect(referenced.has(hole.r1 * outer.cols + c)).toBe(true)
    }
  })

  it('returns null when the patches barely overlap, leaving the mesh intact', () => {
    const tiny = rampHeightmap({
      min_lat: 12.9779,
      max_lat: 12.978,
      min_lon: 79.1679,
      max_lon: 79.168,
    })
    expect(holeIndicesFor(outer, tiny)).toBeNull()
  })
})

describe('LOD boundary stitching', () => {
  /**
   * A 7x7 patch whose edges CURVE, so an unstitched boundary would bow
   * away from the coarse mesh's straight edge — the real crack this
   * fixes. stitchStep 3 means every 3rd boundary vertex is shared with
   * the coarse LOD and the two between it must lie on that straight line.
   */
  const curved = rampHeightmap({
    rows: 7,
    cols: 7,
    elevation_grid: Array.from({ length: 7 }, (_, r) =>
      Array.from({ length: 7 }, (_, c) => 100 + Math.sin(c) * 5 + Math.sin(r) * 5),
    ),
  })

  it('places between-vertices exactly on the coarse straight edge', () => {
    const { geometry } = buildHeightmapGeometry(curved, 12.969, 79.155, null, 3)
    const pos = geometry.attributes.position as THREE.BufferAttribute
    // North edge, first coarse span: vertices 0 and 3 are shared with the
    // coarse LOD; 1 and 2 must be their linear interpolation.
    const z0 = pos.getZ(0)
    const z3 = pos.getZ(3)
    expect(pos.getZ(1)).toBeCloseTo(z0 + (z3 - z0) / 3, 6)
    expect(pos.getZ(2)).toBeCloseTo(z0 + ((z3 - z0) * 2) / 3, 6)
  })

  it('leaves interior elevations untouched — only the boundary ring moves', () => {
    const plain = buildHeightmapGeometry(curved, 12.969, 79.155)
    const stitched = buildHeightmapGeometry(curved, 12.969, 79.155, null, 3)
    const a = plain.geometry.attributes.position as THREE.BufferAttribute
    const b = stitched.geometry.attributes.position as THREE.BufferAttribute
    for (let r = 1; r < 6; r += 1) {
      for (let c = 1; c < 6; c += 1) {
        expect(b.getZ(r * 7 + c)).toBe(a.getZ(r * 7 + c))
      }
    }
  })

  it('is a no-op when the two LODs have the same resolution', () => {
    const plain = buildHeightmapGeometry(curved, 12.969, 79.155)
    const same = buildHeightmapGeometry(curved, 12.969, 79.155, null, 1)
    const a = plain.geometry.attributes.position as THREE.BufferAttribute
    const b = same.geometry.attributes.position as THREE.BufferAttribute
    for (let i = 0; i < a.count; i += 1) expect(b.getZ(i)).toBe(a.getZ(i))
  })
})
