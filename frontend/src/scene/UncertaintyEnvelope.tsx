/**
 * Uncertainty envelope (T4B.6).
 *
 * A translucent band between each real node's `depth_min_m` and
 * `depth_max_m` (Stage 2's real ensemble spread) — bracketing
 * `WaterSurface.tsx`'s `depth_mean_m` surface from below and above. Same
 * ZERO-PHYSICS rule as `WaterSurface`: this only displaces vertices by
 * real backend fields, never derives a spread of its own.
 *
 * THE DEFINING DEMO MOMENT: VISIBLE NARROWING ON ASSIMILATION
 * ---------------------------------------------------------------
 * Stage 2's real ghost-cell nudge (T2.8) narrows `depth_min_m`/
 * `depth_max_m` toward `depth_mean_m` for the nodes a live sensor reading
 * actually touches — confirmed genuinely LOCAL (`sceneStore.ts`'s own
 * comment: "only 157/29,832 NodeStates changed"). This component does
 * nothing special to make that happen: the store's `applySocketEvent`
 * already merges the updated `NodeState`s in, so the SAME per-frame
 * `applyField` re-render that reacts to an hour change also reacts to a
 * real `sensor_assimilated` event — the band visibly narrows because the
 * real upstream numbers narrowed, not because this component animates a
 * tween.
 *
 * The one thing this component adds on top is the DISTINCT visual
 * treatment the User Flow spec calls for: a brief pulse/glow ring at the
 * real centroid of `lastSensorAssimilation.updatedNodeIds` (Stage 2's own
 * real ghost-cell node ids, never a guessed location), so the moment is
 * noticeable, not just a subtle mesh shift.
 */

