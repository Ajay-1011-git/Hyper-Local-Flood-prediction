/**
 * Terrain rendering (T4B.3).
 *
 * Renders two real elevation surfaces as one continuous landscape:
 *   - the decimated regional DEM as the wide surround (TRD §6 point 3)
 *   - a finer site-local patch inside it
 *
 * SEAMLESSNESS IS STRUCTURAL, NOT TUNED
 * ---------------------------------------------------------------
 * Both patches come from the SAME source raster, windowed at different
 * extents by `backend/stage4/terrain/dem_proxy.py` (see its docstring).
 * They therefore agree at their shared boundary by construction — no
 * edge-blending, vertex-welding or z-fudging is applied here, and none
 * should be added. If a seam ever appears, that means the two windows
 * genuinely disagree and the backend is what needs fixing.
 *
 * WHAT THIS SURFACE IS, HONESTLY
 * ---------------------------------------------------------------
 * `interpolated_from_regional_dem` is always `true`: this is ~30m
 * CartoDEM, NOT a photogrammetry survey. Over the ~300m site patch that
 * is genuinely only ~10x10 real samples — the smooth shading below comes
 * from normal interpolation across those real vertices, and no detail is
 * synthesised beyond them. Per Stage 4's CLAUDE.md ground truth, T4C.6's
 * About page must state this limitation; this component's job is correct
 * rendering, not making the data look better than it is.
 *
 * NODATA
 * ---------------------------------------------------------------
 * The backend emits `null` for real DEM voids rather than inventing a
 * number. A mesh cannot have a hole at a vertex, so those vertices are
 * placed at the patch's mean elevation and counted — `onNodata` reports
 * the count so the UI can disclose it instead of silently smoothing.
 *
 * COORDINATES
 * ---------------------------------------------------------------
 * Scene space is metres, X=east, Z=north (three.js is Y-up), with the
 * origin at the site centre (`site_lat`/`site_lon`). This matches the
 * Y-up, east/north convention Stage 2 confirmed for the real GLB, so
 * T4B.4 can drop the building meshes in without a second transform.
 */

import { useMemo } from 'react'
import * as THREE from 'three'

import type { TerrainHeightmap } from '../api/types'
import {
  buildHeightmapGeometry,
  holeIndicesFor,
  type TerrainSurfaceStats,
} from './terrainGeometry'

export type { TerrainSurfaceStats }

interface TerrainSurfaceProps {
  heightmap: TerrainHeightmap
  refLat: number
  refLon: number
  color: string
  /** Grid-index rect of faces to omit (where the finer LOD covers this one). */
  hole?: { r0: number; r1: number; c0: number; c1: number } | null
  /** LOD ratio to the coarser surface; stitches this patch's boundary onto it. */
  stitchStep?: number
  wireframe?: boolean
  onStats?: (stats: TerrainSurfaceStats) => void
}

function TerrainSurface({
  heightmap,
  refLat,
  refLon,
  color,
  hole = null,
  stitchStep = 0,
  wireframe = false,
  onStats,
}: TerrainSurfaceProps) {
  const { geometry, centre, stats } = useMemo(
    () => buildHeightmapGeometry(heightmap, refLat, refLon, hole, stitchStep),
    [heightmap, refLat, refLon, hole, stitchStep],
  )
  useMemo(() => onStats?.(stats), [onStats, stats])

  return (
    <mesh
      geometry={geometry}
      // -90deg about X turns the XY plane into the XZ ground plane, with the
      // pre-rotation +Z displacement becoming world +Y (up).
      rotation={[-Math.PI / 2, 0, 0]}
      // Scene X = east, Z = north. Three.js -Z points "into" the screen by
      // default, so north maps to -Z to keep a conventional map orientation.
      position={[centre.east, 0, -centre.north]}
    >
      <meshStandardMaterial
        color={color}
        wireframe={wireframe}
        flatShading={false}
        roughness={0.95}
        metalness={0}
        side={THREE.DoubleSide}
      />
    </mesh>
  )
}

export interface TerrainProps {
  regional: TerrainHeightmap
  site: TerrainHeightmap
  /** Scene origin — the real site centre. */
  refLat: number
  refLon: number
  wireframe?: boolean
}

/**
 * The full terrain: wide decimated surround + finer site patch.
 *
 * Both are real DEM windows; see this module's docstring for why they are
 * seamless by construction and what the surface honestly represents.
 */
export function Terrain({ regional, site, refLat, refLon, wireframe = false }: TerrainProps) {
  // Cut the regional faces the site patch covers, rather than z-offsetting
  // two coplanar surfaces -- see cutHole() for why the offset approach was
  // rejected after a real render showed heavy z-fighting.
  const hole = useMemo(() => holeIndicesFor(regional, site), [regional, site])
  // How many site vertices span one regional cell -- the site's boundary ring
  // is stitched onto the regional's straight edges at this ratio.
  const stitchStep = useMemo(
    () => Math.max(0, Math.round(regional.resolution_m / site.resolution_m)),
    [regional.resolution_m, site.resolution_m],
  )

  return (
    <group name="terrain">
      <TerrainSurface
        heightmap={regional}
        refLat={refLat}
        refLon={refLon}
        color="#6b7a5e"
        hole={hole}
        wireframe={wireframe}
      />
      <TerrainSurface
        heightmap={site}
        refLat={refLat}
        refLon={refLon}
        color="#8a9a72"
        stitchStep={stitchStep}
        wireframe={wireframe}
      />
    </group>
  )
}

export default Terrain
