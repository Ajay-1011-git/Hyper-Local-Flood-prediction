import { beforeEach, describe, expect, it } from 'vitest'
import { useSceneStore } from './sceneStore'
import type { DamageRankEntry, NodeState, SimulationResult, SiteSocketEvent } from '../api/types'

const INITIAL_STATE = useSceneStore.getState()

beforeEach(() => {
  useSceneStore.setState(INITIAL_STATE, true) // real reset between tests — a shared singleton store
})

function node(overrides: Partial<NodeState> = {}): NodeState {
  return {
    node_id: 'n_0_0',
    hour: 6,
    depth_mean_m: 0.5,
    depth_min_m: 0.4,
    depth_max_m: 0.6,
    velocity_mean_mps: 0.2,
    velocity_min_mps: 0.1,
    velocity_max_mps: 0.3,
    rate_of_rise: 0.05,
    ensemble_agreement_fraction: 0.7,
    building_id: null,
    road_segment_id: null,
    ...overrides,
  }
}

function simResult(nodeStates: NodeState[]): SimulationResult {
  return {
    simulation_id: 'sim-1',
    site_id: 'vit-vellore',
    source_forecast_id: 'forecast-1',
    generated_at: '2026-08-20T12:00:00Z',
    hazard_threshold_m: 0.3,
    validation_error_m: 0.02,
    node_states: nodeStates,
    envelope: { max_depth_m: 0.6 },
  }
}

describe('loadSimulationResult (real REST fetch, T4B.1 initial-state finding)', () => {
  it('indexes node states by hour and node_id', () => {
    useSceneStore.getState().loadSimulationResult(
      simResult([node({ hour: 6, node_id: 'n_0_0', depth_mean_m: 0.5 }), node({ hour: 12, node_id: 'n_0_0', depth_mean_m: 0.9 })]),
    )
    const state = useSceneStore.getState()
    expect(state.getNodeStateAt(6, 'n_0_0')?.depth_mean_m).toBe(0.5)
    expect(state.getNodeStateAt(12, 'n_0_0')?.depth_mean_m).toBe(0.9)
  })

  it('lands the timeline on the first real available hour, not a hardcoded 0', () => {
    useSceneStore.getState().loadSimulationResult(simResult([node({ hour: 6 }), node({ hour: 12 })]))
    expect(useSceneStore.getState().currentHour).toBe(6)
  })

  it('replaces (not merges) on a fresh load', () => {
    const store = useSceneStore.getState()
    store.loadSimulationResult(simResult([node({ hour: 6, node_id: 'old' })]))
    store.loadSimulationResult(simResult([node({ hour: 6, node_id: 'new' })]))
    expect(useSceneStore.getState().getNodeStateAt(6, 'old')).toBeUndefined()
    expect(useSceneStore.getState().getNodeStateAt(6, 'new')).toBeDefined()
  })

  it('stores the real envelope', () => {
    useSceneStore.getState().loadSimulationResult(simResult([node()]))
    expect(useSceneStore.getState().envelope).toEqual({ max_depth_m: 0.6 })
  })
})

describe("applySocketEvent — simulation_update (task's own required VERIFY)", () => {
  it("correctly updates the store's node state", () => {
    useSceneStore.getState().loadSimulationResult(simResult([node({ hour: 6, node_id: 'n_0_0', depth_mean_m: 0.5 })]))

    const event: SiteSocketEvent = {
      type: 'simulation_update',
      payload: {
        node_states: [node({ hour: 6, node_id: 'n_0_0', depth_mean_m: 1.2 })],
        envelope: { max_depth_m: 1.2 },
      },
    }
    useSceneStore.getState().applySocketEvent(event)

    const updated = useSceneStore.getState().getNodeStateAt(6, 'n_0_0')
    expect(updated?.depth_mean_m).toBe(1.2)
    expect(useSceneStore.getState().envelope).toEqual({ max_depth_m: 1.2 })
  })

  it('merges into existing state rather than discarding untouched nodes/hours', () => {
    useSceneStore.getState().loadSimulationResult(
      simResult([node({ hour: 6, node_id: 'n_a', depth_mean_m: 0.1 }), node({ hour: 6, node_id: 'n_b', depth_mean_m: 0.2 })]),
    )
    useSceneStore.getState().applySocketEvent({
      type: 'simulation_update',
      payload: { node_states: [node({ hour: 6, node_id: 'n_a', depth_mean_m: 9.9 })], envelope: {} },
    })
    const state = useSceneStore.getState()
    expect(state.getNodeStateAt(6, 'n_a')?.depth_mean_m).toBe(9.9) // updated
    expect(state.getNodeStateAt(6, 'n_b')?.depth_mean_m).toBe(0.2) // untouched, survived
  })

  it('adds a new hour to hoursAvailable if the update introduces one', () => {
    useSceneStore.getState().loadSimulationResult(simResult([node({ hour: 6 })]))
    useSceneStore.getState().applySocketEvent({
      type: 'simulation_update',
      payload: { node_states: [node({ hour: 12, node_id: 'n_new' })], envelope: {} },
    })
    expect(useSceneStore.getState().hoursAvailable).toEqual([6, 12])
  })
})

