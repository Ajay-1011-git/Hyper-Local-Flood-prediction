import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { AlertComposer } from './AlertComposer'

const REAL_ALERT = {
  id: 'alert-1',
  site_id: 'vit-vellore',
  generated_at: '2026-08-21T00:00:00Z',
  severity: 'Extreme',
  certainty: 0.82,
  urgency: 'Immediate',
  area_polygon: [[12.9, 79.1]],
  effective_time: '2026-08-21T00:00:00Z',
  expiry_time: '2026-08-24T00:00:00Z',
  cap_xml: '<alert xmlns="cap"><info><severity>Extreme</severity></info></alert>',
  text_by_language: {
    en: '1. Move to higher ground.\n2. Avoid flooded roads.',
    ta: 'உயரமான இடத்திற்கு செல்லவும்.',
  },
}

function renderWithProviders() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlertComposer />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AlertComposer', () => {
  it('renders the real CAP-XML and the default-language human preview once loaded', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => REAL_ALERT, text: async () => '' })),
    )
    renderWithProviders()

    await waitFor(() => expect(screen.getByTestId('cap-xml-viewer')).toBeInTheDocument())
    expect(screen.getByTestId('cap-xml-viewer').textContent).toContain('<severity>Extreme</severity>')
    expect(screen.getByTestId('citizen-preview-text').textContent).toContain('Move to higher ground')
  })

  it('switches the human preview when a real language tab is clicked', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => REAL_ALERT, text: async () => '' })),
    )
    renderWithProviders()

    await waitFor(() => expect(screen.getByTestId('alert-language-tabs')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Tamil' }))
    expect(screen.getByTestId('citizen-preview-text').textContent).toContain('உயரமான இடத்திற்கு')
  })

  it('shows a real, clearly-labeled demonstration confirmation on Dispatch -- never claims a real send', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => REAL_ALERT, text: async () => '' })),
    )
    renderWithProviders()

    await waitFor(() => expect(screen.getByTestId('dispatch-button')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('dispatch-button'))
    await waitFor(() => expect(screen.getByTestId('dispatch-confirmation')).toBeInTheDocument())
    expect(screen.getByTestId('dispatch-confirmation').textContent).toMatch(/demonstration only/i)
  })

  it('shows a real error, not fabricated alert content, when the fetch fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}), text: async () => 'unavailable' })),
    )
    renderWithProviders()

    await waitFor(() => expect(screen.getByText(/Alert unavailable/)).toBeInTheDocument())
    expect(screen.queryByTestId('cap-xml-viewer')).not.toBeInTheDocument()
  })
})
