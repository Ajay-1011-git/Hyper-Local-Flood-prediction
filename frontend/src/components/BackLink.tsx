/**
 * Shared back navigation.
 *
 * Every page below the Landing page gets one of these, so a real user
 * can always get out of where they are without the browser chrome. Two
 * real behaviours, deliberately distinguished rather than collapsed:
 *
 *   - `to` given  -> a real `<Link>` to a known parent route. Used where
 *     the page has ONE sensible parent regardless of how it was reached
 *     (Alert Composer -> Dashboard, Guidance -> Citizen View).
 *   - `to` omitted -> `navigate(-1)`, real browser history. Used where
 *     the page is reachable from several places and history is the
 *     honest answer to "back where?".
 *
 * Falls back to `fallbackTo` when there is no history entry to go back to
 * (a deep link opened in a fresh tab — `history.length <= 1`), so the
 * control is never a dead end.
 */

import { Link, useNavigate } from 'react-router-dom'

export interface BackLinkProps {
  /** Explicit parent route. Omit to use real browser history instead. */
  to?: string
  /** Where to go when history has nowhere to go back to. */
  fallbackTo?: string
  label?: string
  /** `light` matches the Citizen View's own register; `dark` the ops UI. */
  tone?: 'dark' | 'light'
  style?: React.CSSProperties
}

export function BackLink({
  to,
  fallbackTo = '/',
  label = 'Back',
  tone = 'dark',
  style,
}: BackLinkProps) {
  const navigate = useNavigate()

  const color = tone === 'light' ? 'var(--citizen-text-dim)' : 'var(--ops-text-dim)'
  const shared: React.CSSProperties = {
    color,
    fontSize: '1rem',
    background: 'none',
    border: 'none',
    padding: 0,
    cursor: 'pointer',
    textDecoration: 'none',
    ...style,
  }

  if (to) {
    return (
      <Link to={to} data-testid="back-link" className="font-pixel-body" style={shared}>
        ◂ {label}
      </Link>
    )
  }

  return (
    <button
      type="button"
      data-testid="back-link"
      className="font-pixel-body"
      style={shared}
      onClick={() => {
        if (window.history.length > 1) navigate(-1)
        else navigate(fallbackTo)
      }}
    >
      ◂ {label}
    </button>
  )
}

export default BackLink
