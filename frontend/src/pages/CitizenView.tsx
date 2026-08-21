/**
 * Citizen Alert View (`/citizen`) — T4C.4.
 *
 * Per User Flow §3.5: "A completely different visual register from the
 * dashboard — light background, large type, minimal chrome," single
 * column, mobile-first: (1) a full-width status band with a plain-
 * language headline, (2) a simplified map, (3) three-to-five numbered
 * action steps in large type, (4) a prominent top-of-screen language
 * selector, (5) a "Share with family" button. "Deliberately absent:
 * confidence percentages, ensemble counts, hazard breakdowns —
 * anything that would require interpretation."
 *
 * REAL DATA, ZERO INTERPRETATION REQUIRED
 * ---------------------------------------------------------------
 * Fetches the SAME real Stage 4 `GET /api/alert/{site_id}` the Alert
 * Composer (T4C.3) does — this page renders it in the citizen register
 * rather than a separate mockup, matching that page's own "this is a
 * live preview of the Citizen View, provably what gets sent" claim.
 * Deliberately does NOT show `certainty`, `area_polygon` coordinates, or
 * any hazard/exposure/vulnerability breakdown — only the plain-language
 * headline + numbered steps `citizenAlertText.ts` parses from the real
 * `text_by_language` string, and the shaded area map.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { ApiError, fetchActiveAlert, queryKeys } from '../api/client'
import BackLink from '../components/BackLink'
import SimplifiedMap from '../components/SimplifiedMap'
import { parseAlertText } from '../citizenAlertText'
import { LANGUAGES } from '../languages'
import { SEVERITY_COLORS, capSeverityToUiSeverity } from '../severity'

const SITE_ID = import.meta.env.VITE_SITE_ID ?? 'vit-vellore'

type ShareState = 'idle' | 'shared' | 'copied' | 'failed'

export function CitizenView() {
  // Reads the ACTIVE alert, not the draft. A 404 here is the real, common
  // and entirely correct "no warning is in effect" state -- rendered below
  // as an explicit all-clear, never as an error and never as a blank page.
  const { data: alert, error, isPending } = useQuery({
    queryKey: queryKeys.activeAlert(SITE_ID),
    queryFn: () => fetchActiveAlert(SITE_ID),
    // Re-check periodically: a citizen leaving this page open needs to
    // see a newly-issued (or withdrawn) alert without reloading.
    refetchInterval: 30_000,
    retry: false,
  })
  const noActiveAlert = error instanceof ApiError && error.status === 404

  const [language, setLanguage] = useState<string | null>(null)
  const [shareState, setShareState] = useState<ShareState>('idle')

  const availableLanguages = alert ? LANGUAGES.filter((lang) => lang.code in alert.text_by_language) : []
  const activeLanguage =
    language && availableLanguages.some((l) => l.code === language) ? language : (availableLanguages[0]?.code ?? 'en')
  const parsed = alert ? parseAlertText(alert.text_by_language[activeLanguage] ?? '') : null
  const uiSeverity = alert ? capSeverityToUiSeverity(alert.severity) : 'Monitoring'

  const handleShare = async () => {
    const shareText = parsed ? `${parsed.headline}\n${window.location.href}` : window.location.href
    if (navigator.share) {
      try {
        await navigator.share({ title: 'Flood Watch alert', text: parsed?.headline, url: window.location.href })
        setShareState('shared')
        return
      } catch {
        // Real user cancellation or a real share failure -- fall through
        // to the clipboard fallback rather than silently doing nothing.
      }
    }
    try {
      await navigator.clipboard.writeText(shareText)
      setShareState('copied')
    } catch {
      setShareState('failed')
    }
  }

  return (
    <main
      style={{
        minHeight: '100vh',
        background: 'var(--citizen-bg)',
        color: 'var(--citizen-text)',
        display: 'flex',
        flexDirection: 'column',
      }}
      className="font-sans"
    >
      {/* Prominent, top-of-screen language selector -- "since language
          accessibility is a core requirement, not an afterthought." */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 1rem' }}>
        <BackLink to="/" label="Flood Watch" tone="light" />
        {availableLanguages.length > 0 && (
          <select
            aria-label="Language"
            value={activeLanguage}
            onChange={(event) => setLanguage(event.target.value)}
            className="font-pixel-body"
            data-testid="citizen-language-select"
            style={{
              fontSize: '1.1rem',
              padding: '0.4em 0.6em',
              background: 'var(--citizen-panel)',
              color: 'var(--citizen-text)',
              border: '2px solid var(--citizen-border)',
              borderRadius: 0,
            }}
          >
            {availableLanguages.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {isPending && (
        <p className="font-pixel-body" style={{ padding: '0 1rem', fontSize: '1.2rem' }}>
          Loading the current alert…
        </p>
      )}
      {noActiveAlert && (
        <div data-testid="citizen-all-clear" style={{ padding: '1rem' }}>
          <div
            style={{
              background: 'var(--citizen-panel)',
              border: '2px solid var(--citizen-border)',
              padding: '1.25rem 1rem',
            }}
          >
            <h1 className="font-pixel-body" style={{ fontSize: 'clamp(1.3rem, 5vw, 1.9rem)', margin: 0, lineHeight: 1.3 }}>
              No flood warning right now
            </h1>
            <p className="font-pixel-body" style={{ fontSize: '1.15rem', marginTop: '0.6rem', marginBottom: 0 }}>
              There is no flood warning in effect for this area. This page will
              update automatically if that changes.
            </p>
          </div>
          <Link
            to="/citizen/guidance"
            className="font-pixel-body"
            style={{ display: 'inline-block', marginTop: '1.25rem', color: 'var(--citizen-text-dim)', fontSize: '1rem' }}
          >
            General flood-safety guidance ▸
          </Link>
        </div>
      )}
      {error && !noActiveAlert && (
        <p className="font-pixel-body" style={{ padding: '0 1rem', fontSize: '1.2rem', color: 'var(--sev-critical)' }}>
          The alert isn't available right now. Please try again shortly.
        </p>
      )}

      {alert && parsed && (
        <>
          {/* 1. Full-width status band, plain-language headline. */}
          <div
            data-testid="citizen-status-band"
            style={{
              background: SEVERITY_COLORS[uiSeverity],
              color: '#0c0926',
              padding: '1.25rem 1rem',
            }}
          >
            <p className="font-pixel-body" style={{ fontSize: '1rem', margin: '0 0 0.25rem', fontWeight: 600 }}>
              {uiSeverity}
            </p>
            <h1
              className="font-pixel-body"
              style={{ fontSize: 'clamp(1.4rem, 5vw, 2rem)', margin: 0, lineHeight: 1.3 }}
            >
              {parsed.headline}
            </h1>
          </div>

          <div style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {/* 2. Simplified map. */}
            <SimplifiedMap areaPolygon={alert.area_polygon} />

            {/* 3. Numbered action steps, large type. */}
            {parsed.steps.length > 0 && (
              <ol data-testid="citizen-action-steps" style={{ margin: 0, paddingLeft: '1.4rem' }}>
                {parsed.steps.map((step, i) => (
                  <li key={i} className="font-pixel-body" style={{ fontSize: '1.4rem', marginBottom: '0.75rem' }}>
                    {step}
                  </li>
                ))}
              </ol>
            )}

            {/* 5. Share with family. */}
            <button
              type="button"
              onClick={handleShare}
              data-testid="share-with-family-button"
              className="pixel-button pixel-button--light"
              style={{ fontSize: '1.2rem', alignSelf: 'flex-start' }}
            >
              Share with family
            </button>
            {shareState === 'shared' && (
              <p className="font-pixel-body" style={{ color: 'var(--citizen-text-dim)' }}>
                Shared.
              </p>
            )}
            {shareState === 'copied' && (
              <p className="font-pixel-body" style={{ color: 'var(--citizen-text-dim)' }}>
                Link copied — paste it to share.
              </p>
            )}
            {shareState === 'failed' && (
              <p className="font-pixel-body" style={{ color: 'var(--sev-critical)' }}>
                Couldn't share or copy the link.
              </p>
            )}

            <Link to="/citizen/guidance" className="font-pixel-body" style={{ color: 'var(--citizen-text-dim)', fontSize: '1rem' }}>
              General flood-safety guidance ▸
            </Link>
          </div>
        </>
      )}
    </main>
  )
}

export default CitizenView
