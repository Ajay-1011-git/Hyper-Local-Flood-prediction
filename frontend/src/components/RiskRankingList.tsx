/**
 * RiskRankingList — the Dashboard's right column (T4C.1, User Flow
 * §3.2): "A vertically scrolling list, each row showing: structure
 * name/ID, a small colored risk chip ..., a confidence percentage, and a
 * one-line hazard summary ... Rows are sorted by risk descending by
 * default. Clicking a row navigates to Site Detail (3.3) and
 * simultaneously highlights that structure in the 3D scene — the two
 * views are always cross-linked, never independent."
 *
 * Reads the scene store directly (`damageRanking`/`currentHour`), the
 * same real data `DamageOverlay.tsx` (T4B.7) already colors the 3D scene
 * from — one real source feeding both views, which is what makes them
 * "always cross-linked, never independent" true rather than aspirational.
 */

import { useNavigate } from 'react-router-dom'

import type { SimulationScenario } from '../api/client'

import { severityForEntry } from '../severity'
import { useSceneStore } from '../store/sceneStore'
import PixelPanel from './pixel/PixelPanel'
import SeverityBadge from './SeverityBadge'
import { confidencePercent, hazardSummary } from './riskSummary'

export interface RiskRankingListProps {
  /** Which of Stage 2's two real simulations this ranking was computed
   *  from — shown in the header so a ranking can never be read as
   *  belonging to the other scenario. */
  scenario?: SimulationScenario
}

export function RiskRankingList({ scenario = 'real' }: RiskRankingListProps) {
  const damageRanking = useSceneStore((s) => s.damageRanking)
  const currentHour = useSceneStore((s) => s.currentHour)
  const highlightedStructureId = useSceneStore((s) => s.highlightedStructureId)
  const setHighlightedStructure = useSceneStore((s) => s.setHighlightedStructure)
  const navigate = useNavigate()

  const maxRiskScore = damageRanking.reduce((max, entry) => Math.max(max, entry.risk_score), 0)
  // Real risk_score descending, per the doc's own default sort -- not
  // trusting `rank` alone, since it's only guaranteed monotonic with
  // risk_score, not necessarily identical ordering after any client-side
  // filtering this list might grow later.
  const sorted = [...damageRanking].sort((a, b) => b.risk_score - a.risk_score)

  const selectRow = (structureId: string) => {
    setHighlightedStructure(structureId)
    navigate(`/dashboard/site/${encodeURIComponent(structureId)}`)
  }

  return (
    <div
      data-testid="risk-ranking-list"
      style={{ width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto' }}
    >
      <h2 className="font-pixel-body" style={{ fontSize: '1.3rem', margin: 0 }}>
        Risk ranking
      </h2>
      {/* States plainly that this is DOWNSTREAM of the simulation --
          Stage 3 reads hazard out of Stage 2's SimulationResult, so a
          ranking only exists once that simulation does. */}
      <p
        data-testid="ranking-provenance"
        className="font-data"
        style={{ fontSize: '0.78rem', color: 'var(--ops-text-dim)', margin: 0, lineHeight: 1.4 }}
      >
        Computed from the {scenario === 'heavy' ? 'heavy-rain (hypothetical)' : 'real forecast'}{' '}
        simulation.
      </p>
      {sorted.length === 0 && (
        <p className="font-data" style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)' }}>
          Run the simulation first — the ranking is computed from its output.
        </p>
      )}
      {sorted.map((entry) => {
        const severity = severityForEntry(entry, currentHour, maxRiskScore)
        const isHighlighted = entry.structure_id === highlightedStructureId
        return (
          <PixelPanel
            key={entry.structure_id}
            testId={`risk-row-${entry.structure_id}`}
            className="font-data"
            style={{
              padding: '0.5rem 0.65rem',
              cursor: 'pointer',
              outline: isHighlighted ? '2px solid var(--pixel-glow)' : 'none',
              outlineOffset: 2,
            }}
          >
            <button
              type="button"
              onClick={() => selectRow(entry.structure_id)}
              style={{
                all: 'unset',
                display: 'block',
                width: '100%',
                cursor: 'pointer',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{entry.structure_id}</span>
                <SeverityBadge state={severity} />
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--ops-text-dim)', marginTop: 4 }}>
                {confidencePercent(entry)}% confidence
              </div>
              <div style={{ fontSize: '0.8rem', marginTop: 2 }}>{hazardSummary(entry)}</div>
            </button>
          </PixelPanel>
        )
      })}
    </div>
  )
}

export default RiskRankingList
