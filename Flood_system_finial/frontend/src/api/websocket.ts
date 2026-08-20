/**
 * WebSocket client — T4B.1.
 *
 * Connects to `/ws/site/{site_id}` and auto-reconnects on drop without a
 * page reload (TRD TNFR-5).
 *
 * REAL CONSTRAINT, CONFIRMED DIRECTLY IN THIS SESSION (not assumed from
 * §B.2's contract text) — read this before wiring this into the scene
 * store (T4B.2) or the water surface (T4B.5):
 *
 *   `grep -rn '"type"'` across the real backend code (not the contract's
 *   own comments) shows `sensor_assimilated` is the ONLY event any real
 *   backend process ever actually broadcasts today. `simulation_update`
 *   and `ranking_update` (both named in §B.2's contract) have NO
 *   emitter anywhere in this repo: Stage 2 never broadcasts after a
 *   `set_site_state()` precompute run, and Stage 3's `damage-ranking`
 *   route is a plain REST endpoint, not a broadcaster.
 *
 * Consequences this client is built around:
 *   1. It correctly parses and routes all THREE event types (future-
 *      proof, matches the real contract shape) — but callers must not
 *      assume `simulation_update`/`ranking_update` will ever arrive
 *      today. The 3D scene's INITIAL state comes from the real REST
 *      endpoints (`api/client.ts`'s `fetchSimulationResult`/
 *      `fetchDamageRanking`), not from a WS event.
 *   2. `sensor_assimilated` is itself broadcast by TWO independent
 *      processes (Stage 1B and Stage 2), each with a different
 *      `updated_region` — Stage 1B's is always `null` (it has no
 *      simulation to update), Stage 2's is real once T2.8 assimilation
 *      runs. `VITE_WS_BASE_URL` picks which one this client talks to;
 *      defaults to Stage 2's (real `updated_region`).
 *   3. An unrecognized `type` is logged and ignored, never thrown — a
 *      backend emitting an event this client doesn't know about yet
 *      must not crash the whole page.
 */

import type { SiteSocketEvent } from './types'

export type ConnectionStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface SiteSocketHandlers {
  onEvent?: (event: SiteSocketEvent) => void
  onStatusChange?: (status: ConnectionStatus) => void
  /** Real, unrecognized-shape, or JSON-parse failures — never silently swallowed. */
  onError?: (error: unknown) => void
}

export interface SiteSocketOptions {
  /** Initial backoff delay in ms before the first reconnect attempt. */
  initialBackoffMs?: number
  /** Backoff is capped here — real deployments should not back off forever. */
  maxBackoffMs?: number
  /** Injectable for tests; defaults to the real browser `WebSocket`. */
  WebSocketImpl?: typeof WebSocket
}

const DEFAULT_INITIAL_BACKOFF_MS = 1000
const DEFAULT_MAX_BACKOFF_MS = 30000

function isSiteSocketEvent(value: unknown): value is SiteSocketEvent {
  if (typeof value !== 'object' || value === null) return false
  const type = (value as { type?: unknown }).type
  return type === 'simulation_update' || type === 'sensor_assimilated' || type === 'ranking_update'
}

/**
 * A reconnecting WebSocket client for one site's `/ws/site/{site_id}`
 * channel. Framework-agnostic (no React/Zustand dependency) so it's
 * independently testable — T4B.2's store subscribes to it via handlers.
 */
export class SiteSocket {
  private readonly url: string
  private readonly handlers: SiteSocketHandlers
  private readonly WebSocketImpl: typeof WebSocket
  private readonly initialBackoffMs: number
  private readonly maxBackoffMs: number

  private socket: WebSocket | null = null
  private backoffMs: number
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private closedByCaller = false

  constructor(siteId: string, baseUrl: string, handlers: SiteSocketHandlers, options: SiteSocketOptions = {}) {
    this.url = `${baseUrl.replace(/\/$/, '')}/ws/site/${encodeURIComponent(siteId)}`
    this.handlers = handlers
    this.WebSocketImpl = options.WebSocketImpl ?? WebSocket
    this.initialBackoffMs = options.initialBackoffMs ?? DEFAULT_INITIAL_BACKOFF_MS
    this.maxBackoffMs = options.maxBackoffMs ?? DEFAULT_MAX_BACKOFF_MS
    this.backoffMs = this.initialBackoffMs
  }

  connect(): void {
    this.closedByCaller = false
    this.openSocket()
  }

  private openSocket(): void {
    this.setStatus(this.socket === null && this.backoffMs === this.initialBackoffMs ? 'connecting' : 'reconnecting')

    const socket = new this.WebSocketImpl(this.url)
    this.socket = socket

    socket.onopen = () => {
      this.backoffMs = this.initialBackoffMs // reset backoff after a real successful connect
      this.setStatus('open')
    }

    socket.onmessage = (event: MessageEvent) => {
      this.handleMessage(event.data)
    }

    socket.onerror = (event: Event) => {
      this.handlers.onError?.(event)
    }

    socket.onclose = () => {
      this.socket = null
      if (this.closedByCaller) {
        this.setStatus('closed')
        return
      }
      this.scheduleReconnect()
    }
  }

  private handleMessage(raw: unknown): void {
    let parsed: unknown
    try {
      parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    } catch (error) {
      this.handlers.onError?.(error)
      return
    }

    if (!isSiteSocketEvent(parsed)) {
      // A real, unrecognized event shape/type -- logged, never thrown.
      // See module docstring point 3: a backend emitting something this
      // client doesn't know about must not crash the page.
      console.warn('[SiteSocket] ignoring unrecognized message:', parsed)
      return
    }

    this.handlers.onEvent?.(parsed)
  }

  private scheduleReconnect(): void {
    this.setStatus('reconnecting')
    this.reconnectTimer = setTimeout(() => {
      this.openSocket()
    }, this.backoffMs)
    // Exponential backoff, capped -- never gives up (TRD TNFR-5: no page
    // reload required), but never hammers a genuinely-down backend either.
    this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs)
  }

  private setStatus(status: ConnectionStatus): void {
    this.handlers.onStatusChange?.(status)
  }

  close(): void {
    this.closedByCaller = true
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.socket?.close()
  }
}
