/**
 * Operations Dashboard (`/dashboard`) — T4C.1.
 *
 * The real four-zone grid from User Flow §3.2: top bar, forecast panel
 * (left), 3D scene (center — the already-real T4B.0–T4B.8 scene), risk
 * ranking (right), sensor strip (bottom). `/dashboard/site/:structureId`
 * renders as a real nested route (`<Outlet/>`) — a slide-over panel on
 * top of this same mounted tree, per the doc's own "not a full
 * navigation away" requirement (T4C.2 is a placeholder for now; see
 * `SiteDetailPanel.tsx`'s own docstring).
 */

import { Outlet, useSearchParams } from 'react-router-dom'

import ForecastPanel from '../components/ForecastPanel'
import RiskRankingList from '../components/RiskRankingList'
import SensorStrip from '../components/SensorStrip'
import TopBar from '../components/TopBar'
import SiteScene from '../scene/SiteScene'

const SITE_ID = import.meta.env.VITE_SITE_ID ?? 'vit-vellore'
// Real site coordinates (matches backend/stage4/config.py's own
// target_site_lat/lon default — the real VIT Vellore site) — the
// forecast panel's river-stage cross-check needs a real point to query.
const SITE_LAT = 12.969223
const SITE_LON = 79.155934

export function Dashboard() {
  const [searchParams] = useSearchParams()
  const wireframe = searchParams.has('wireframe')

  return (
    <div
      style={{
        position: 'relative',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--ops-bg)',
        color: 'var(--ops-text)',
      }}
      className="font-sans"
    >
      <TopBar siteName="VIT Vellore" />

      <div style={{ flex: 1, display: 'flex', gap: 12, padding: 12, minHeight: 0 }}>
        <ForecastPanel siteLat={SITE_LAT} siteLon={SITE_LON} />

        <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
          <SiteScene siteId={SITE_ID} wireframe={wireframe} />
          {/* Site Detail slide-over (T4C.2 placeholder) -- rendered as a
              sibling overlay, not a route swap, so the scene above stays
              mounted per the doc's own requirement. */}
          <Outlet />
        </div>

        <RiskRankingList />
      </div>

      <SensorStrip siteId={SITE_ID} />
    </div>
  )
}

export default Dashboard
