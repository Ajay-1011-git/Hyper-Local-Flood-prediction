/**
 * Simulation controls — picks which real Stage 2 simulation the scene and
 * the risk ranking are showing, and runs one on demand.
 *
 * TWO REAL SIMULATIONS, NEVER BLURRED TOGETHER
 * ---------------------------------------------------------------
 * Stage 2 computes two genuinely separate simulations for this site (see
 * its own `precompute.py` docstring), and this component's whole job is
 * to make which one you are looking at unmissable:
 *
 *   - "Real forecast"  — the honest current answer, driven by Stage 1B's
 *     real downscaled GEFS ensemble. For this site right now that really
 *     is very little rain, and the scene really does show almost no
 *     water. That is a correct result, so this component says so rather
 *     than letting an empty-looking scene read as a failure.
 *
 *   - "Heavy rain"     — a HYPOTHETICAL at a real, cited IMD rainfall
 *     category. It is never labelled as a forecast, always carries the
 *     word "hypothetical", and reports the real factor it scaled the
 *     real forecast by, so nobody can mistake it for what is coming.
 *
 * WHY A RUN BUTTON AND A PROGRESS BAR
 * ---------------------------------------------------------------
 * A real run is ~1-2 minutes of real physics (the numerical solver that
 * generates the GNN's training data dominates it). Stage 2 therefore
 * returns 202 immediately and exposes real progress, which this polls —
 * rather than pretending a long computation is instant.
 */

import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  fetchPrecomputeStatus,
  fetchSimulationProvenance,
  queryKeys,
  startPrecompute,
  type SimulationScenario,
} from '../api/client'
import PixelButton from './pixel/PixelButton'
import PixelPanel from './pixel/PixelPanel'

export interface SimulationControlsProps {
  siteId: string
  scenario: SimulationScenario
  onScenarioChange: (scenario: SimulationScenario) => void
}

export function SimulationControls({
  siteId,
  scenario,
  onScenarioChange,
}: SimulationControlsProps) {
  const queryClient = useQueryClient()

  const { data: status } = useQuery({
    queryKey: queryKeys.precomputeStatus(siteId, scenario),
    queryFn: () => fetchPrecomputeStatus(siteId, scenario),
    // Poll only while a real run is in flight — no busy-polling an idle
    // server just to redraw an unchanged bar.
    refetchInterval: (query) =>
      query.state.data?.state === 'running' ? 2000 : false,
    retry: false,
  })

  const { data: provenance } = useQuery({
    queryKey: queryKeys.simulationProvenance(siteId, scenario),
    queryFn: () => fetchSimulationProvenance(siteId, scenario),
    enabled: status?.state === 'done',
    staleTime: Infinity,
    retry: false,
  })

  // When a run finishes, the stored simulation and everything derived
  // from it (the ranking, which is computed FROM this simulation) are
  // genuinely new — refetch rather than showing the previous run's water
  // under the new run's label.
  useEffect(() => {
    if (status?.state !== 'done') return
    queryClient.invalidateQueries({ queryKey: queryKeys.simulation(siteId, scenario) })
    queryClient.invalidateQueries({ queryKey: queryKeys.damageRanking(siteId) })
  }, [status?.state, siteId, scenario, queryClient])

  const run = useMutation({
    mutationFn: () => startPrecompute(siteId, scenario),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.precomputeStatus(siteId, scenario) })
    },
  })

  const isRunning = status?.state === 'running' || run.isPending
  const isReady = status?.state === 'done'

  return (
    <PixelPanel
      testId="simulation-controls"
      className="font-pixel-body"
      style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}
    >
      <h2 style={{ fontSize: '1.2rem', margin: 0 }}>Simulation</h2>

      <div style={{ display: 'flex', gap: 6 }}>
        <PixelButton
          data-testid="scenario-real"
          variant={scenario === 'real' ? 'primary' : undefined}
          style={{ flex: 1, fontSize: '0.95rem', padding: '0.35em 0.4em' }}
          onClick={() => onScenarioChange('real')}
        >
          Real forecast
        </PixelButton>
        <PixelButton
          data-testid="scenario-heavy"
          variant={scenario === 'heavy' ? 'primary' : undefined}
          style={{ flex: 1, fontSize: '0.95rem', padding: '0.35em 0.4em' }}
          onClick={() => onScenarioChange('heavy')}
        >
          What if heavy rain?
        </PixelButton>
      </div>

      {scenario === 'heavy' && (
        <p
          data-testid="hypothetical-warning"
          style={{
            margin: 0,
            fontSize: '0.9rem',
            color: 'var(--sev-warning)',
            lineHeight: 1.35,
          }}
        >
          Hypothetical — not a forecast. Shows what this site would do under
          extremely heavy rain (IMD ≥204.5 mm/24h)
          {provenance?.rainfall_scale_factor
            ? `, ${provenance.rainfall_scale_factor}× the real forecast`
            : ''}
          .
        </p>
      )}

      {scenario === 'real' && isReady && (
        <p style={{ margin: 0, fontSize: '0.9rem', color: 'var(--ops-text-dim)', lineHeight: 1.35 }}>
          The real GEFS forecast. Little rain is expected here right now, so
          little flooding is a correct result — not a missing simulation.
        </p>
      )}

      {isRunning && (
        <div data-testid="precompute-progress">
          <p style={{ margin: '0 0 4px', fontSize: '0.9rem' }}>
            {status?.message ?? 'Starting'}…
          </p>
          <div
            style={{
              height: 8,
              background: 'var(--ops-panel-2, #1b1740)',
              border: '2px solid var(--pixel-border, #4b4788)',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${Math.round((status?.progress ?? 0) * 100)}%`,
                background: 'var(--pixel-accent)',
                transition: 'width 300ms linear',
              }}
            />
          </div>
        </div>
      )}

      {status?.state === 'failed' && (
        <p data-testid="precompute-failed" style={{ margin: 0, fontSize: '0.9rem', color: 'var(--sev-critical)' }}>
          Simulation failed: {status.detail ?? 'unknown error'}
        </p>
      )}

      {!isRunning && (
        <PixelButton
          data-testid="run-simulation"
          variant={isReady ? undefined : 'primary'}
          style={{ fontSize: '0.95rem' }}
          onClick={() => run.mutate()}
        >
          {isReady ? 'Re-run simulation' : 'Run simulation ▸'}
        </PixelButton>
      )}

      {provenance && (
        <p
          data-testid="simulation-provenance"
          style={{ margin: 0, fontSize: '0.82rem', color: 'var(--ops-text-dim)', lineHeight: 1.4 }}
        >
          {provenance.member_count} ensemble members over {provenance.node_count.toLocaleString()}{' '}
          mesh nodes at {provenance.grid_resolution_m} m.{' '}
          {provenance.engine === 'numerical_solver' ? (
            <>
              Computed by the <strong>numerical solver</strong> — the GNN emulator&apos;s
              rollout failed the mass-conservation check (held{' '}
              {provenance.mass_conservation_ratio}× the water that fell), so its
              output was discarded.
            </>
          ) : (
            <>
              Computed by the <strong>GNN emulator</strong>; depth error vs the numerical
              solver {provenance.validation_depth_mae_m} m.
            </>
          )}
        </p>
      )}
    </PixelPanel>
  )
}

export default SimulationControls
