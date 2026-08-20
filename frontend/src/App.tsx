import { BrowserRouter, Route, Routes } from 'react-router-dom'

import About from './pages/About'
import AlertComposer from './pages/AlertComposer'
import CitizenView from './pages/CitizenView'
import Dashboard from './pages/Dashboard'
import Landing from './pages/Landing'
import SiteDetail from './pages/SiteDetail'

/**
 * App shell — real client-side routing (T4C.0), replacing the earlier
 * single always-mounted `SiteScene` root. Routes match the User Flow
 * doc's own information architecture (§2): `/` Landing, `/dashboard`
 * Operations (with a real nested `site/:structureId` slide-over, T4C.2),
 * `/dashboard/alert` Alert Composer (T4C.3 — its own full page, not a
 * slide-over, per §3.4's two-column layout), `/citizen` Citizen access,
 * `/about` methodology. `/citizen`/`/about` are still clearly-labeled
 * placeholders for T4C.4/T4C.6 — see each page's own docstring.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<Dashboard />}>
          <Route path="site/:structureId" element={<SiteDetail />} />
        </Route>
        <Route path="/dashboard/alert" element={<AlertComposer />} />
        <Route path="/citizen" element={<CitizenView />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </BrowserRouter>
  )
}