describe('applySocketEvent — sensor_assimilated', () => {
  it('merges real changed node states from a Stage 2-shaped event (updated_region set)', () => {
    useSceneStore.getState().loadSimulationResult(simResult([node({ hour: 6, node_id: 'n_0_0', depth_mean_m: 0.5 })]))
    useSceneStore.getState().applySocketEvent({
      type: 'sensor_assimilated',
      payload: {
        sensor_id: 'esp32-vellore-demo-01',
        new_reading: { sensor_id: 'esp32-vellore-demo-01', site_id: 'vit-vellore', distance_cm: 15, timestamp: '2026-08-20T12:00:00Z', assimilated: true },
        updated_region: { node_states: [node({ hour: 6, node_id: 'n_0_0', depth_mean_m: 0.35, ensemble_agreement_fraction: 1.0 })] },
      },
    })
    const state = useSceneStore.getState()
    expect(state.getNodeStateAt(6, 'n_0_0')?.depth_mean_m).toBe(0.35)
    expect(state.lastSensorAssimilation).toEqual({
      sensorId: 'esp32-vellore-demo-01',
      distanceCm: 15,
      timestamp: '2026-08-20T12:00:00Z',
      updatedNodeIds: ['n_0_0'],
    })
  })

  it('handles a Stage 1B-shaped event honestly (updated_region: null) without crashing', () => {
    // Real Stage 1B behavior, per that module's own comment: "no Stage 2
    // simulation exists yet" -- must not fabricate an updated node.
    useSceneStore.getState().applySocketEvent({
      type: 'sensor_assimilated',
      payload: {
        sensor_id: 'esp32-vellore-demo-01',
        new_reading: { sensor_id: 'esp32-vellore-demo-01', site_id: 'vit-vellore', distance_cm: 20, timestamp: '2026-08-20T12:00:00Z', assimilated: false },
        updated_region: null,
      },
    })
    expect(useSceneStore.getState().lastSensorAssimilation).toEqual({
      sensorId: 'esp32-vellore-demo-01',
      distanceCm: 20,
      timestamp: '2026-08-20T12:00:00Z',
      updatedNodeIds: [], // never fabricated
    })
  })
})

describe('applySocketEvent — ranking_update', () => {
  it('replaces the damage ranking wholesale', () => {
    const entries: DamageRankEntry[] = [
      {
        structure_id: 'Building_02', structure_type: 'building', site_id: 'vit-vellore',
        hazard_score: 6.1, exposure_score: 300, vulnerability_score: 0.8,
        vulnerability_source: 'real', vulnerability_is_local_calibration: false,
        risk_score: 1464, confidence: 0.7, rank: 1, peak_hour: 5,
        peak_depth_m: 1.8, peak_velocity_mps: 2.1, peak_rate_of_rise: 0.15,
      },
    ]
    useSceneStore.getState().applySocketEvent({ type: 'ranking_update', payload: entries })
    expect(useSceneStore.getState().damageRanking).toEqual(entries)
  })
})

describe('setCurrentHour / setDamageRanking / setConnectionStatus / getNodeStatesAtCurrentHour', () => {
  it('moves the scrubber to a real hour', () => {
    useSceneStore.getState().setCurrentHour(24)
    expect(useSceneStore.getState().currentHour).toBe(24)
  })

  it('setDamageRanking replaces the list directly (REST path, not a socket event)', () => {
    useSceneStore.getState().setDamageRanking([])
    expect(useSceneStore.getState().damageRanking).toEqual([])
  })

  it('tracks connection status from the WebSocket client', () => {
    useSceneStore.getState().setConnectionStatus('reconnecting')
    expect(useSceneStore.getState().connectionStatus).toBe('reconnecting')
  })

  it('getNodeStatesAtCurrentHour returns only the current hour’s real states', () => {
    useSceneStore.getState().loadSimulationResult(
      simResult([node({ hour: 6, node_id: 'n_a' }), node({ hour: 12, node_id: 'n_b' })]),
    )
    useSceneStore.getState().setCurrentHour(6)
    const atHour = useSceneStore.getState().getNodeStatesAtCurrentHour()
    expect(Object.keys(atHour)).toEqual(['n_a'])
  })

  it('getNodeStatesAtCurrentHour is an empty object, never undefined, for an hour with no data', () => {
    expect(useSceneStore.getState().getNodeStatesAtCurrentHour()).toEqual({})
  })
})
