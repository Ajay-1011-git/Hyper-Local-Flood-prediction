/**
 * PixelPanel — the one shared surface primitive for the pixel-art design
 * system (T4C theme pass). A hard-bordered, stepped-bevel box — no
 * border-radius, no blurred shadow — used everywhere a "card"/"panel"
 * would otherwise appear, so every page shares the exact same surface
 * treatment rather than each re-inventing one.
 *
 * `variant="light"` is the citizen-view register (warm cream, per the
 * User Flow's own deliberate dark-ops/light-citizen split, §3.2 vs
 * §3.5) — same pixel bevel/border language, different palette half.
 */

import type { CSSProperties, ReactNode } from 'react'

export interface PixelPanelProps {
  children: ReactNode
  variant?: 'dark' | 'light'
  /** Adds the restrained scanline texture (dark register only — see
   *  index.css's own docstring on why it's kept subtle). */
  scanlines?: boolean
  className?: string
  style?: CSSProperties
  testId?: string
}

export function PixelPanel({
  children,
  variant = 'dark',
  scanlines = false,
  className = '',
  style,
  testId,
}: PixelPanelProps) {
  const classes = [
    'pixel-panel',
    variant === 'light' ? 'pixel-panel--light' : '',
    scanlines && variant !== 'light' ? 'pixel-scanlines' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={classes} style={style} data-testid={testId}>
      {children}
    </div>
  )
}

export default PixelPanel
