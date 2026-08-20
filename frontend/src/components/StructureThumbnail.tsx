/**
 * StructureThumbnail — Site Detail's "small thumbnail crop of its 3D
 * render" (T4C.2, User Flow §3.3).
 *
 * A REAL CROP OF THE REAL GEOMETRY, NOT A SCREENSHOT OR A STATIC ASSET
 * ---------------------------------------------------------------
 * Reuses the SAME `queryKeys.siteMesh(siteId)` cache entry `SiteMesh.tsx`
 * / `DamageOverlay.tsx` already populate (TanStack Query dedupes — no
 * extra fetch), then CLONES just the named structure's real mesh(es) out
 * of it into a small isolated scene with its own tightly-framed camera.
 * Cloning (not reparenting the original) keeps this safe alongside
 * `SiteMesh`'s own mounted primitive — same reasoning as `DamageOverlay`
 * mutating materials in place rather than mounting a second `<primitive>`
 * of the live object.
 *
 * `Road_Segment_*` ids map to the real GLB's one merged `Road_Network`
 * mesh (same disclosed limitation as `DamageOverlay.tsx` — no per-segment
 * geometry exists in the real model).
 */

import { useEffect, useMemo } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { useQuery } from '@tanstack/react-query'
import * as THREE from 'three'

import { queryKeys } from '../api/client'
import { fetchSiteMeshScene } from '../scene/SiteMesh'

export interface StructureThumbnailProps {
  siteId: string
  structureId: string
}

interface FramedGroup {
  group: THREE.Group
  cameraPosition: [number, number, number]
  target: [number, number, number]
}

function extractFramedStructure(scene: THREE.Group, structureId: string): FramedGroup | null {
  const targetName = structureId.startsWith('Road_Segment') ? 'Road_Network' : structureId
  const group = new THREE.Group()
  let found = false

  scene.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) return
    let node: THREE.Object3D | null = child
    while (node && !node.name) node = node.parent
    if (node?.name !== targetName) return

    const clone = child.clone()
    clone.material = Array.isArray(child.material)
      ? child.material.map((m) => m.clone())
      : child.material.clone()
    group.add(clone)
    found = true
  })

  if (!found) return null

  const box = new THREE.Box3().setFromObject(group)
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  const radius = Math.max(size.x, size.y, size.z, 1) / 2
  const distance = radius * 2.6

  return {
    group,
    cameraPosition: [center.x + distance, center.y + distance * 0.7, center.z + distance],
    target: [center.x, center.y, center.z],
  }
}

/** No OrbitControls in this static mini-viewer -- a real camera still
 *  needs one real `lookAt` call, since a bare `<Canvas camera={{position}}>`
 *  otherwise points along -Z regardless of where the structure actually is. */
function CameraLookAt({ target }: { target: [number, number, number] }) {
  const camera = useThree((state) => state.camera)
  useEffect(() => {
    camera.lookAt(...target)
  }, [camera, target])
  return null
}

export function StructureThumbnail({ siteId, structureId }: StructureThumbnailProps) {
  const { data } = useQuery({
    queryKey: queryKeys.siteMesh(siteId),
    queryFn: () => fetchSiteMeshScene(siteId),
    staleTime: Infinity,
    retry: false,
  })

  const framed = useMemo(() => (data ? extractFramedStructure(data.scene, structureId) : null), [
    data,
    structureId,
  ])

  if (!framed) {
    return (
      <div
        data-testid="structure-thumbnail-empty"
        style={{
          width: 160,
          height: 110,
          background: 'var(--pixel-bg-2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        className="font-data"
      >
        <span style={{ fontSize: '0.7rem', color: 'var(--ops-text-dim)' }}>no 3D render yet</span>
      </div>
    )
  }

  return (
    <div data-testid="structure-thumbnail" style={{ width: 160, height: 110 }}>
      <Canvas camera={{ position: framed.cameraPosition, fov: 40, near: 0.1, far: 5000 }}>
        <color attach="background" args={['#0c0926']} />
        <hemisphereLight args={['#cfe3ff', '#3a3f2f', 1.2]} />
        <directionalLight position={[50, 80, 40]} intensity={1.4} />
        <CameraLookAt target={framed.target} />
        <primitive object={framed.group} />
      </Canvas>
    </div>
  )
}

export default StructureThumbnail
