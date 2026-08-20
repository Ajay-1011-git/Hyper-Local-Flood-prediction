import SiteScene from './scene/SiteScene'

const SITE_ID = import.meta.env.VITE_SITE_ID ?? 'vit-vellore'

/**
 * T4B.3 scene host.
 *
 * Replaces T4B.0's connectivity probe (which had served its purpose —
 * proving a real backend call reached the browser) with the real 3D
 * scene, so the terrain is rendered against live Stage 4 data and can be
 * captured by the headless-screenshot harness for this task's VERIFY.
 *
 * `?wireframe=1` renders both surfaces as wireframe, which is how the
 * regional/site boundary is actually inspected for a seam — a shaded
 * surface can hide a small discontinuity that wireframe makes obvious.
 *
 * Replaced by the real routed pages in Section C (T4C.0 onward).
 */
export default function App() {
  const wireframe = new URLSearchParams(window.location.search).has('wireframe')

  return (
    <main
      style={{ background: 'var(--ops-bg)', color: 'var(--ops-text)', height: '100vh' }}
      className="font-sans"
    >
      <SiteScene siteId={SITE_ID} wireframe={wireframe} />
    </main>
  )
}
