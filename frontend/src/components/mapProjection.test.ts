import { describe, expect, it } from 'vitest'

import { buildMapProjection, polygonToSvgPoints } from './mapProjection'

describe('buildMapProjection', () => {
  it('returns null for a real empty polygon rather than a meaningless projection', () => {
    expect(buildMapProjection([], 200, 100)).toBeNull()
  })

  it('projects north-up: higher latitude draws higher on screen (smaller y)', () => {
    const projection = buildMapProjection(
      [
        [12.96, 79.15],
        [12.97, 79.16],
      ],
      100,
      100,
      0,
    )!
    const south = projection.project(12.96, 79.15)
    const north = projection.project(12.97, 79.15)
    expect(north.y).toBeLessThan(south.y)
  })

  it('projects east as larger x', () => {
    const projection = buildMapProjection(
      [
        [12.96, 79.15],
        [12.97, 79.16],
      ],
      100,
      100,
      0,
    )!
    const west = projection.project(12.96, 79.15)
    const east = projection.project(12.96, 79.16)
    expect(east.x).toBeGreaterThan(west.x)
  })

  it('never divides by zero for a degenerate (single-point) polygon', () => {
    const projection = buildMapProjection([[12.96, 79.15]], 100, 100)!
    const point = projection.project(12.96, 79.15)
    expect(Number.isFinite(point.x)).toBe(true)
    expect(Number.isFinite(point.y)).toBe(true)
  })
})

describe('polygonToSvgPoints', () => {
  it('formats every real polygon point as an SVG points string', () => {
    const polygon = [
      [12.96, 79.15],
      [12.97, 79.16],
    ]
    const projection = buildMapProjection(polygon, 100, 100, 0)!
    const points = polygonToSvgPoints(projection, polygon)
    expect(points.split(' ')).toHaveLength(2)
  })
})
