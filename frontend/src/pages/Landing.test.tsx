import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { Landing } from './Landing'

/**
 * Smoke test for T4C.0 — confirms the real required content (User Flow
 * §3.1: status badge, two entry points, footer About link) is present,
 * not a visual regression test (that's what the real screenshots in this
 * task's VERIFY are for).
 */
describe('Landing', () => {
  it('shows the live status badge with the real example region text', () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    )
    expect(screen.getByText('Monitoring — Vellore District')).toBeInTheDocument()
  })

  it('has both real entry points, linking to their real routes', () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    )
    const opsLink = screen.getByRole('link', { name: /Open Operations Dashboard/ })
    expect(opsLink).toHaveAttribute('href', '/dashboard')

    const citizenLink = screen.getByRole('link', { name: /Check my area/ })
    expect(citizenLink).toHaveAttribute('href', '/citizen')
  })

  it('has a persistent footer link to /about', () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /About & methodology/ })).toHaveAttribute('href', '/about')
  })

  it('shows the real tagline', () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    )
    expect(screen.getByText('72-hour flood forecasting, down to the street.')).toBeInTheDocument()
  })
})
