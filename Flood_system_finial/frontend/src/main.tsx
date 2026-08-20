import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import './index.css'
import App from './App'

/**
 * `retry: false` deliberately: this project's backends either answer or
 * honestly fail (they never return fabricated fallback data on error),
 * so silently retrying a real failure would just hide a real outage
 * behind a spinner — exactly the opposite of this project's honesty
 * principles. A failed query should surface as a visible error state.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
