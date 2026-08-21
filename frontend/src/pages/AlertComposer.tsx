/**
 * Alert Composer & Dispatch (`/dashboard/alert`) — T4C.3.
 *
 * Per User Flow §3.4: "the moment the ranked model output becomes a
 * real, sendable message." Two-column split — real raw CAP-XML on the
 * left (`CapXmlViewer.tsx`), a tabbed human-language preview on the
 * right — plus a "Dispatch" action explicitly labeled as a
 * demonstration, never a real send.
 *
 * REAL DATA, ONE HONEST MAPPING DISCLOSED
 * ---------------------------------------------------------------
 * Fetches Stage 4's real `GET /api/alert/{site_id}` (`cap_generator.py`
 * + `multilingual.py`'s actual output — never fabricated here). The one
 * translation this component does itself: `Alert.severity` is a real CAP
 * enum value (Extreme/Severe/Moderate/Minor/Unknown —
 * `cap_generator.py::derive_severity`), NOT this app's own four-state UI
 * vocabulary (Monitoring/Watch/Warning/Critical, `severity.ts`). The
 * preview's status band maps CAP -> UI vocabulary for display, a
 * disclosed approximation of what the real Citizen View (T4C.4) shows —
 * both import the SAME `severity.ts::capSeverityToUiSeverity` mapping,
 * never presented as if it were CAP's own severity field.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  fetchActiveAlert,
  fetchAlert,
  issueAlert,
  queryKeys,
  withdrawAlert,
} from '../api/client'
import BackLink from '../components/BackLink'
import CapXmlViewer from '../components/CapXmlViewer'
import PixelButton from '../components/pixel/PixelButton'
import PixelPanel from '../components/pixel/PixelPanel'
import { LANGUAGES } from '../languages'
import { SEVERITY_COLORS, capSeverityToUiSeverity } from '../severity'

const SITE_ID = import.meta.env.VITE_SITE_ID ?? 'vit-vellore'

type DispatchState = 'idle' | 'sending' | 'sent'

export function AlertComposer() {
  const {
    data: alert,
    error,
    isPending,
  } = useQuery({
    queryKey: queryKeys.alert(SITE_ID),
    queryFn: () => fetchAlert(SITE_ID),
    staleTime: Infinity,
    retry: false,
  })

  const queryClient = useQueryClient()

  // Is a warning currently in effect for the public? A 404 is the real
  // "nothing issued" answer, not an error.
  const { data: activeAlert, error: activeError } = useQuery({
    queryKey: queryKeys.activeAlert(SITE_ID),
    queryFn: () => fetchActiveAlert(SITE_ID),
    retry: false,
  })
  const isActive = Boolean(activeAlert) && !(activeError instanceof ApiError)

  const invalidateActive = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.activeAlert(SITE_ID) })
  }
  const issue = useMutation({ mutationFn: () => issueAlert(SITE_ID), onSuccess: invalidateActive })
  const withdraw = useMutation({
    mutationFn: () => withdrawAlert(SITE_ID),
    onSuccess: invalidateActive,
  })

  const [selectedLanguage, setSelectedLanguage] = useState<string | null>(null)
  const [dispatchState, setDispatchState] = useState<DispatchState>('idle')

  const availableLanguages = alert
    ? LANGUAGES.filter((lang) => lang.code in alert.text_by_language)
    : []
  const activeLanguage =
    selectedLanguage && availableLanguages.some((l) => l.code === selectedLanguage)
      ? selectedLanguage
      : (availableLanguages[0]?.code ?? 'en')

  const handleDispatch = () => {
    setDispatchState('sending')
    // Real, explicitly-labeled SIMULATION (User Flow §3.4's own words:
    // "triggers a simulated send with a success confirmation, explicitly
    // labeled as a demonstration action rather than a real integration")
    // -- no real dispatch endpoint exists or is called here.
    setTimeout(() => setDispatchState('sent'), 500)
  }

  return (
    <div
      style={{ minHeight: '100vh', background: 'var(--ops-bg)', color: 'var(--ops-text)', padding: '1.5rem' }}
      className="font-sans"
    >
      <BackLink to="/dashboard" label="Back to Dashboard" style={{ color: 'var(--pixel-accent)', fontSize: '1.1rem' }} />
      <h1 className="font-pixel-display" style={{ fontSize: '1.1rem', margin: '1rem 0' }}>
        Alert Composer
      </h1>

      {isPending && (
        <p className="font-data" style={{ color: 'var(--ops-text-dim)' }}>
          Loading real alert…
        </p>
      )}
      {error && (
        <p className="font-data" style={{ color: 'var(--sev-critical)' }}>
          Alert unavailable: {error instanceof Error ? error.message : String(error)}
        </p>
      )}

      {alert && (
        <>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <PixelPanel style={{ flex: '1 1 420px', padding: '1rem', minWidth: 0 }}>
              <h2 className="font-pixel-body" style={{ fontSize: '1.2rem', margin: '0 0 0.75rem' }}>
                Raw CAP-XML
              </h2>
              <CapXmlViewer xml={alert.cap_xml} />
            </PixelPanel>

            <PixelPanel variant="light" style={{ flex: '1 1 380px', padding: '1rem', minWidth: 0 }}>
              <h2 className="font-pixel-body" style={{ fontSize: '1.2rem', margin: '0 0 0.75rem' }}>
                Human preview — citizen view
              </h2>

              <div
                data-testid="alert-language-tabs"
                style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: '0.75rem' }}
              >
                {availableLanguages.map((lang) => (
                  <button
                    key={lang.code}
                    type="button"
                    onClick={() => setSelectedLanguage(lang.code)}
                    className="pixel-button pixel-button--light"
                    style={{
                      fontSize: '0.8rem',
                      padding: '0.3em 0.6em',
                      outline: activeLanguage === lang.code ? '2px solid var(--citizen-border)' : 'none',
                    }}
                  >
                    {lang.label}
                  </button>
                ))}
              </div>

              <div
                data-testid="citizen-preview-band"
                style={{
                  background: SEVERITY_COLORS[capSeverityToUiSeverity(alert.severity)],
                  color: '#0c0926',
                  padding: '0.5em 0.75em',
                  marginBottom: '0.75rem',
                  fontWeight: 600,
                }}
                className="font-data"
              >
                CAP {alert.severity} · {alert.urgency} · {Math.round(alert.certainty * 100)}% certainty
              </div>

              <p
                data-testid="citizen-preview-text"
                className="font-pixel-body"
                style={{ whiteSpace: 'pre-wrap', color: 'var(--citizen-text)', fontSize: '1.15rem', margin: 0 }}
              >
                {alert.text_by_language[activeLanguage] ?? 'No preview text for this language.'}
              </p>
            </PixelPanel>
          </div>

          {/* ISSUE / WITHDRAW -- the real public-facing decision.
              Everything above this point is a DRAFT: it is derived
              automatically from the current simulation, and the Citizen
              View shows none of it until a person here decides to issue
              it. That decision is deliberately a separate, explicit,
              reversible action rather than something a simulation can
              trigger on its own. */}
          <div
            data-testid="alert-issuance"
            style={{
              marginTop: '1.5rem',
              padding: '0.9rem 1rem',
              border: '2px solid var(--pixel-border, #4b4788)',
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            <div className="font-data" style={{ fontSize: '0.95rem' }}>
              {isActive ? (
                <span data-testid="alert-status-active" style={{ color: 'var(--sev-warning)' }}>
                  ● This alert is LIVE on the public Citizen View.
                </span>
              ) : (
                <span data-testid="alert-status-inactive" style={{ color: 'var(--ops-text-dim)' }}>
                  ○ Draft only — nothing is published to the public right now.
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <PixelButton
                variant="primary"
                data-testid="issue-alert-button"
                disabled={issue.isPending}
                onClick={() => issue.mutate()}
              >
                {issue.isPending ? 'Issuing…' : isActive ? 'Re-issue alert' : 'Issue alert to public ▸'}
              </PixelButton>
              <PixelButton
                data-testid="withdraw-alert-button"
                disabled={!isActive || withdraw.isPending}
                onClick={() => withdraw.mutate()}
              >
                {withdraw.isPending ? 'Withdrawing…' : 'Withdraw alert'}
              </PixelButton>
            </div>
            {(issue.isError || withdraw.isError) && (
              <p className="font-data" style={{ color: 'var(--sev-critical)', margin: 0, fontSize: '0.9rem' }}>
                {(issue.error ?? withdraw.error) instanceof Error
                  ? ((issue.error ?? withdraw.error) as Error).message
                  : 'Action failed.'}
              </p>
            )}
          </div>

          <div style={{ marginTop: '1.5rem' }}>
            <PixelButton
              variant="primary"
              onClick={handleDispatch}
              disabled={dispatchState === 'sending'}
              data-testid="dispatch-button"
            >
              {dispatchState === 'sending' ? 'Dispatching…' : 'Dispatch (simulated)'}
            </PixelButton>
            {dispatchState === 'sent' && (
              <p
                data-testid="dispatch-confirmation"
                className="font-data"
                style={{ color: 'var(--sev-monitoring)', marginTop: '0.5rem' }}
              >
                ✓ Simulated dispatch sent — demonstration only, no real message was sent.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default AlertComposer
