import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { SEVERITY_COLORS } from '../severity'
import { SeverityBadge } from './SeverityBadge'

describe('SeverityBadge', () => {
  it('renders the real state label', () => {
    render(<SeverityBadge state="Critical" />)
    expect(screen.getByText(/Critical/)).toBeInTheDocument()
  })

  it('appends a real suffix with an em-dash, matching the User Flow doc\'s own example', () => {
    render(<SeverityBadge state="Monitoring" suffix="Vellore District" />)
    expect(screen.getByText('Monitoring — Vellore District')).toBeInTheDocument()
  })

  it('never conveys severity by color alone -- glyph count escalates with severity', () => {
    const { container: monitoring } = render(<SeverityBadge state="Monitoring" />)
    const { container: watch } = render(<SeverityBadge state="Watch" />)
    const { container: warning } = render(<SeverityBadge state="Warning" />)
    const { container: critical } = render(<SeverityBadge state="Critical" />)

    const glyphOf = (c: HTMLElement) => c.querySelector('[aria-hidden="true"]')?.textContent ?? ''
    expect(glyphOf(monitoring).length).toBeLessThan(glyphOf(watch).length)
    expect(glyphOf(watch).length).toBeLessThan(glyphOf(warning).length)
    expect(glyphOf(warning).length).toBeLessThan(glyphOf(critical).length)
  })

  it('colors the badge from the real severity palette, not an arbitrary hex', () => {
    render(<SeverityBadge state="Warning" />)
    expect(screen.getByText(/Warning/).closest('span')).toHaveStyle({
      color: SEVERITY_COLORS.Warning,
    })
  })
})
