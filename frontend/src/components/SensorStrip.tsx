/**
 * SensorStrip — the Dashboard's bottom bar (T4C.1, User Flow §3.2): "A
 * slim, persistent bar: a connection-status dot ..., the sensor's last
 * reading, and ... a clearly labeled 'Simulate live reading' affordance
 * sitting right next to the real hardware input path, so the same UI
 * acts identically whether the reading comes from the physical device or
 * the rehearsed fallback (Section 7 of the TRD)."
 *
 * REAL HARDWARE STATUS, NOT ASSUMED
 * ---------------------------------------------------------------
 * The physical ESP32 + HC-SR04 sensor is confirmed in hand as of
 * 2026-08-21 but not yet wired/flashed (project owner, this session) —
 * so in this environment "the real hardware input path" has never
 * actually sent a reading; every real reading this strip can show comes
 * through "Simulate live reading" until that connection work happens.
 * This button calls Stage 2's REAL `/api/simulation/assimilate` endpoint
 * (not a fabricated local state update) — a real 503/network failure
 * surfaces as a real error, per this project's honesty rules.
 */

import { useEffect, useRef, useState } from 'react'

import { postSimulationAssimilate } from '../api/client'
import type { SensorReading } from '../api/types'
import { useSceneStore } from '../store/sceneStore'
import PixelButton from './pixel/PixelButton'
import PixelPanel from './pixel/PixelPanel'

export interface SensorStripProps {
  siteId: string
}

/** A plausible HC-SR04 distance reading for the demo sensor mount — a
 *  real value shape, not claiming to BE a live physical measurement. */
function syntheticDistanceCm(): number {
  return Math.round((80 + Math.random() * 40) * 10) / 10
}

export function SensorStrip({ siteId }: SensorStripProps) {
  const connectionStatus = useSceneStore((s) => s.connectionStatus)
  const lastSensorAssimilation = useSceneStore((s) => s.lastSensorAssimilation)
  const [isSimulating, setIsSimulating] = useState(false)
  const [simulateError, setSimulateError] = useState<string | null>(null)
  const [flash, setFlash] = useState(false)
  const lastTimestampRef = useRef<string | null>(null)

  useEffect(() => {
    if (!lastSensorAssimilation) return
    if (lastSensorAssimilation.timestamp === lastTimestampRef.current) return
    lastTimestampRef.current = lastSensorAssimilation.timestamp
    setFlash(true)
    const timer = setTimeout(() => setFlash(false), 1200)
    return () => clearTimeout(timer)
  }, [lastSensorAssimilation])

  const handleSimulate = async () => {
    setIsSimulating(true)
    setSimulateError(null)
    const reading: SensorReading = {
      sensor_id: 'demo-sensor-01',
      site_id: siteId,
      distance_cm: syntheticDistanceCm(),
      timestamp: new Date().toISOString(),
      assimilated: false,
    }
    try {
      await postSimulationAssimilate(reading)
      // The real `sensor_assimilated` WS broadcast (T4B.6's useSiteSocket)
      // is what actually updates the store -- this call just triggers
      // the real backend event, it never sets store state itself.
    } catch (error) {
      setSimulateError(error instanceof Error ? error.message : 'Simulate reading failed.')
    } finally {
      setIsSimulating(false)
    }
  }

  const dotColor = connectionStatus === 'open' ? '#3fb950' : '#6b7280'

  return (
    <PixelPanel
      testId="sensor-strip"
      className="font-data"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '0.5rem 1rem',
        transition: 'background-color 200ms ease-out',
        backgroundColor: flash ? 'var(--pixel-accent)' : undefined,
      }}
    >
      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          aria-hidden="true"
          style={{ width: 10, height: 10, borderRadius: '50%', background: dotColor, display: 'inline-block' }}
        />
        <span style={{ fontSize: '0.85rem' }}>WS {connectionStatus}</span>
      </span>

      <span style={{ fontSize: '0.85rem', color: 'var(--ops-text-dim)' }}>
        {lastSensorAssimilation
          ? `Last reading: sensor ${lastSensorAssimilation.sensorId} — ${lastSensorAssimilation.distanceCm}cm at ${new Date(lastSensorAssimilation.timestamp).toLocaleTimeString()}`
          : 'No sensor reading yet.'}
      </span>

      <PixelButton
        variant="primary"
        onClick={handleSimulate}
        disabled={isSimulating}
        style={{ marginLeft: 'auto', fontSize: '0.9rem' }}
      >
        {isSimulating ? 'Simulating…' : 'Simulate live reading'}
      </PixelButton>

      {simulateError && (
        <span style={{ fontSize: '0.8rem', color: 'var(--sev-critical)' }}>{simulateError}</span>
      )}
    </PixelPanel>
  )
}

export default SensorStrip
