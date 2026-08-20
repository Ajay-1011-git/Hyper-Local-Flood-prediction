import { BrowserRouter, Route, Routes } from 'react-router-dom'

import About from './pages/About'
import CitizenView from './pages/CitizenView'
import Dashboard from './pages/Dashboard'
import Landing from './pages/Landing'
import SiteDetail from './pages/SiteDetail'

/**
 * App shell — real client-side routing (T4C.0), replacing the earlier
 * single always-mounted `SiteScene` root. Routes match the User Flow
 * doc's own information architecture (§2): `/` Landing, `/dashboard`
 * Operations (with a real nested `site/:structureId` slide-over, T4C.2),
 * `/citizen` Citizen access, `/about` methodology. `/citizen`/`/about`
 * are still clearly-labeled placeholders for T4C.4/T4C.6 — see each
 * page's own docstring.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<Dashboard />}>
          <Route path="site/:structureId" element={<SiteDetail />} />
        </Route>
        <Route path="/citizen" element={<CitizenView />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </BrowserRouter>
  )
}
