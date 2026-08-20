/**
 * Shared "not built yet" placeholder — used by routes this session's
 * scope doesn't cover (CitizenView is T4C.4, About is T4C.6) so Landing's
 * real links have somewhere honest to land instead of a dead link or a
 * fabricated finished page. Clearly labeled as pending, in the same
 * pixel theme as everything else, never presented as the real page.
 */

import { Link } from 'react-router-dom'

import PixelPanel from '../components/pixel/PixelPanel'

export interface ComingSoonPageProps {
  title: string
  note: string
}

export function ComingSoonPage({ title, note }: ComingSoonPageProps) {
  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--pixel-bg-0)',
        padding: 24,
      }}
    >
      <PixelPanel scanlines style={{ padding: '2rem', maxWidth: 480, textAlign: 'center' }}>
        <h1 className="font-pixel-display" style={{ fontSize: '1.1rem', margin: '0 0 1rem' }}>
          {title}
        </h1>
        <p className="font-pixel-body" style={{ fontSize: '1.35rem', color: 'var(--ops-text-dim)', margin: '0 0 1.5rem' }}>
          {note}
        </p>
        <Link to="/" className="font-pixel-body" style={{ color: 'var(--pixel-accent)', fontSize: '1.2rem' }}>
          ◂ Back to Landing
        </Link>
      </PixelPanel>
    </main>
  )
}

export default ComingSoonPage
