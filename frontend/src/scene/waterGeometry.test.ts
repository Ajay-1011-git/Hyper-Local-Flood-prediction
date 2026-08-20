import { describe, expect, it } from 'vitest'
import * as THREE from 'three'

import type { NodeState, SiteMeshNodesResponse } from '../api/types'
import { applyDepths, applyField, buildWaterGrid, parseNodeId } from './waterGeometry'

function makeNodeState(overrides: Partial<NodeState> = {}): NodeState {
  return {
    node_id: 'n_0_0',
    hour: 24,
    depth_mean_m: 0.5,
    depth_min_m: 0.3,
    depth_max_m: 0.7,
    velocity_mean_mps: 0.2,
    velocity_min_mps: 0.1,
    velocity_max_mps: 0.3,
    rate_of_rise: 0.01,
    ensemble_agreement_fraction: 0.9,
    building_id: null,
    road_segment_id: null,
    ...overrides,
  }
}

const mesh: SiteMeshNodesResponse = {
  site_id: 'test-site',
  rows: 2,
  cols: 3,
  resolution_m: 1,
  nodes: [
    { node_id: 'n_0_0', x_m: 0, z_m: 0, elevation_m: 100 },
    { node_id: 'n_0_1', x_m: 1, z_m: 0, elevation_m: 101 },
    { node_id: 'n_0_2', x_m: 2, z_m: 0, elevation_m: 102 },
    { node_id: 'n_1_0', x_m: 0, z_m: 1, elevation_m: 110 },
    { node_id: 'n_1_1', x_m: 1, z_m: 1, elevation_m: 111 },
    { node_id: 'n_1_2', x_m: 2, z_m: 1, elevation_m: 112 },
  ],
}

describe('parseNodeId', () => {
  it('parses the real row/col scheme', () => {
    expect(parseNodeId('n_12_345')).toEqual({ row: 12, col: 345 })
  })

  it('returns null for anything not matching the real scheme', () => {
    expect(parseNodeId('Building_01')).toBeNull()
    expect(parseNodeId('n_1')).toBeNull()
    expect(parseNodeId('')).toBeNull()
  })
})

describe('buildWaterGrid', () => {
  it('places every vertex at its real (x_m, elevation_m, z_m)', () => {
    const grid = buildWaterGrid(mesh)
    const position = grid.geometry.getAttribute('position') as THREE.BufferAttribute
    // n_1_2 -> index 1*3+2 = 5
    expect(position.getX(5)).toBe(2)
    expect(position.getY(5)).toBe(112)
    expect(position.getZ(5)).toBe(1)
  })

  it('indexes nodeIdByVertex in row-major order matching node_id', () => {
    const grid = buildWaterGrid(mesh)
    expect(grid.nodeIdByVertex[0]).toBe('n_0_0')
    expect(grid.nodeIdByVertex[4]).toBe('n_1_1')
  })

  it('builds a triangulated grid with (rows-1)*(cols-1)*2 triangles', () => {
    const grid = buildWaterGrid(mesh)
    const index = grid.geometry.getIndex()
    expect(index).not.toBeNull()
    expect(index!.count).toBe((mesh.rows - 1) * (mesh.cols - 1) * 2 * 3)
  })
})

describe('applyDepths', () => {
  it('raises a vertex by exactly its real depth_mean_m above base elevation', () => {
    const grid = buildWaterGrid(mesh)
    const position = grid.geometry.getAttribute('position') as THREE.BufferAttribute
    const nodeStates = { n_0_0: makeNodeState({ node_id: 'n_0_0', depth_mean_m: 0.42 }) }

    applyDepths(position, grid.nodeIdByVertex, grid.baseElevationByVertex, nodeStates)

    // Float32-precision tolerance -- the position attribute is backed by
    // a Float32Array, so an exact double-precision match isn't real here.
    expect(position.getY(0)).toBeCloseTo(100 + 0.42, 5)
  })

  it('leaves a vertex at its dry base elevation when no real state covers it', () => {
    const grid = buildWaterGrid(mesh)
    const position = grid.geometry.getAttribute('position') as THREE.BufferAttribute

    applyDepths(position, grid.nodeIdByVertex, grid.baseElevationByVertex, {})

    expect(position.getY(0)).toBe(100)
    expect(position.getY(5)).toBe(112)
  })

  it('floors a negative depth at zero rather than sinking below dry elevation', () => {
    const grid = buildWaterGrid(mesh)
    const position = grid.geometry.getAttribute('position') as THREE.BufferAttribute
    const nodeStates = { n_0_0: makeNodeState({ node_id: 'n_0_0', depth_mean_m: -0.2 }) }

    applyDepths(position, grid.nodeIdByVertex, grid.baseElevationByVertex, nodeStates)

    expect(position.getY(0)).toBe(100)
  })

  it('returns the real count of genuinely wet vertices', () => {
    const grid = buildWaterGrid(mesh)
    const position = grid.geometry.getAttribute('position') as THREE.BufferAttribute
    const nodeStates = {
      n_0_0: makeNodeState({ node_id: 'n_0_0', depth_mean_m: 0.1 }),
      n_1_1: makeNodeState({ node_id: 'n_1_1', depth_mean_m: 0 }),
      n_1_2: makeNodeState({ node_id: 'n_1_2', depth_mean_m: 0.3 }),
    }

    const wetCount = applyDepths(position, grid.nodeIdByVertex, grid.baseElevationByVertex, nodeStates)

    expect(wetCount).toBe(2)
  })
})

describe('applyField', () => {
  it('drives displacement off whichever real field the selector names (T4B.6)', () => {
    const grid = buildWaterGrid(mesh)
    const lowerPos = grid.geometry.getAttribute('position') as THREE.BufferAttribute
    const nodeStates = {
      n_0_0: makeNodeState({ node_id: 'n_0_0', depth_min_m: 0.1, depth_max_m: 0.9 }),
    }

    applyField(lowerPos, grid.nodeIdByVertex, grid.baseElevationByVertex, nodeStates, (s) => s.depth_min_m)
    expect(lowerPos.getY(0)).toBeCloseTo(100 + 0.1, 5)

    const upperGrid = buildWaterGrid(mesh)
    const upperPos = upperGrid.geometry.getAttribute('position') as THREE.BufferAttribute
    applyField(upperPos, upperGrid.nodeIdByVertex, upperGrid.baseElevationByVertex, nodeStates, (s) => s.depth_max_m)
    expect(upperPos.getY(0)).toBeCloseTo(100 + 0.9, 5)
  })

  it('applyDepths is applyField specialised to depth_mean_m', () => {
    const gridA = buildWaterGrid(mesh)
    const gridB = buildWaterGrid(mesh)
    const posA = gridA.geometry.getAttribute('position') as THREE.BufferAttribute
    const posB = gridB.geometry.getAttribute('position') as THREE.BufferAttribute
    const nodeStates = { n_0_0: makeNodeState({ node_id: 'n_0_0', depth_mean_m: 0.55 }) }

    applyDepths(posA, gridA.nodeIdByVertex, gridA.baseElevationByVertex, nodeStates)
    applyField(posB, gridB.nodeIdByVertex, gridB.baseElevationByVertex, nodeStates, (s) => s.depth_mean_m)

    expect(posA.getY(0)).toBeCloseTo(posB.getY(0), 6)
  })
})
