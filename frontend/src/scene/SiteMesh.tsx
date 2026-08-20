/**
 * Site mesh — buildings + roads (T4B.4).
 *
 * Renders the real `Building_01`/`Building_02`/`Road_Network` GLB Stage 2
 * ingested, ALREADY positioned in `Terrain.tsx`'s exact scene frame
 * (X=east, Y=up, Z=-north, relative to the same `site_lat`/`site_lon`
 * `Terrain` uses) by Stage 4's `GET /api/site-mesh/{site_id}` — see
 * `backend/stage4/scene/site_mesh.py`'s module docstring for the real
 * georeferencing transform applied and its one disclosed approximation
 * (a single-point DEM ground-elevation sample, not a per-vertex fit).
 *
 * This component therefore does ZERO additional positioning/scaling: the
 * loaded scene is dropped in at the origin as-is. That is what makes "no
 * floating/sinking relative to Terrain" a backend-transform property to
 * verify, not a frontend alignment fudge to tune per screenshot.
 *
 * WHY A MANUAL FETCH, NOT DREI'S `useGLTF`
 * ---------------------------------------------------------------
 * `useGLTF` caches strictly by URL and offers no hook into the response
 * headers — this project's honesty convention (mirroring `Terrain`'s own
 * `X-...-Source` disclosure) needs `X-Site-Mesh-Source` (`real_glb` vs
 * `placeholder_fallback`) surfaced to the caller, so this fetches the GLB
 * itself and parses it with `GLTFLoader.parse` directly (three.js's own
 * documented, current, callback-based parse API for a raw buffer,
 * confirmed in this session against three@0.185's real `GLTFLoader.js`).
 *
 * MATERIALS
 * ---------------------------------------------------------------
 * The backend re-export is geometry-only (`site_mesh.py`'s own docstring:
 * "no re-baked materials — out of scope for this task"), so every mesh
 * assigns a plain material here, chosen by the REAL object name Stage 2's
 * GLB defines (`Building_*` vs `Road_*`) — not a guess from mesh shape.
 * T4B.7 (damage overlay) recolors these same named meshes later.
 */

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as THREE from 'three'
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js'

import { queryKeys, siteMeshUrl } from '../api/client'

const BUILDING_MATERIAL = new THREE.MeshStandardMaterial({
  color: '#c9c2b3',
  roughness: 0.85,
  metalness: 0.05,
})
const ROAD_MATERIAL = new THREE.MeshStandardMaterial({
  color: '#3a3a3f',
  roughness: 0.95,
  metalness: 0,
})

function materialForObjectName(name: string): THREE.Material {
  return name.startsWith('Road_') ? ROAD_MATERIAL : BUILDING_MATERIAL
}

/** Walk up from a mesh to the nearest ancestor carrying a real node name
 *  (trimesh's GLB export nests one mesh per named scene node — the mesh
 *  itself is often unnamed). */
function nearestNamedAncestor(object: THREE.Object3D): string {
  let node: THREE.Object3D | null = object
  while (node) {
    if (node.name) return node.name
    node = node.parent
  }
  return ''
}

export interface SiteMeshFetchResult {
  scene: THREE.Group
  /** `"real_glb"` | `"placeholder_fallback"` | `"unknown"` (header missing). */
  source: string
}

export async function fetchSiteMeshScene(siteId: string): Promise<SiteMeshFetchResult> {
  const url = siteMeshUrl(siteId)
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`${url} failed with HTTP ${response.status}: ${await response.text()}`)
  }
  const source = response.headers.get('X-Site-Mesh-Source') ?? 'unknown'
  const buffer = await response.arrayBuffer()

  const loader = new GLTFLoader()
  const gltf = await new Promise<GLTF>((resolve, reject) => {
    loader.parse(buffer, '', resolve, reject)
  })

  gltf.scene.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      child.material = materialForObjectName(nearestNamedAncestor(child))
      child.receiveShadow = true
    }
  })

  return { scene: gltf.scene, source }
}

export interface SiteMeshProps {
  siteId: string
  /** Real vs. placeholder-fallback geometry — for callers that want to
   *  surface this the same way `Terrain`'s provenance strip does. */
  onSourceChange?: (source: string) => void
}

export function SiteMesh({ siteId, onSourceChange }: SiteMeshProps) {
  const { data } = useQuery({
    queryKey: queryKeys.siteMesh(siteId),
    queryFn: () => fetchSiteMeshScene(siteId),
    // The GLB is static for a site (same reasoning as Terrain's own
    // `staleTime: Infinity` — this isn't data that changes mid-session).
    staleTime: Infinity,
  })

  useEffect(() => {
    if (data) onSourceChange?.(data.source)
  }, [data, onSourceChange])

  const scene = useMemo(() => data?.scene ?? null, [data])

  if (!scene) return null
  return <primitive object={scene} name="site-mesh" />
}

export default SiteMesh
