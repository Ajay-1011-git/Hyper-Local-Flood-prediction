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

import { useEffect, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { useQuery } from '@tanstack/react-query'

import { fetchDamageRanking, fetchSimulationResult, fetchSiteTerrain, queryKeys } from '../api/client'
import type { DamageRankEntry } from '../api/types'
import { useSiteSocket } from '../hooks/useSiteSocket'
import { SEVERITY_ORDER, severityForEntry } from '../severity'
import PixelButton from '../components/pixel/PixelButton'
import PixelPanel from '../components/pixel/PixelPanel'
import { useSceneStore } from '../store/sceneStore'
import CameraController, { type CameraPose } from './CameraController'
import DamageOverlay from './DamageOverlay'
import SiteMesh from './SiteMesh'
import Terrain from './Terrain'
import UncertaintyEnvelope from './UncertaintyEnvelope'
import WaterSurface from './WaterSurface'

/**
 * The scene's two real resting poses (T4B.8) — module-level constants so
 * `CameraController` sees stable object identity across `SiteScene`'s
 * frequent re-renders (wetVertexCount/siteMeshSource/etc. all change
 * often; a fresh literal every render would be harmless but wasteful).
 *
 * `REGIONAL` matches T4B.3's original "opens wide" camera prop exactly.
 * `SITE` is a close, oblique view over the real building/road cluster
 * (SiteMesh's own real coordinates: Building_01/02 span roughly
 * x:[-53,122], z:[-63,66]; mesh-node elevations run ~117-138) — the real
 * site patch this project actually registers, not the User Flow doc's
 * stated "50m×50m" figure (see CameraController's own docstring for that
 * disclosed discrepancy).
 */
const REGIONAL_CAMERA_POSE: CameraPose = { position: [700, 520, 700], target: [0, 120, 0] }
const SITE_CAMERA_POSE: CameraPose = { position: [110, 140, 160], target: [25, 128, 0] }

/** Real, human-readable summary of the current worst structure's real
 *  severity at this hour — matches DamageOverlay's own per-entry logic,
 *  not a separate guess. */
function damageRankingSummary(damageRanking: DamageRankEntry[], currentHour: number): string {
  if (damageRanking.length === 0) return 'no real structures ranked'
  const maxRiskScore = damageRanking.reduce((max, entry) => Math.max(max, entry.risk_score), 0)
  let worstIndex = 0
  let worstEntryId = damageRanking[0].structure_id
  for (const entry of damageRanking) {
    const severity = severityForEntry(entry, currentHour, maxRiskScore)
    const index = SEVERITY_ORDER.indexOf(severity)
    if (index > worstIndex) {
      worstIndex = index
      worstEntryId = entry.structure_id
    }
  }
  return `worst is ${worstEntryId} (${SEVERITY_ORDER[worstIndex]}) at hour ${currentHour}`
}

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
  const [siteMeshSource, setSiteMeshSource] = useState<string | null>(null)
  const [wetVertexCount, setWetVertexCount] = useState(0)

  // Real simulation load (T4B.5) — Stage 2's own `/api/simulation/site`
  // 404s until something real has been precomputed for this site (that
  // pipeline has no live caller anywhere in this repo, confirmed this
  // session), so `error` here is a genuine, common, non-fatal case: the
  // scene just has no water to show yet, not a crash.
  const loadSimulationResult = useSceneStore((s) => s.loadSimulationResult)
  const currentHour = useSceneStore((s) => s.currentHour)
  const hoursAvailable = useSceneStore((s) => s.hoursAvailable)
  const setCurrentHour = useSceneStore((s) => s.setCurrentHour)
  const { data: simulationResult, error: simulationError } = useQuery({
    queryKey: queryKeys.simulation(siteId),
    queryFn: () => fetchSimulationResult(siteId),
    staleTime: Infinity,
    retry: false,
  })
  useEffect(() => {
    if (simulationResult) loadSimulationResult(simulationResult)
  }, [simulationResult, loadSimulationResult])

  // Real WS wiring (T4B.6) — see useSiteSocket's own docstring: nothing
  // in this app ever connected T4B.1's SiteSocket before this.
  useSiteSocket(siteId)
  const connectionStatus = useSceneStore((s) => s.connectionStatus)
  const lastSensorAssimilation = useSceneStore((s) => s.lastSensorAssimilation)

  // Real damage ranking load (T4B.7) — same pattern as T4B.5's simulation
  // load: DamageOverlay only reads the store, this is what actually
  // fetches Stage 3's real ranking into it. `ranking_update` (the WS
  // event) has no real emitter anywhere in this repo either (T4B.1's own
  // documented finding), so this REST fetch is the real source, not the
  // socket.
  const setDamageRanking = useSceneStore((s) => s.setDamageRanking)
  const damageRanking = useSceneStore((s) => s.damageRanking)
  const { data: damageRankingData, error: damageRankingError } = useQuery({
    queryKey: queryKeys.damageRanking(siteId),
    queryFn: () => fetchDamageRanking(siteId),
    staleTime: Infinity,
    retry: false,
  })
  useEffect(() => {
    if (damageRankingData) setDamageRanking(damageRankingData)
  }, [damageRankingData, setDamageRanking])

  // Real camera fly-in/fly-out (T4B.8) — `flyTrigger` is bumped by the
  // button below; CameraController toggles regional<->site each time.
  const [flyTrigger, setFlyTrigger] = useState(0)
  const [atSite, setAtSite] = useState(false)
  const [flyProgress, setFlyProgress] = useState<{ progress: number; flyingToSite: boolean } | null>(
    null,
  )
  const handleFlyProgress = (progress: number, flyingToSite: boolean) => {
    setFlyProgress({ progress, flyingToSite })
    if (progress >= 1) setTimeout(() => setFlyProgress(null), 300)
  }

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
        <SiteMesh siteId={siteId} onSourceChange={setSiteMeshSource} />
        <WaterSurface siteId={siteId} onWetVertexCountChange={setWetVertexCount} />
        <UncertaintyEnvelope siteId={siteId} />
        <DamageOverlay siteId={siteId} />
        {/* No static `target` prop here (T4B.8): CameraController now owns
            the camera's resting pose AND its animated transitions, and a
            static prop re-applied every SiteScene render would fight its
            imperative `controls.target` updates mid-flight. */}
        <OrbitControls makeDefault />
        <CameraController
          regional={REGIONAL_CAMERA_POSE}
          site={SITE_CAMERA_POSE}
          trigger={flyTrigger}
          onProgress={handleFlyProgress}
        />
      </Canvas>

      {/* Honesty disclosure, per Stage 4's CLAUDE.md ground truth: this
          surface is DEM-derived, never surveyed. T4C.6's About page states
          it in full; this is the in-scene short form so the limitation is
          visible where the data is, not only on another page. */}
      <PixelPanel
        testId="terrain-provenance"
        scanlines
        className="font-pixel-body"
        style={{
          position: 'absolute',
          left: 12,
          bottom: 12,
          padding: '8px 12px',
          maxWidth: 520,
          fontSize: '1.05rem',
          lineHeight: 1.35,
        }}
      >
        Terrain interpolated from Stage 1B’s regional DEM (~
        {Math.round(data.site.resolution_m)} m sampling) — not a survey.
        {' '}Regional {data.regional.rows}×{data.regional.cols}, site {data.site.rows}×
        {data.site.cols}.
        {nodata > 0 ? ` ${nodata} cell(s) had no DEM data and use the patch mean.` : ''}
        {siteMeshSource === 'placeholder_fallback'
          ? ' Buildings/roads: PLACEHOLDER geometry (real GLB not found).'
          : siteMeshSource === 'real_glb'
            ? ' Buildings/roads: real site GLB.'
            : ''}
        {' '}
        {simulationResult
          ? `Water: ${wetVertexCount} node(s) wet at hour ${currentHour}.`
          : simulationError
            ? 'Water: no live simulation for this site yet.'
            : 'Water: loading simulation…'}
        {' '}
        {`WS: ${connectionStatus}.`}
        {lastSensorAssimilation
          ? ` Last assimilation: sensor ${lastSensorAssimilation.sensorId} (${lastSensorAssimilation.updatedNodeIds.length} node(s) updated).`
          : ''}
        {' '}
        {damageRankingData
          ? ` Damage ranking: ${damageRankingSummary(damageRanking, currentHour)}.`
          : damageRankingError
            ? ' Damage ranking: unavailable.'
            : ' Damage ranking: loading…'}
      </PixelPanel>

      {/* Minimal timeline control for T4B.5's own VERIFY (rising/falling
          across hours) -- the full TimelineScrubber component is T4C's
          own dashboard task; this is only enough to move `currentHour`
          for now. */}
      {hoursAvailable.length > 1 && (
        <PixelPanel
          testId="hour-scrubber"
          className="font-pixel-body"
          style={{
            position: 'absolute',
            right: 12,
            bottom: 12,
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            padding: '6px 10px',
            fontSize: '1.1rem',
          }}
        >
          <PixelButton
            data-testid="hour-prev"
            style={{ padding: '0.25em 0.6em', fontSize: '1rem' }}
            onClick={() =>
              setCurrentHour(
                hoursAvailable[Math.max(0, hoursAvailable.indexOf(currentHour) - 1)] ?? currentHour,
              )
            }
          >
            ◀
          </PixelButton>
          <span>hour {currentHour}</span>
          <PixelButton
            data-testid="hour-next"
            style={{ padding: '0.25em 0.6em', fontSize: '1rem' }}
            onClick={() =>
              setCurrentHour(
                hoursAvailable[
                  Math.min(hoursAvailable.length - 1, hoursAvailable.indexOf(currentHour) + 1)
                ] ?? currentHour,
              )
            }
          >
            ▶
          </PixelButton>
        </PixelPanel>
      )}

      {/* T4B.8 — "A single click ... smoothly flies the camera down into
          the scanned site" (User Flow §3.2). A dedicated button, not a
          bare canvas click: OrbitControls already treats a click-drag as
          orbiting, and disambiguating a plain click from the start of a
          drag reliably is a real UX problem this task doesn't need to
          also solve. */}
      <div
        style={{
          position: 'absolute',
          top: 12,
          right: 12,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          gap: 6,
        }}
      >
        <PixelButton
          data-testid="fly-camera"
          variant="primary"
          onClick={() => {
            setFlyTrigger((n) => n + 1)
            setAtSite((was) => !was)
          }}
        >
          {atSite ? 'Fly to region ▸' : 'Fly to site ▸'}
        </PixelButton>
        {flyProgress && (
          <PixelPanel
            testId="fly-progress"
            className="font-pixel-body"
            style={{ padding: '4px 10px', fontSize: '1rem' }}
          >
            {flyProgress.flyingToSite ? 'Flying to site…' : 'Flying to region…'}{' '}
            {Math.round(flyProgress.progress * 100)}%
          </PixelPanel>
        )}
      </div>
    </div>
  )
}

export default SiteScene
