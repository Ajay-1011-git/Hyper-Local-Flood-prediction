/**
 * Landing (`/`) — T4C.0.
 *
 * Per the User Flow doc's own §3.1: "orient any visitor in under five
 * seconds and route them to the right experience" — a live status
 * badge, two visually distinct entry points (a solid primary CTA to
 * Operations, a lighter link to Citizen access), and a small persistent
 * footer link to `/about`.
 *
 * DISCLOSED DEVIATION FROM THE DOC'S OWN BACKGROUND DESCRIPTION
 * ---------------------------------------------------------------
 * §3.1 describes "a subtle, slowly panning satellite/terrain view of the
 * demo region." This uses the project owner's own supplied pixel-art
 * artwork instead (a flooded night city, deliberately chosen as this
 * project's whole visual direction — see index.css's own design-system
 * docstring) — same "subtle, slowly panning" motion cue (`.pixel-hero-pan`),
 * different, explicitly-requested image. Not a silent swap.
 */

import { Link } from 'react-router-dom'

import heroUrl from '../assets/flood-city-hero.png'
import PixelButton from '../components/pixel/PixelButton'
import PixelIcon from '../components/pixel/PixelIcon'
import SeverityBadge from '../components/SeverityBadge'

export function Landing() {
  return (
    <main
      style={{
        position: 'relative',
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        background: 'var(--pixel-bg-0)',
      }}
    >
      {/* Full-bleed hero artwork, slow ambient drift. A separate layer
          from the content so the animation's `transform: scale` never
          affects layout/foreground text position (Core Web Vitals: no
          CLS from this). */}
      <div
        aria-hidden="true"
        className="pixel-hero-pan"
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `url(${heroUrl})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          willChange: 'transform',
        }}
      />
      {/* Bottom scrim -- keeps foreground text/CTAs legible over the
          artwork (UX guideline: modal/foreground scrim strong enough to
          isolate content, ~40-60% here at its strongest point). */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(to bottom, rgba(12,9,38,0.25) 0%, rgba(12,9,38,0.55) 55%, rgba(12,9,38,0.92) 100%)',
        }}
      />

      <div
        style={{
          position: 'relative',
          zIndex: 1,
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          gap: '1.5rem',
          padding: '2rem 1.25rem',
        }}
      >
        <div style={{ color: 'var(--pixel-amber)' }}>
          <PixelIcon name="drop" size={48} title="Flood Watch" />
        </div>

        <h1
          className="font-pixel-display"
          style={{
            fontSize: 'clamp(1.1rem, 4vw, 2rem)',
            color: 'var(--pixel-glow)',
            margin: 0,
            lineHeight: 1.6,
            textShadow: '3px 3px 0 var(--pixel-bg-0)',
          }}
        >
          FLOOD WATCH
        </h1>

        <p
          className="font-pixel-body"
          style={{
            fontSize: 'clamp(1.1rem, 2.5vw, 1.5rem)',
            color: 'var(--ops-text-dim)',
            margin: 0,
            maxWidth: 520,
          }}
        >
          72-hour flood forecasting, down to the street.
        </p>

        <SeverityBadge state="Monitoring" suffix="Vellore District" />

        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '1rem',
            justifyContent: 'center',
            marginTop: '0.5rem',
          }}
        >
          <Link to="/dashboard" style={{ textDecoration: 'none' }}>
            <PixelButton variant="primary">Open Operations Dashboard</PixelButton>
          </Link>
          <Link
            to="/citizen"
            className="font-pixel-body"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              color: 'var(--pixel-glow)',
              fontSize: '1.2rem',
              textDecoration: 'underline',
              textUnderlineOffset: '0.25em',
            }}
          >
            Check my area ▸
          </Link>
        </div>
      </div>

      <footer
        style={{
          position: 'relative',
          zIndex: 1,
          textAlign: 'center',
          padding: '1rem',
        }}
      >
        <Link
          to="/about"
          className="font-pixel-body"
          style={{ color: 'var(--ops-text-dim)', fontSize: '1rem', textDecoration: 'none' }}
        >
          About &amp; methodology
        </Link>
      </footer>
    </main>
  )
}

export default Landing
