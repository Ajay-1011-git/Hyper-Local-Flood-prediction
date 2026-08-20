/**
 * Site Detail slide-over — PLACEHOLDER, not yet T4C.2.
 *
 * T4C.2's real requirement (User Flow §3.3) is substantial: a thumbnail
 * crop of the structure's 3D render, a depth/velocity/rate-of-rise
 * time-series chart, the full hazard×exposure×vulnerability breakdown,
 * a plain-language confidence statement, and an "Include in alert"
 * toggle feeding the Alert Composer.
 *
 * This exists now only so T4C.1's real risk-ranking cross-link
 * ("clicking a row navigates to Site Detail ... slides in as a
 * right-hand panel over the dashboard, not a full navigation away")
 * has something real to slide in, rendered via the real nested route
 * `/dashboard/site/:structureId` — the 3D scene and ranking list behind
 * it stay mounted and visible, exactly as the doc requires; only the
 * PANEL CONTENT is a placeholder, not the slide-over mechanism itself.
 * T4C.2 will replace this file's content with the real breakdown.
 */

import { useNavigate, useParams } from 'react-router-dom'

import PixelButton from '../components/pixel/PixelButton'
import PixelPanel from '../components/pixel/PixelPanel'
import { useSceneStore } from '../store/sceneStore'

export function SiteDetailPanel() {
  const { structureId } = useParams<{ structureId: string }>()
  const navigate = useNavigate()
  const setHighlightedStructure = useSceneStore((s) => s.setHighlightedStructure)
  const damageRanking = useSceneStore((s) => s.damageRanking)
  const entry = damageRanking.find((e) => e.structure_id === structureId)

  const close = () => {
    setHighlightedStructure(null)
    navigate('/dashboard')
  }

  return (
    <PixelPanel
      testId="site-detail-panel"
      scanlines
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        width: 320,
        padding: '1rem',
        overflowY: 'auto',
        zIndex: 10,
      }}
    >
      <PixelButton onClick={close} style={{ fontSize: '0.9rem', marginBottom: '1rem' }}>
        ✕ Close
      </PixelButton>
      <h2 className="font-pixel-body" style={{ fontSize: '1.4rem', margin: '0 0 0.5rem' }}>
        {structureId}
      </h2>
      {entry ? (
        <dl className="font-data" style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)' }}>
          <dt>Peak hour</dt>
          <dd style={{ margin: '0 0 0.5rem' }}>{entry.peak_hour}h</dd>
          <dt>Peak depth</dt>
          <dd style={{ margin: '0 0 0.5rem' }}>{entry.peak_depth_m.toFixed(2)}m</dd>
          <dt>Confidence</dt>
          <dd style={{ margin: 0 }}>{Math.round(entry.confidence * 100)}%</dd>
        </dl>
      ) : (
        <p className="font-data" style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)' }}>
          No real ranking data for this structure yet.
        </p>
      )}
      <p className="font-pixel-body" style={{ fontSize: '1.1rem', color: 'var(--ops-text-dim)', marginTop: '1.5rem' }}>
        Full breakdown, time-series chart, and "Include in alert" toggle
        aren't built yet — check back soon.
      </p>
    </PixelPanel>
  )
}

export default SiteDetailPanel
