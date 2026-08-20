import { useQuery } from '@tanstack/react-query'
import { fetchAlert, queryKeys } from './api/client'

const SITE_ID = import.meta.env.VITE_SITE_ID ?? 'vit-vellore'

/**
 * T4B.0 connectivity probe.
 *
 * Deliberately minimal: this exists to satisfy T4B.0's own VERIFY step
 * ("a test API call to one real backend endpoint succeeds") against a
 * REAL running Stage 4 server, and to give the headless-screenshot
 * harness something real to capture. It is replaced by the real routed
 * pages in Section C (T4C.0 onward) — not a placeholder that quietly
 * ships.
 */
export default function App() {
  const { data, error, isLoading } = useQuery({
    queryKey: queryKeys.alert(SITE_ID),
    queryFn: () => fetchAlert(SITE_ID),
  })

  return (
    <main
      style={{ background: 'var(--ops-bg)', color: 'var(--ops-text)' }}
      className="min-h-full p-8 font-sans"
    >
      <h1 className="text-2xl font-semibold">Hyper-Local Flood Prediction</h1>
      <p style={{ color: 'var(--ops-text-dim)' }} className="mt-1 text-sm">
        T4B.0 backend connectivity probe — site <code>{SITE_ID}</code>
      </p>

      {isLoading && <p className="mt-6" data-testid="status">Loading real alert from Stage 4…</p>}

      {error && (
        <pre
          data-testid="status"
          style={{ background: 'var(--ops-panel)', border: '1px solid var(--sev-critical)' }}
          className="mt-6 overflow-auto rounded p-4 text-sm"
        >
          {String(error)}
        </pre>
      )}

      {data && (
        <section
          data-testid="status"
          style={{ background: 'var(--ops-panel)', border: '1px solid var(--ops-border)' }}
          className="mt-6 rounded p-4"
        >
          <p className="text-sm">
            <strong>Live Stage 4 alert fetched.</strong>
          </p>
          <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
            <dt style={{ color: 'var(--ops-text-dim)' }}>id</dt>
            <dd>{data.id}</dd>
            <dt style={{ color: 'var(--ops-text-dim)' }}>severity</dt>
            <dd>{data.severity}</dd>
            <dt style={{ color: 'var(--ops-text-dim)' }}>urgency</dt>
            <dd>{data.urgency}</dd>
            <dt style={{ color: 'var(--ops-text-dim)' }}>certainty</dt>
            <dd>{data.certainty}</dd>
            <dt style={{ color: 'var(--ops-text-dim)' }}>languages</dt>
            <dd>{Object.keys(data.text_by_language).join(', ')}</dd>
          </dl>
          <p className="mt-4 text-sm" style={{ color: 'var(--ops-text-dim)' }}>
            English alert text:
          </p>
          <pre className="mt-1 whitespace-pre-wrap text-sm">{data.text_by_language.en}</pre>
        </section>
      )}
    </main>
  )
}
