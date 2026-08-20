import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { CitizenGuidance } from './CitizenGuidance'

describe('CitizenGuidance', () => {
  it('renders all three real sections with real content, no live alert fetch', () => {
    render(
      <MemoryRouter>
        <CitizenGuidance />
      </MemoryRouter>,
    )
    expect(screen.getByText('Before a flood')).toBeInTheDocument()
    expect(screen.getByText('During a flood')).toBeInTheDocument()
    expect(screen.getByText('After a flood')).toBeInTheDocument()
    expect(screen.getByText(/Move to higher ground immediately/)).toBeInTheDocument()
  })

  it('discloses the real English-only translation limitation', () => {
    render(
      <MemoryRouter>
        <CitizenGuidance />
      </MemoryRouter>,
    )
    expect(screen.getByText(/English only/)).toBeInTheDocument()
  })

  it('links back to the live citizen alert', () => {
    render(
      <MemoryRouter>
        <CitizenGuidance />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /Back to alert/ })).toHaveAttribute('href', '/citizen')
  })
})
