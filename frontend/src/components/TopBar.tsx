/**
 * TopBar — the Dashboard's top strip (T4C.1, User Flow §3.2): "Site
 * name, the four-state severity badge (Section 1), a countdown-style
 * 'time to peak scenario' readout, and a language selector (affects only
 * citizen-facing text previews, not the operational UI itself, which
 * stays in the operator's working language)."
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import BackLink from './BackLink'

import { LANGUAGES } from '../languages'
import { severityForEntry, type SeverityState } from '../severity'
import { useSceneStore } from '../store/sceneStore'
import SeverityBadge from './SeverityBadge'

export interface TopBarProps {
  siteName: string
}

export function TopBar({ siteName }: TopBarProps) {
  const damageRanking = useSceneStore((s) => s.damageRanking)
  const currentHour = useSceneStore((s) => s.currentHour)
  const [language, setLanguage] = useState('en')

  const maxRiskScore = damageRanking.reduce((max, entry) => Math.max(max, entry.risk_score), 0)
  let worstSeverity: SeverityState = 'Monitoring'
  let peakHour: number | null = null
  for (const entry of damageRanking) {
    const severity = severityForEntry(entry, currentHour, maxRiskScore)
    const order: SeverityState[] = ['Monitoring', 'Watch', 'Warning', 'Critical']
    if (order.indexOf(severity) >= order.indexOf(worstSeverity)) {
      worstSeverity = severity
      peakHour = entry.peak_hour
    }
  }

  const timeToPeakLabel =
    peakHour === null
      ? 'no scenario ranked'
      : peakHour > currentHour
        ? `T-${peakHour - currentHour}h to peak scenario`
        : 'Peak scenario reached'

  return (
    <header
      data-testid="dashboard-topbar"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '0.5rem 1rem',
        borderBottom: '3px solid var(--pixel-border)',
        background: 'var(--pixel-bg-1)',
      }}
    >
      <BackLink to="/" label="Flood Watch" />
      <h1 className="font-pixel-display" style={{ fontSize: '0.9rem', margin: 0 }}>
        {siteName}
      </h1>
      <SeverityBadge state={worstSeverity} />
      <span className="font-data" style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)' }}>
        {timeToPeakLabel}
      </span>
      <Link
        to="/dashboard/alert"
        className="font-pixel-body"
        style={{ marginLeft: 'auto', color: 'var(--pixel-accent)', fontSize: '1.1rem' }}
      >
        Compose Alert ▸
      </Link>
      <select
        aria-label="Citizen text preview language"
        value={language}
        onChange={(event) => setLanguage(event.target.value)}
        className="font-data"
        style={{
          background: 'var(--pixel-bg-2)',
          color: 'var(--ops-text)',
          border: '2px solid var(--pixel-border)',
          borderRadius: 0,
          padding: '0.3em 0.5em',
        }}
      >
        {LANGUAGES.map((lang) => (
          <option key={lang.code} value={lang.code}>
            {lang.label}
          </option>
        ))}
      </select>
    </header>
  )
}

export default TopBar
