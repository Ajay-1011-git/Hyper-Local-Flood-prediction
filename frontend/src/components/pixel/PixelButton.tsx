/**
 * PixelButton — the one shared button primitive for the pixel-art design
 * system (T4C theme pass). Hard bevel border, chunky press feedback
 * (shadow-collapse on `:active`, defined in index.css — not a soft
 * ease), real `:focus-visible` outline, real `:disabled` handling.
 *
 * `variant`: `"primary"` (the accent-filled CTA — one per screen, per
 * the UX guideline "each screen should have only one primary CTA"),
 * `"secondary"` (default, dark-register chrome), or `"light"` (citizen
 * register).
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react'

export interface PixelButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
  variant?: 'primary' | 'secondary' | 'light'
}

export function PixelButton({
  children,
  variant = 'secondary',
  className = '',
  type = 'button',
  ...rest
}: PixelButtonProps) {
  const classes = [
    'pixel-button',
    variant === 'primary' ? 'pixel-button--primary' : '',
    variant === 'light' ? 'pixel-button--light' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button type={type} className={classes} {...rest}>
      {children}
    </button>
  )
}

export default PixelButton
