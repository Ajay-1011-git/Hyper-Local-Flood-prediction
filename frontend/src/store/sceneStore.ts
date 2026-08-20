/**
 * Scene state store — T4B.2 (Zustand v5, curried `create<T>()(...)`
 * form — confirmed current in-session against zustand's own real docs;
 * required for correct TypeScript inference, not just style).
 *
 * Holds: current timeline hour, per-node water state, the uncertainty
 * envelope, damage ranking, and sensor/connection status — updated by
 * real WebSocket events (`applySocketEvent`) and by real REST fetches
 * (`loadSimulationResult`/`setDamageRanking`, called once per site load
 * and on manual refresh — see T4B.1's own documented finding:
 * `simulation_update` has no real emitter today, so the scene's INITIAL
 * and primary state comes from `GET /api/simulation/site/{site_id}`, not
 * from the socket).
 *
 * NODE STATE INDEXING: `NodeState` is inherently per-(node, hour) — this
 * project's `SimulationResult.node_states` is a flat list covering every
 * node at every hour, not pre-grouped. Indexed here as
 * `nodeStatesByHour[hour][node_id]` for O(1) lookup by the water surface
 * (T4B.5) at whatever hour the timeline scrubber is on, rather than a
 * linear scan of the whole list on every frame.
 */

import { create } from 'zustand'
import type { ConnectionStatus } from '../api/websocket'
import type { DamageRankEntry, NodeState, SimulationResult, SiteSocketEvent } from '../api/types'

export interface LastSensorAssimilation {
  sensorId: string
  distanceCm: number
  timestamp: string
  /** node_ids the real ghost-cell nudge actually changed — `[]` for
   *  Stage 1B's honest `updated_region: null` case (no simulation to
   *  update yet), never fabricated. */
  updatedNodeIds: string[]
}

export interface SceneState {
  siteId: string | null

  currentHour: number
  hoursAvailable: number[]

  nodeStatesByHour: Record<number, Record<string, NodeState>>
  envelope: Record<string, unknown>

  damageRanking: DamageRankEntry[]

  connectionStatus: ConnectionStatus
  lastSensorAssimilation: LastSensorAssimilation | null

  /** Real `structure_id` (e.g. "Building_01") the operator most recently
   *  selected — T4C.1's risk-ranking list sets this on click, and
   *  DamageOverlay (T4B.7) reads it to add a highlight ring on top of its
   *  own real severity color. `null` means nothing is selected. */
  highlightedStructureId: string | null

  // Actions
  setCurrentHour: (hour: number) => void
  loadSimulationResult: (result: SimulationResult) => void
  setDamageRanking: (entries: DamageRankEntry[]) => void
  setConnectionStatus: (status: ConnectionStatus) => void
  applySocketEvent: (event: SiteSocketEvent) => void
  setHighlightedStructure: (structureId: string | null) => void

  // Selectors
  getNodeStateAt: (hour: number, nodeId: string) => NodeState | undefined
  getNodeStatesAtCurrentHour: () => Record<string, NodeState>
}

function mergeNodeStates(
  index: Record<number, Record<string, NodeState>>,
  states: NodeState[],
): { index: Record<number, Record<string, NodeState>>; hoursAvailable: number[] } {
  // Real merge, not a full replace: a simulation_update/sensor_assimilated
  // event carries only the states that changed (T2.8's own real ghost-
  // cell nudge is explicitly LOCAL — "only 157/29,832 NodeStates
  // changed" per Stage 2's own real VERIFY), so untouched hours/nodes
  // must survive.
  const next: Record<number, Record<string, NodeState>> = { ...index }
  for (const state of states) {
    next[state.hour] = { ...(next[state.hour] ?? {}), [state.node_id]: state }
  }
  const hoursAvailable = Object.keys(next)
    .map(Number)
    .sort((a, b) => a - b)
  return { index: next, hoursAvailable }
}

export const useSceneStore = create<SceneState>()((set, get) => ({
  siteId: null,
  currentHour: 0,
  hoursAvailable: [],
  nodeStatesByHour: {},
  envelope: {},
  damageRanking: [],
  connectionStatus: 'closed',
  lastSensorAssimilation: null,
  highlightedStructureId: null,

  setCurrentHour: (hour) => set({ currentHour: hour }),
  setHighlightedStructure: (structureId) => set({ highlightedStructureId: structureId }),

  loadSimulationResult: (result) => {
    const { index, hoursAvailable } = mergeNodeStates({}, result.node_states) // full replace, not merge
    set({
      siteId: result.site_id,
      nodeStatesByHour: index,
      hoursAvailable,
      envelope: result.envelope,
      // Land the scrubber on the first real hour this simulation has,
      // rather than leaving it at a possibly-out-of-range 0.
      currentHour: hoursAvailable[0] ?? 0,
    })
  },

  setDamageRanking: (entries) => set({ damageRanking: entries }),

  setConnectionStatus: (status) => set({ connectionStatus: status }),

  applySocketEvent: (event) => {
    switch (event.type) {
      case 'simulation_update': {
        const { index, hoursAvailable } = mergeNodeStates(
          get().nodeStatesByHour,
          event.payload.node_states,
        )
        set({ nodeStatesByHour: index, hoursAvailable, envelope: event.payload.envelope })
        return
      }
      case 'sensor_assimilated': {
        const changed = event.payload.updated_region?.node_states ?? []
        const { index, hoursAvailable } = mergeNodeStates(get().nodeStatesByHour, changed)
        set({
          nodeStatesByHour: index,
          hoursAvailable,
          lastSensorAssimilation: {
            sensorId: event.payload.sensor_id,
            distanceCm: event.payload.new_reading.distance_cm,
            timestamp: event.payload.new_reading.timestamp,
            updatedNodeIds: changed.map((ns) => ns.node_id),
          },
        })
        return
      }
      case 'ranking_update':
        set({ damageRanking: event.payload })
        return
    }
  },

  getNodeStateAt: (hour, nodeId) => get().nodeStatesByHour[hour]?.[nodeId],

  getNodeStatesAtCurrentHour: () => get().nodeStatesByHour[get().currentHour] ?? {},
}))
