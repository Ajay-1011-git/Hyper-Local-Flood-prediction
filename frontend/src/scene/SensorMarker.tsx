/**
 * Physical sensor marker — where the real ESP32/HC-SR04 unit is.
 *
 * RENDERS NOTHING UNTIL REAL HARDWARE IS REALLY PLACED
 * ---------------------------------------------------------------
 * Stage 2 reports `configured: false` while
 * `SENSOR_TARGET_X_M`/`_Y_M`/`SENSOR_MOUNT_HEIGHT_M` are unset, which is
 * the current, honest state — the unit has not been deployed yet. This
 * component draws nothing in that case. A marker at a guessed position
 * would claim a deployment that has not happened, and would then be
 * "confirmed" by the water it appears to be measuring.
 *
 * Once the settings hold real values, Stage 2 resolves them to the
 * NEAREST REAL MESH NODE and returns its `node_id`. The marker is placed
 * at that node's real scene position (the same `/api/mesh-nodes` data the
 * water surface is built from), so the marker and the simulation data it
 * relates to are guaranteed to be at the same place rather than being
 * positioned by two independent coordinate conversions.
 *
 * WATER STATE COMES FROM THE SIMULATION AT THE SENSOR'S OWN NODE
 * ---------------------------------------------------------------
 * The beacon reads the real `NodeState.depth_mean_m` at the sensor's node
 * for the current hour — which, after a live reading is assimilated
 * (T2.8's ghost-cell nudge), IS the measured value at that node. So "the
 * sensor is detecting water" and "the scene shows water there" are the
 * same real number, not two separately-maintained displays.
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { fetchSensorLocation, fetchSiteMeshNodes, queryKeys } from '../api/client'
import { useSceneStore } from '../store/sceneStore'

export interface SensorMarkerProps {
  siteId: string
}

/** Depth (m) above which the sensor is treated as standing in water. */
const WET_M = 0.02

export function SensorMarker({ siteId }: SensorMarkerProps) {
  const { data: sensor } = useQuery({
    queryKey: queryKeys.sensorLocation(siteId),
    queryFn: () => fetchSensorLocation(siteId),
    staleTime: 60_000,
    retry: false,
  })

  const { data: meshNodes } = useQuery({
    queryKey: queryKeys.meshNodes(siteId),
    queryFn: () => fetchSiteMeshNodes(siteId),
    staleTime: Infinity,
    retry: false,
  })

  const nodeId = sensor?.configured ? (sensor.nearest_node_id ?? null) : null

  const position = useMemo(() => {
    if (!nodeId || !meshNodes) return null
    const node = meshNodes.nodes.find((n) => n.node_id === nodeId)
    return node ? { x: node.x_m, y: node.elevation_m, z: node.z_m } : null
  }, [nodeId, meshNodes])

  const nodeStatesByHour = useSceneStore((s) => s.nodeStatesByHour)
  const currentHour = useSceneStore((s) => s.currentHour)
  const depth = nodeId ? (nodeStatesByHour[currentHour]?.[nodeId]?.depth_mean_m ?? 0) : 0
  const isWet = depth > WET_M

  // No real hardware placed, or no real position for it -> draw nothing.
  if (!position) return null

  const mountHeight = sensor?.mount_height_m ?? 1
  const beaconY = position.y + mountHeight

  return (
    <group name="sensor-marker" position={[position.x, 0, position.z]}>
      {/* Mounting post, at its real configured height. */}
      <mesh position={[0, position.y + mountHeight / 2, 0]}>
        <cylinderGeometry args={[0.25, 0.25, mountHeight, 8]} />
        <meshStandardMaterial color="#d8d2c4" roughness={0.7} />
      </mesh>

      {/* Beacon: blue while the simulation says this node is wet, amber
          while it is dry. Never invents a state — this is the real depth
          at the sensor's own node. */}
      <mesh position={[0, beaconY, 0]}>
        <sphereGeometry args={[0.7, 16, 16]} />
        <meshStandardMaterial
          color={isWet ? '#38bdf8' : '#f5b301'}
          emissive={isWet ? '#38bdf8' : '#f5b301'}
          emissiveIntensity={isWet ? 0.9 : 0.45}
        />
      </mesh>

      {/* A ring on the ground so the sensor stays findable from the wide
          regional camera, where a 0.7m sphere is sub-pixel. */}
      <mesh position={[0, position.y + 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[1.6, 2.4, 24]} />
        <meshBasicMaterial color={isWet ? '#38bdf8' : '#f5b301'} transparent opacity={0.75} />
      </mesh>
    </group>
  )
}

export default SensorMarker
