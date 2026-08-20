import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { CitizenView } from './CitizenView'

const REAL_ALERT = {
  id: 'alert-1',
  site_id: 'vit-vellore',
  generated_at: '2026-08-21T00:00:00Z',
  severity: 'Severe',
  certainty: 0.82,
  urgency: 'Immediate',
  area_polygon: [
    [12.968, 79.155],
    [12.97, 79.155],
    [12.97, 79.157],
    [12.968, 79.157],
  ],
  effective_time: '2026-08-21T00:00:00Z',
  expiry_time: '2026-08-24T00:00:00Z',
  cap_xml: '<alert/>',
  text_by_language: {
    en: 'Rising water expected near Building_02 within 24 hours.\n1. Move valuables above 1 meter.\n2. Avoid low-lying areas near Building_02.',
    ta: 'உயரமான இடத்திற்கு செல்லவும்.\n1. படி 1.',
  },
}

function renderWithProviders() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CitizenView />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CitizenView', () => {
  it('shows the real status band + headline + numbered steps, never confidence/ensemble numbers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => REAL_ALERT, text: async () => '' })),
    )
    renderWithProviders()

    await waitFor(() => expect(screen.getByTestId('citizen-status-band')).toBeInTheDocument())
    expect(screen.getByText('Rising water expected near Building_02 within 24 hours.')).toBeInTheDocument()

    const steps = screen.getByTestId('citizen-action-steps')
    expect(steps.textContent).toContain('Move valuables above 1 meter.')
    expect(steps.textContent).toContain('Avoid low-lying areas near Building_02.')

    // Deliberately absent, per the doc's own rule.
    expect(screen.queryByText(/82%/)).not.toBeInTheDocument()
    expect(screen.queryByText(/certainty/i)).not.toBeInTheDocument()
  })

  it('switches language via the prominent top-of-screen selector', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => REAL_ALERT, text: async () => '' })),
    )
    renderWithProviders()

    await waitFor(() => expect(screen.getByTestId('citizen-language-select')).toBeInTheDocument())
    fireEvent.change(screen.getByTestId('citizen-language-select'), { target: { value: 'ta' } })
    expect(screen.getByText('உயரமான இடத்திற்கு செல்லவும்.')).toBeInTheDocument()
  })

  it('falls back to a real clipboard copy when the Web Share API is unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => REAL_ALERT, text: async () => '' })),
    )
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { ...navigator, share: undefined, clipboard: { writeText } })
    renderWithProviders()

    await waitFor(() => expect(screen.getByTestId('share-with-family-button')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('share-with-family-button'))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(await screen.findByText(/Link copied/)).toBeInTheDocument()
  })

  it('shows a real error, never fabricated alert content, when the fetch fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}), text: async () => 'unavailable' })),
    )
    renderWithProviders()
    await waitFor(() => expect(screen.getByText(/isn't available right now/)).toBeInTheDocument())
    expect(screen.queryByTestId('citizen-status-band')).not.toBeInTheDocument()
  })
})
