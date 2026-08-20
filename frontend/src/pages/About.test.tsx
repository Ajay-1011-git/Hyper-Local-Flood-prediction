import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { About } from './About'

const REAL_REGIONAL_FORECAST = {
  forecast_id: 'test',
  source: 'GEFS',
  region_bbox: { min_lat: 12.8, max_lat: 13.1, min_lon: 79.0, max_lon: 79.3 },
  generated_at: '2026-08-21T00:00:00Z',
  resolution_km: 27.75,
  members: Array.from({ length: 31 }, (_, i) => ({
    member_id: i,
    trajectory: [{ hour: 6, rainfall_mm: 1 }],
  })),
}

function renderWithProviders() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <About />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('About', () => {
  it('states all five required honesty disclosures as real, readable text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => REAL_REGIONAL_FORECAST, text: async () => '' })),
    )
    renderWithProviders()

    // 1. Rainfall resolution limit.
    expect(screen.getByText(/never claimed below about 2km resolution/)).toBeInTheDocument()

    // 2. DEM-interpolated terrain, not surveyed.
    expect(screen.getByText(/not a photogrammetry survey/)).toBeInTheDocument()

    // 3. Live sensor proves assimilation, not forecast improvement.
    expect(screen.getByText(/data assimilation/)).toBeInTheDocument()
    expect(screen.getByText(/improve or feed into the underlying rainfall forecast itself/)).toBeInTheDocument()

    // 4. Vulnerability curve is a general, cited approximation.
    expect(screen.getByText(/neither has been locally calibrated/)).toBeInTheDocument()

    // 5. Which forecast source is powering the current display -- fetched live.
    await waitFor(() => expect(screen.getByTestId('live-forecast-source')).toBeInTheDocument())
    expect(screen.getByTestId('live-forecast-source').textContent).toContain('GEFS (0.25°)')
    expect(screen.getByTestId('live-forecast-source').textContent).toContain('31 real members')
  })

  it('shows a real, honest message when the live forecast source is unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}), text: async () => 'unavailable' })),
    )
    renderWithProviders()

    await waitFor(() => expect(screen.getByText(/unavailable right now/)).toBeInTheDocument())
    expect(screen.queryByTestId('live-forecast-source')).not.toBeInTheDocument()
  })
})
