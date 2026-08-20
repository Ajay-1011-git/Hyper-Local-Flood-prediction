/**
 * Operations Dashboard (`/dashboard`) — PLACEHOLDER, not yet T4C.1.
 *
 * T4C.1's real requirement (User Flow §3.2) is a four-zone grid: top
 * bar, forecast panel, this 3D scene, risk ranking list, sensor strip —
 * none of that surrounding chrome exists yet. This file exists now only
 * so the Landing page's real "Open Operations Dashboard" button (T4C.0)
 * has somewhere real to land rather than a dead link, per this session's
 * own scope (pixel theme + landing page). It wraps the real, already-
 * built 3D scene (`SiteScene`, T4B.0–T4B.8) as-is. T4C.1 will replace
 * this file's content with the real four-zone layout — same file, not a
 * new one.
 */

import { useSearchParams } from 'react-router-dom'

import SiteScene from '../scene/SiteScene'

const SITE_ID = import.meta.env.VITE_SITE_ID ?? 'vit-vellore'

export function Dashboard() {
  const [searchParams] = useSearchParams()
  const wireframe = searchParams.has('wireframe')

  return (
    <main
      style={{ background: 'var(--ops-bg)', color: 'var(--ops-text)', height: '100vh' }}
      className="font-sans"
    >
      <SiteScene siteId={SITE_ID} wireframe={wireframe} />
    </main>
  )
}

export default Dashboard