import { useEffect, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { useQuery } from '@tanstack/react-query'
import * as THREE from 'three'

import { fetchSiteMeshNodes, queryKeys } from '../api/client'
import type { NodeState } from '../api/types'
import { useSceneStore } from '../store/sceneStore'
import { applyField, buildWaterGrid, parseNodeId } from './waterGeometry'

const EMPTY_NODE_STATES: Record<string, NodeState> = {}
const PULSE_DURATION_MS = 1600

interface AssimilationPulseProps {
  position: [number, number, number]
}

/** The brief pulse/glow the User Flow spec calls for — grows and fades
 *  once, then `UncertaintyEnvelope` unmounts it. */
function AssimilationPulse({ position }: AssimilationPulseProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const startedAtRef = useRef(performance.now())

  useFrame(() => {
    const mesh = meshRef.current
    if (!mesh) return
    const t = Math.min(1, (performance.now() - startedAtRef.current) / PULSE_DURATION_MS)
    // A real site is a few hundred metres across (see SiteMesh/Terrain) —
    // sized in metres, not arbitrary units, so it reads as a real-scale
    // ground marker rather than a tiny UI glyph lost in the scene.
    mesh.scale.setScalar(6 + t * 40)
    const material = mesh.material as THREE.MeshBasicMaterial
    material.opacity = 0.95 * (1 - t)
  })

  return (
    <mesh position={position} rotation={[-Math.PI / 2, 0, 0]} ref={meshRef} renderOrder={2}>
      <ringGeometry args={[0.55, 1, 64]} />
      <meshBasicMaterial
        color="#ffd166"
        transparent
        opacity={0.95}
        side={THREE.DoubleSide}
        depthWrite={false}
        toneMapped={false}
      />
    </mesh>
  )
}

export interface UncertaintyEnvelopeProps {
  siteId: string
}

export function UncertaintyEnvelope({ siteId }: UncertaintyEnvelopeProps) {
  const { data: meshNodes } = useQuery({
    queryKey: queryKeys.meshNodes(siteId),
    queryFn: () => fetchSiteMeshNodes(siteId),
    // Shares its cache entry with WaterSurface's identical query key —
    // one real fetch of the (large, static-per-site) mesh-node grid, not
    // a second network round trip.
    staleTime: Infinity,
    retry: false,
  })

  // Two independent geometry instances over the SAME real node grid: one
  // displaced by depth_min_m (the lower band), one by depth_max_m (the
  // upper band). `useState` (not `useMemo`) so each is built exactly once
  // per real meshNodes response and then mutated in place by the effect
  // below — rebuilding a 30k-vertex BufferGeometry every render would be
  // wasteful for data that only changes when `meshNodes` itself does.
  const [lowerGrid, setLowerGrid] = useState<ReturnType<typeof buildWaterGrid> | null>(null)
  const [upperGrid, setUpperGrid] = useState<ReturnType<typeof buildWaterGrid> | null>(null)
  useEffect(() => {
    if (!meshNodes) return
    setLowerGrid(buildWaterGrid(meshNodes))
    setUpperGrid(buildWaterGrid(meshNodes))
  }, [meshNodes])

  const nodeStatesByHour = useSceneStore((s) => s.nodeStatesByHour)
  const currentHour = useSceneStore((s) => s.currentHour)
  const nodeStates = nodeStatesByHour[currentHour] ?? EMPTY_NODE_STATES
  const lastSensorAssimilation = useSceneStore((s) => s.lastSensorAssimilation)

  useEffect(() => {
    if (!lowerGrid || !upperGrid) return
    const lowerPosition = lowerGrid.geometry.getAttribute('position') as THREE.BufferAttribute
    const upperPosition = upperGrid.geometry.getAttribute('position') as THREE.BufferAttribute
    applyField(
      lowerPosition,
      lowerGrid.nodeIdByVertex,
      lowerGrid.baseElevationByVertex,
      nodeStates,
      (state) => state.depth_min_m,
    )
    applyField(
      upperPosition,
      upperGrid.nodeIdByVertex,
      upperGrid.baseElevationByVertex,
      nodeStates,
      (state) => state.depth_max_m,
    )
    lowerGrid.geometry.computeVertexNormals()
    upperGrid.geometry.computeVertexNormals()
  }, [lowerGrid, upperGrid, nodeStates])

  const [pulse, setPulse] = useState<{ key: string; position: [number, number, number] } | null>(null)

  useEffect(() => {
    if (!lastSensorAssimilation || !meshNodes || !lowerGrid) return
    if (lastSensorAssimilation.updatedNodeIds.length === 0) return

    const positionAttr = lowerGrid.geometry.getAttribute('position') as THREE.BufferAttribute
    let sumX = 0
    let sumY = 0
    let sumZ = 0
    let count = 0
    for (const nodeId of lastSensorAssimilation.updatedNodeIds) {
      const parsed = parseNodeId(nodeId)
      if (!parsed) continue
      const idx = parsed.row * meshNodes.cols + parsed.col
      if (idx < 0 || idx >= positionAttr.count) continue
      sumX += positionAttr.getX(idx)
      sumY += positionAttr.getY(idx)
      sumZ += positionAttr.getZ(idx)
      count += 1
    }
    if (count === 0) return

    setPulse({
      key: `${lastSensorAssimilation.sensorId}-${lastSensorAssimilation.timestamp}`,
      position: [sumX / count, sumY / count + 3, sumZ / count],
    })
    const timer = setTimeout(() => setPulse(null), PULSE_DURATION_MS + 100)
    return () => clearTimeout(timer)
  }, [lastSensorAssimilation, meshNodes, lowerGrid])

  if (!lowerGrid || !upperGrid) return null
  // Nothing real to bracket -- same reasoning as WaterSurface: render
  // nothing rather than a band sitting at dry ground level.
  if (Object.keys(nodeStates).length === 0) return null

  return (
    <group name="uncertainty-envelope">
      <mesh geometry={upperGrid.geometry} renderOrder={0}>
        <meshBasicMaterial
          color="#8ecae6"
          transparent
          opacity={0.2}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      <mesh geometry={lowerGrid.geometry} renderOrder={0}>
        <meshBasicMaterial
          color="#8ecae6"
          transparent
          opacity={0.2}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      {pulse && <AssimilationPulse key={pulse.key} position={pulse.position} />}
    </group>
  )
}

export default UncertaintyEnvelope
