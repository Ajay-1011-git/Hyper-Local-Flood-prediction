/**
 * SeverityBadge — the one shared severity-chip primitive (T4C theme
 * pass), reading from `severity.ts`'s real four-state vocabulary
 * (Monitoring/Watch/Warning/Critical — transcribed from the User Flow
 * doc's own §1 table). Pairs color + a pixel glyph + the real text
 * label, per that same doc's §7 rule: "severity is never communicated
 * by color alone."
 *
 * The glyph count itself is a real severity signal (more marks = worse),
 * not decoration — readable even without color (e.g. printed, or a
 * color-blind viewer), same reasoning as the doc's own accessibility rule.
 */

import { SEVERITY_COLORS, type SeverityState } from '../severity'

/** Mark count itself IS the severity signal (0/1/2/3) — strictly
 *  escalating, not just four arbitrary same-size glyphs, so it reads
 *  even in grayscale/print. Monitoring gets none: "no elevated risk"
 *  has nothing to flag. */
const SEVERITY_GLYPHS: Record<SeverityState, string> = {
  Monitoring: '',
  Watch: '▲',
  Warning: '▲▲',
  Critical: '▲▲▲',
}

export interface SeverityBadgeProps {
  state: SeverityState
  /** Real, human-readable context appended after the state word — e.g.
   *  the User Flow doc's own landing-page example: "Monitoring —
   *  Vellore District". */
  suffix?: string
  variant?: 'dark' | 'light'
  className?: string
}

export function SeverityBadge({ state, suffix, variant = 'dark', className = '' }: SeverityBadgeProps) {
  const classes = ['pixel-badge', variant === 'light' ? 'pixel-badge--light' : '', className]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={classes} style={{ color: SEVERITY_COLORS[state] }}>
      <span aria-hidden="true">{SEVERITY_GLYPHS[state]}</span>
      <span>
        {state}
        {suffix ? ` — ${suffix}` : ''}
      </span>
    </span>
  )
}

export default SeverityBadge
