/**
 * Pure water-surface geometry maths (T4B.5).
 *
 * Split out from `WaterSurface.tsx` for the same reason `terrainGeometry.ts`
 * is split from `Terrain.tsx`: the real displacement logic is unit-testable
 * without mounting React or WebGL.
 *
 * ZERO PHYSICS HERE — per Stage 4's Operating Contract, this module only
 * places vertices at REAL backend values (`MeshNodePosition.elevation_m`
 * from Stage 4's `/api/mesh-nodes` proxy, `NodeState.depth_mean_m` from
 * Stage 2's real simulation) and never computes/derives a depth of its
 * own. A node with no real `NodeState` for the current hour is treated as
 * genuinely unknown/dry (displacement 0), never interpolated or guessed.
 */

import * as THREE from 'three'

import type { MeshNodePosition, NodeState, SiteMeshNodesResponse } from '../api/types'

const NODE_ID_PATTERN = /^n_(\d+)_(\d+)$/

/** `"n_{row}_{col}"` -> `{ row, col }`, or `null` if it doesn't match the
 *  real scheme `stage2/mesh/computational_mesh.py` generates. */
export function parseNodeId(nodeId: string): { row: number; col: number } | null {
  const match = NODE_ID_PATTERN.exec(nodeId)
  if (!match) return null
  return { row: Number(match[1]), col: Number(match[2]) }
}

export interface WaterGrid {
  geometry: THREE.BufferGeometry
  /** `nodeIdByVertex[row * cols + col]` — parallel to the geometry's
   *  `position` attribute, so a store lookup by real `node_id` maps
   *  directly to a vertex index. Empty string where no real
   *  `MeshNodePosition` covers that grid cell (should not happen for a
   *  real, complete response, but never assumed). */
  nodeIdByVertex: string[]
  /** Real elevation_m per vertex — the "dry" resting height a vertex
   *  returns to when its node has no real depth for the current hour. */
  baseElevationByVertex: Float32Array
  rows: number
  cols: number
}

/**
 * Build the water mesh's base geometry from Stage 4's real mesh-node
 * positions — one vertex per `ComputationalMeshNode`, connected into the
 * SAME regular row/col grid Stage 2's real mesh is (confirmed: `node_id`
 * IS the grid's own row/col addressing).
 *
 * Vertices start at each node's real dry elevation (zero depth) — actual
 * depth is applied per-frame by `applyDepths`, never here.
 */
export function buildWaterGrid(mesh: SiteMeshNodesResponse): WaterGrid {
  const { rows, cols, nodes } = mesh
  const count = rows * cols
  const positions = new Float32Array(count * 3)
  const nodeIdByVertex: string[] = new Array(count).fill('')
  const baseElevationByVertex = new Float32Array(count)

  for (const node of nodes as MeshNodePosition[]) {
    const parsed = parseNodeId(node.node_id)
    if (!parsed) continue
    const idx = parsed.row * cols + parsed.col
    if (idx < 0 || idx >= count) continue
    positions[idx * 3 + 0] = node.x_m
    positions[idx * 3 + 1] = node.elevation_m
    positions[idx * 3 + 2] = node.z_m
    nodeIdByVertex[idx] = node.node_id
    baseElevationByVertex[idx] = node.elevation_m
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))

  const indices: number[] = []
  for (let r = 0; r < rows - 1; r += 1) {
    for (let c = 0; c < cols - 1; c += 1) {
      const a = r * cols + c
      const b = a + 1
      const below = a + cols
      const belowRight = below + 1
      indices.push(a, below, b, b, below, belowRight)
    }
  }
  geometry.setIndex(indices)
  geometry.computeVertexNormals()

  return { geometry, nodeIdByVertex, baseElevationByVertex, rows, cols }
}

/**
 * Displace every vertex to `baseElevation + max(selectDepth(state), 0)`
 * for the given real per-node-at-this-hour states. Returns how many
 * vertices got a genuinely positive depth, so a caller can decide whether
 * there's anything real to show.
 *
 * `selectDepth` is the one seam between this shared displacement logic
 * and WHICH real field drives it — `WaterSurface.tsx` passes
 * `depth_mean_m`, `UncertaintyEnvelope.tsx` (T4B.6) passes
 * `depth_min_m`/`depth_max_m` for its lower/upper bands. All three are
 * real Stage 2 `NodeState` fields; nothing here derives a value Stage 2
 * didn't already compute.
 *
 * `max(depth, 0)` is a rendering floor, not fabricated physics: Stage 2's
 * own contract never documents a negative depth, but nothing stops a
 * future upstream bug from emitting one, and a negative displacement
 * would sink the surface below its own dry resting height, which is not
 * a real water depth in either direction.
 */
export function applyField(
  positionAttr: THREE.BufferAttribute,
  nodeIdByVertex: string[],
  baseElevationByVertex: Float32Array,
  nodeStates: Record<string, NodeState>,
  selectDepth: (state: NodeState) => number,
): number {
  let wetCount = 0
  for (let i = 0; i < nodeIdByVertex.length; i += 1) {
    const nodeId = nodeIdByVertex[i]
    const state = nodeId ? nodeStates[nodeId] : undefined
    const depth = state ? Math.max(selectDepth(state), 0) : 0
    if (depth > 0) wetCount += 1
    positionAttr.setY(i, baseElevationByVertex[i] + depth)
  }
  positionAttr.needsUpdate = true
  return wetCount
}

/** `applyField` specialised to `depth_mean_m` — `WaterSurface.tsx`'s own field. */
export function applyDepths(
  positionAttr: THREE.BufferAttribute,
  nodeIdByVertex: string[],
  baseElevationByVertex: Float32Array,
  nodeStates: Record<string, NodeState>,
): number {
  return applyField(
    positionAttr,
    nodeIdByVertex,
    baseElevationByVertex,
    nodeStates,
    (state) => state.depth_mean_m,
  )
}
