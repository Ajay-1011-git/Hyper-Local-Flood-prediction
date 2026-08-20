/**
 * ForecastPanel — the Dashboard's left column (T4C.1, User Flow §3.2):
 * two stacked real cards, the regional ensemble fan chart and the CWC
 * river-stage cross-check.
 */

import { useQuery } from '@tanstack/react-query'

import { fetchRegionalForecast, fetchRiverStageForecast, queryKeys } from '../api/client'
import PixelPanel from './pixel/PixelPanel'
import EnsembleFanChart from './EnsembleFanChart'
import RiverStageCard from './RiverStageCard'

export interface ForecastPanelProps {
  siteLat: number
  siteLon: number
}

export function ForecastPanel({ siteLat, siteLon }: ForecastPanelProps) {
  const {
    data: regionalForecast,
    error: regionalError,
    isPending: regionalPending,
  } = useQuery({
    queryKey: queryKeys.regionalForecast,
    queryFn: fetchRegionalForecast,
    staleTime: Infinity,
    retry: false,
  })

  const {
    data: riverStageForecast,
    error: riverStageError,
    isPending: riverStagePending,
  } = useQuery({
    queryKey: queryKeys.riverStage(siteLat, siteLon),
    queryFn: () => fetchRiverStageForecast(siteLat, siteLon),
    staleTime: Infinity,
    retry: false,
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: 300, flexShrink: 0 }}>
      <PixelPanel style={{ padding: '0.75rem' }}>
        <h2 className="font-pixel-body" style={{ fontSize: '1.3rem', margin: '0 0 0.5rem' }}>
          Regional ensemble
        </h2>
        {regionalPending && (
          <p className="font-data" style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)' }}>
            Loading regional forecast…
          </p>
        )}
        {regionalError ? (
          <p className="font-data" style={{ fontSize: '0.85rem', color: 'var(--sev-critical)' }}>
            Regional forecast unavailable.
          </p>
        ) : null}
        {regionalForecast && <EnsembleFanChart forecast={regionalForecast} />}
      </PixelPanel>

      <PixelPanel style={{ padding: '0.75rem' }}>
        <h2 className="font-pixel-body" style={{ fontSize: '1.3rem', margin: '0 0 0.5rem' }}>
          River / reservoir cross-check
        </h2>
        <RiverStageCard forecast={riverStageForecast} error={riverStageError} isPending={riverStagePending} />
      </PixelPanel>
    </div>
  )
}

export default ForecastPanel
