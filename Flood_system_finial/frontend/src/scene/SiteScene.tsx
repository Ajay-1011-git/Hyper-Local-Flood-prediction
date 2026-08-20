/**
 * The 3D scene shell (T4B.3).
 *
 * Owns the canvas, lighting and camera so `Terrain` stays a pure
 * geometry component. Later scene tasks (T4B.4 buildings, T4B.5 water,
 * T4B.6 envelope, T4B.7 damage overlay) mount as siblings of `<Terrain>`
 * inside this same canvas.
 *
 * Terrain comes from Stage 4's proxy endpoint, not Stage 2 — see
 * `api/client.ts`'s `fetchSiteTerrain` and the backend module docstring
 * for why. A 503 (no real DEM registered) surfaces as a visible error
 * rather than an empty canvas or a fake flat ground plane.
 */

import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { useQuery } from '@tanstack/react-query'

import { fetchSiteTerrain, queryKeys } from '../api/client'
import Terrain from './Terrain'

export interface SiteSceneProps {
  siteId: string
  /** Render both surfaces as wireframe — makes the seam (or absence of one) checkable. */
  wireframe?: boolean
}

export function SiteScene({ siteId, wireframe = false }: SiteSceneProps) {
  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.siteTerrain(siteId),
    queryFn: () => fetchSiteTerrain(siteId),
    // Terrain is static for a site; no reason to refetch on focus.
    staleTime: Infinity,
  })

  if (isPending) {
    return <div data-testid="terrain-loading">Loading terrain…</div>
  }
  if (error) {
    return (
      <div data-testid="terrain-error" style={{ color: '#b00', padding: 16 }}>
        Terrain unavailable: {(error as Error).message}
      </div>
    )
  }

  const nodata = data.regional.nodata_cell_count + data.site.nodata_cell_count

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <Canvas
        data-testid="terrain-canvas"
        camera={{ position: [700, 520, 700], near: 1, far: 20000, fov: 45 }}
      >
        <color attach="background" args={['#0b1020']} />
        <hemisphereLight args={['#cfe3ff', '#3a3f2f', 1.0]} />
        {/* No castShadow: a default-bounds shadow camera over a 4km terrain
            produced real shadow-acne slivers along the LOD boundary that
            looked like mesh gaps. Shadows are not required by T4B.3, and a
            correctly-bounded shadow camera belongs with the lighting pass
            (T4B.8) rather than being half-configured here. */}
        <directionalLight position={[900, 1200, 600]} intensity={1.6} />
        <Terrain
          regional={data.regional}
          site={data.site}
          refLat={data.site_lat}
          refLon={data.site_lon}
          wireframe={wireframe}
        />
        <OrbitControls makeDefault target={[0, 120, 0]} />
      </Canvas>

      {/* Honesty disclosure, per Stage 4's CLAUDE.md ground truth: this
          surface is DEM-derived, never surveyed. T4C.6's About page states
          it in full; this is the in-scene short form so the limitation is
          visible where the data is, not only on another page. */}
      <div
        data-testid="terrain-provenance"
        style={{
          position: 'absolute',
          left: 12,
          bottom: 12,
          font: '12px system-ui, sans-serif',
          color: '#cbd5e1',
          background: 'rgba(11,16,32,0.72)',
          padding: '6px 10px',
          borderRadius: 6,
          maxWidth: 520,
        }}
      >
        Terrain interpolated from Stage 1B’s regional DEM (~
        {Math.round(data.site.resolution_m)} m sampling) — not a survey.
        {' '}Regional {data.regional.rows}×{data.regional.cols}, site {data.site.rows}×
        {data.site.cols}.
        {nodata > 0 ? ` ${nodata} cell(s) had no DEM data and use the patch mean.` : ''}
      </div>
    </div>
  )
}

export default SiteScene
