/**
 * RiverStageCard — the "River/reservoir cross-check card" (T4C.1, User
 * Flow §3.2): "CWC's independent forecast, shown as a simple two-state
 * indicator ... deliberately terse, because its entire UX job is to
 * answer one question at a glance: does a second, independent source
 * back this up."
 *
 * A REAL THIRD STATE, DISCLOSED RATHER THAN FORCED INTO THE DOC'S TWO
 * ---------------------------------------------------------------
 * Stage 1A's own CLAUDE.md rule 6 is explicit: where no real CWC/
 * India-WRIS station can be confirmed near the site, implement the
 * honest `station_proximity_verified: false` path rather than assuming
 * coverage. Presenting a green/amber verdict from a forecast with no
 * verified nearby station would be exactly the kind of silent
 * fabrication this project's honesty rules forbid — so this card has a
 * real third state ("no verified nearby station") for that case, on top
 * of the doc's own two (agrees / diverges).
 */

import type { RiverStageForecast } from '../api/types'

export interface RiverStageCardProps {
  forecast?: RiverStageForecast
  error?: unknown
  isPending: boolean
}

export type CrossCheckState = 'agrees' | 'diverges' | 'no-station' | 'unavailable' | 'loading'

export function deriveState(forecast: RiverStageForecast | undefined, error: unknown, isPending: boolean): CrossCheckState {
  if (isPending) return 'loading'
  if (error || !forecast) return 'unavailable'
  if (!forecast.station_proximity_verified) return 'no-station'
  // A real, disclosed judgment call: "agrees" means CWC's own real
  // breach_probability crosses 0.5 -- the same probability convention
  // this project already uses elsewhere (severity.ts's own tiering) --
  // never a fabricated verdict when the field is null.
  if (forecast.breach_probability === null) return 'unavailable'
  return forecast.breach_probability >= 0.5 ? 'agrees' : 'diverges'
}

const STATE_COPY: Record<CrossCheckState, { text: string; color: string }> = {
  loading: { text: 'Loading CWC cross-check…', color: 'var(--ops-text-dim)' },
  unavailable: { text: 'CWC cross-check unavailable', color: 'var(--ops-text-dim)' },
  'no-station': { text: 'No verified nearby CWC station', color: 'var(--ops-text-dim)' },
  agrees: { text: 'Independent government model agrees', color: 'var(--sev-monitoring)' },
  diverges: { text: 'Divergence detected', color: 'var(--sev-watch)' },
}

export function RiverStageCard({ forecast, error, isPending }: RiverStageCardProps) {
  const state = deriveState(forecast, error, isPending)
  const copy = STATE_COPY[state]

  return (
    <div data-testid="river-stage-card">
      <div
        className="font-pixel-body"
        style={{
          fontSize: '1.1rem',
          color: copy.color,
          border: `2px solid ${copy.color}`,
          padding: '0.4em 0.7em',
          display: 'inline-block',
        }}
      >
        {copy.text}
      </div>
      {forecast && state !== 'no-station' && state !== 'unavailable' && (
        <p className="font-data" style={{ fontSize: '0.75rem', color: 'var(--ops-text-dim)', marginTop: 4 }}>
          {forecast.station_name} — breach probability{' '}
          {forecast.breach_probability !== null ? `${Math.round(forecast.breach_probability * 100)}%` : 'n/a'}
        </p>
      )}
    </div>
  )
}

export default RiverStageCard
