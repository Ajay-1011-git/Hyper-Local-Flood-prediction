/**
 * Site Detail slide-over (`/dashboard/site/:structureId`) — T4C.2.
 *
 * Per User Flow §3.3: "Opened from a ranking-list click or a direct
 * click on a building in the 3D scene. Slides in as a right-hand panel
 * over the dashboard (not a full navigation away — the 3D scene and
 * ranking list stay visible behind it) so the operator never loses
 * context." Rendered via the real nested route `/dashboard` ->
 * `site/:structureId` (`App.tsx`) — `Dashboard.tsx` keeps the 3D scene
 * and `RiskRankingList` mounted the whole time; this component is only
 * the overlay panel itself.
 *
 * CONTENTS, PER THE DOC'S OWN LIST
 * ---------------------------------------------------------------
 * - Structure name/ID + a real thumbnail crop of its 3D render
 *   (`StructureThumbnail.tsx` — real cloned GLB geometry, not a
 *   screenshot or static asset).
 * - The real depth/velocity/rate-of-rise time series
 *   (`HazardTimeSeriesChart.tsx`), current timeline hour marked.
 * - The full hazard × exposure × vulnerability breakdown — three real
 *   labeled sub-scores feeding `risk_score`, not just the final number.
 * - A confidence statement. The doc's own example phrasing ("41 of 50
 *   forecast scenarios...") assumes a fixed ensemble size that isn't in
 *   the real `DamageRankEntry` contract (only the fraction,
 *   `confidence`, sourced from `ensemble_agreement_fraction`) — stated
 *   here as a real percentage instead of inventing a member count.
 * - A real "Include in alert" toggle, writing to the scene store's
 *   `includedInAlertIds` (T4C.3's Alert Composer will read the SAME
 *   real selection, not a second copy).
 */

import { useNavigate, useParams } from 'react-router-dom'

import PixelButton from '../components/pixel/PixelButton'
import PixelPanel from '../components/pixel/PixelPanel'
import HazardTimeSeriesChart from '../components/HazardTimeSeriesChart'
import StructureThumbnail from '../components/StructureThumbnail'
import { useSceneStore } from '../store/sceneStore'

const SITE_ID = import.meta.env.VITE_SITE_ID ?? 'vit-vellore'

export function SiteDetail() {
  const { structureId } = useParams<{ structureId: string }>()
  const navigate = useNavigate()

  const setHighlightedStructure = useSceneStore((s) => s.setHighlightedStructure)
  const damageRanking = useSceneStore((s) => s.damageRanking)
  const nodeStatesByHour = useSceneStore((s) => s.nodeStatesByHour)
  const hoursAvailable = useSceneStore((s) => s.hoursAvailable)
  const currentHour = useSceneStore((s) => s.currentHour)
  const includedInAlertIds = useSceneStore((s) => s.includedInAlertIds)
  const toggleIncludedInAlert = useSceneStore((s) => s.toggleIncludedInAlert)

  const entry = damageRanking.find((e) => e.structure_id === structureId)
  const isIncluded = structureId ? includedInAlertIds.includes(structureId) : false

  const close = () => {
    setHighlightedStructure(null)
    navigate('/dashboard')
  }

  if (!structureId) return null

  return (
    <PixelPanel
      testId="site-detail-panel"
      scanlines
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        width: 340,
        padding: '1rem',
        overflowY: 'auto',
        zIndex: 10,
      }}
    >
      <PixelButton onClick={close} style={{ fontSize: '0.9rem', marginBottom: '1rem' }}>
        ✕ Close
      </PixelButton>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', marginBottom: '1rem' }}>
        <StructureThumbnail siteId={SITE_ID} structureId={structureId} />
        <div>
          <h2 className="font-pixel-body" style={{ fontSize: '1.4rem', margin: 0 }}>
            {structureId}
          </h2>
          <p className="font-data" style={{ fontSize: '0.75rem', color: 'var(--ops-text-dim)', margin: '4px 0 0' }}>
            {entry ? entry.structure_type.replace('_', ' ') : 'unknown type'}
          </p>
        </div>
      </div>

      {!entry ? (
        <p className="font-data" style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)' }}>
          No real ranking data for this structure yet.
        </p>
      ) : (
        <>
          <section style={{ marginBottom: '1rem' }}>
            <h3 className="font-pixel-body" style={{ fontSize: '1.1rem', margin: '0 0 0.4rem' }}>
              Hazard time series
            </h3>
            <HazardTimeSeriesChart
              nodeStatesByHour={nodeStatesByHour}
              hoursAvailable={hoursAvailable}
              structureId={structureId}
              currentHour={currentHour}
            />
          </section>

          <section style={{ marginBottom: '1rem' }} data-testid="risk-breakdown">
            <h3 className="font-pixel-body" style={{ fontSize: '1.1rem', margin: '0 0 0.4rem' }}>
              Risk breakdown
            </h3>
            <dl className="font-data" style={{ fontSize: '0.85rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <dt>Hazard</dt>
                <dd style={{ margin: 0 }}>{entry.hazard_score.toFixed(2)}</dd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <dt>Exposure</dt>
                <dd style={{ margin: 0 }}>{entry.exposure_score.toFixed(2)}</dd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <dt>Vulnerability</dt>
                <dd style={{ margin: 0 }}>{entry.vulnerability_score.toFixed(2)}</dd>
              </div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  borderTop: '2px solid var(--pixel-border)',
                  marginTop: 4,
                  paddingTop: 4,
                  fontWeight: 600,
                }}
              >
                <dt>Risk score</dt>
                <dd style={{ margin: 0 }}>{entry.risk_score.toFixed(2)}</dd>
              </div>
            </dl>
            <p className="font-data" style={{ fontSize: '0.7rem', color: 'var(--ops-text-dim)', marginTop: 4 }}>
              Vulnerability curve: {entry.vulnerability_source}
              {entry.vulnerability_is_local_calibration ? '' : ' (general, not locally calibrated)'}
            </p>
          </section>

          <p className="font-pixel-body" style={{ fontSize: '1.1rem', margin: '0 0 1rem' }}>
            {Math.round(entry.confidence * 100)}% of forecast scenarios place this structure above the
            critical threshold.
          </p>

          <label
            className="font-pixel-body"
            style={{ fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
          >
            <input
              type="checkbox"
              checked={isIncluded}
              onChange={() => toggleIncludedInAlert(structureId)}
              data-testid="include-in-alert-toggle"
              style={{ width: 18, height: 18 }}
            />
            Include in alert
          </label>
        </>
      )}
    </PixelPanel>
  )
}

export default SiteDetail
