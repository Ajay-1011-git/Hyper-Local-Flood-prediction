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

import { useState } from 'react'
import { Outlet, useSearchParams } from 'react-router-dom'

import type { SimulationScenario } from '../api/client'
import ForecastPanel from '../components/ForecastPanel'
import RiskRankingList from '../components/RiskRankingList'
import SensorStrip from '../components/SensorStrip'
import SimulationControls from '../components/SimulationControls'
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
  // Which of Stage 2's two real simulations the whole dashboard is
  // showing. Held here, not inside the scene, because the ranking column
  // and the scene must never disagree about which one they are showing.
  const [scenario, setScenario] = useState<SimulationScenario>('real')

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
        <div
          style={{
            width: 300,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            overflowY: 'auto',
          }}
        >
          <SimulationControls
            siteId={SITE_ID}
            scenario={scenario}
            onScenarioChange={setScenario}
          />
          <ForecastPanel siteLat={SITE_LAT} siteLon={SITE_LON} />
        </div>

        <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
          <SiteScene siteId={SITE_ID} scenario={scenario} wireframe={wireframe} />
          {/* Site Detail slide-over (T4C.2 placeholder) -- rendered as a
              sibling overlay, not a route swap, so the scene above stays
              mounted per the doc's own requirement. */}
          <Outlet />
        </div>

        <RiskRankingList scenario={scenario} />
      </div>

      <SensorStrip siteId={SITE_ID} />
    </div>
  )
}

export default Dashboard
