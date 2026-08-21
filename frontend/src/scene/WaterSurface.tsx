/**
 * Water surface (T4B.5).
 *
 * Renders REAL, backend-computed hydraulic state as a displaced surface —
 * per Stage 4's Operating Contract, this component performs ZERO physics
 * of its own. Vertex heights come directly from the scene store's current
 * `NodeState.depth_mean_m` at whatever hour the timeline is on
 * (`waterGeometry.ts::applyDepths`); this component's only job is
 * wiring that real data to a real mesh each time either changes.
 *
 * GEOMETRY, NOT AN OFF-THE-SHELF OCEAN SHADER
 * ---------------------------------------------------------------
 * three.js ships `Water`/`Water2` (examples/jsm/objects) for reflective
 * open-ocean rendering (normal maps, planar reflection) — confirmed
 * in-session by listing the real installed module. That is the wrong
 * tool here: this surface's shape IS the data (per-node real depth), not
 * a decorative animated texture on a flat plane. A plain displaced grid
 * with a translucent `meshPhysicalMaterial` is what makes "rising/falling
 * levels tied to store state changes" a literal geometry change, matching
 * this task's own real requirement.
 *
 * SAME GRID AS THE REAL COMPUTATIONAL MESH
 * ---------------------------------------------------------------
 * One vertex per real `MeshNodePosition` from Stage 4's `/api/mesh-nodes`
 * proxy (T4B.5 support) — the SAME row/col grid Stage 2's real simulation
 * indexes by `node_id`, in `Terrain.tsx`'s exact scene frame. No
 * additional positioning happens here, same reasoning as `SiteMesh.tsx`.
 *
 * NO REAL DATA -> RENDER NOTHING, NOT A FABRICATED FLAT SHEET
 * ---------------------------------------------------------------
 * If the scene store holds no `NodeState`s for the current hour (Stage
 * 2 has no live precompute pipeline in this repo — confirmed; a fresh
 * session with nothing loaded is the common case), this renders nothing
 * rather than a full-site water plane sitting exactly at dry ground
 * level, which would be visually indistinguishable from real all-dry
 * data and therefore a real, if subtle, honesty violation.
 */

import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { useQuery } from '@tanstack/react-query'
import * as THREE from 'three'

import { fetchSiteMeshNodes, queryKeys } from '../api/client'
import { useSceneStore } from '../store/sceneStore'
import type { NodeState } from '../api/types'
import { applyDepths, buildWaterGrid } from './waterGeometry'
import { createFlowMaterial } from './waterMaterial'

const EMPTY_NODE_STATES: Record<string, NodeState> = {}

export interface WaterSurfaceProps {
  siteId: string
  /** Real count of vertices currently showing standing water (>0m depth)
   *  — for callers that want to disclose this, same convention as
   *  `SiteMesh`'s `onSourceChange`. */
  onWetVertexCountChange?: (count: number) => void
}

export function WaterSurface({ siteId, onWetVertexCountChange }: WaterSurfaceProps) {
  const { data: meshNodes, error } = useQuery({
    queryKey: queryKeys.meshNodes(siteId),
    queryFn: () => fetchSiteMeshNodes(siteId),
    // Node positions are static for a site -- same reasoning as Terrain's
    // and SiteMesh's own staleTime.
    staleTime: Infinity,
    retry: false,
  })

  const grid = useMemo(() => (meshNodes ? buildWaterGrid(meshNodes) : null), [meshNodes])

  // One material instance for the lifetime of the component — rebuilding
  // it per render would recompile the shader program every frame.
  const flow = useMemo(() => createFlowMaterial(), [])
  useEffect(() => () => flow.material.dispose(), [flow])

  // Real elapsed-time drive for the flow animation. This is the only
  // non-simulation input to the render (see waterMaterial.ts's docstring).
  useFrame((state) => flow.setTime(state.clock.getElapsedTime()))

  const nodeStatesByHour = useSceneStore((s) => s.nodeStatesByHour)
  const currentHour = useSceneStore((s) => s.currentHour)
  const nodeStates = nodeStatesByHour[currentHour] ?? EMPTY_NODE_STATES

  useEffect(() => {
    if (!grid) return
    const positionAttr = grid.geometry.getAttribute('position') as THREE.BufferAttribute
    const wetCount = applyDepths(
      positionAttr,
      grid.nodeIdByVertex,
      grid.baseElevationByVertex,
      nodeStates,
    )

    // Real per-vertex depth + velocity, handed to the flow shader. Created
    // once, then updated in place on every hour change.
    const vertexCount = grid.nodeIdByVertex.length
    let depthAttr = grid.geometry.getAttribute('aDepth') as THREE.BufferAttribute | undefined
    let velocityAttr = grid.geometry.getAttribute('aVelocity') as THREE.BufferAttribute | undefined
    if (!depthAttr || !velocityAttr) {
      depthAttr = new THREE.BufferAttribute(new Float32Array(vertexCount), 1)
      velocityAttr = new THREE.BufferAttribute(new Float32Array(vertexCount), 1)
      grid.geometry.setAttribute('aDepth', depthAttr)
      grid.geometry.setAttribute('aVelocity', velocityAttr)
    }
    for (let i = 0; i < vertexCount; i += 1) {
      const nodeId = grid.nodeIdByVertex[i]
      const state = nodeId ? nodeStates[nodeId] : undefined
      depthAttr.setX(i, state ? Math.max(state.depth_mean_m, 0) : 0)
      velocityAttr.setX(i, state ? Math.max(state.velocity_mean_mps, 0) : 0)
    }
    depthAttr.needsUpdate = true
    velocityAttr.needsUpdate = true

    grid.geometry.computeVertexNormals()
    onWetVertexCountChange?.(wetCount)
  }, [grid, nodeStates, onWetVertexCountChange])

  if (error) {
    // Real, confirmed case (see module docstring): no /api/mesh-nodes
    // coverage for this site. Logged once, not thrown -- a missing water
    // layer shouldn't take down the whole scene.
    // eslint-disable-next-line no-console
    console.warn('WaterSurface: mesh nodes unavailable', error)
  }
  if (!grid) return null
  if (Object.keys(nodeStates).length === 0) return null

  return <mesh geometry={grid.geometry} material={flow.material} name="water-surface" />
}

export default WaterSurface
