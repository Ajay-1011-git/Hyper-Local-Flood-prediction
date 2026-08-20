import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SiteSocket, type ConnectionStatus } from './websocket'
import type { SiteSocketEvent } from './types'

/**
 * A fake `WebSocket` that never touches the network — real timing/state
 * transitions (open -> message -> close -> reconnect) are exercised via
 * its `simulate*` helpers, driven by vitest's fake timers for the
 * reconnect-backoff tests. The one genuinely LIVE reconnect test lives
 * separately as a real headless-browser script (see this task's VERIFY),
 * since jsdom has no real network stack to actually drop a connection
 * against.
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static reset(): void {
    FakeWebSocket.instances = []
  }

  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  onclose: (() => void) | null = null
  closeCalled = false

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  close(): void {
    this.closeCalled = true
    this.onclose?.()
  }

  simulateOpen(): void {
    this.onopen?.()
  }

  simulateMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  simulateServerDrop(): void {
    this.onclose?.()
  }
}

function makeSocket(handlers: {
  onEvent?: (e: SiteSocketEvent) => void
  onStatusChange?: (s: ConnectionStatus) => void
  onError?: (e: unknown) => void
}) {
  FakeWebSocket.reset()
  return new SiteSocket('vit-vellore', 'ws://fake-host', handlers, {
    WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    initialBackoffMs: 100,
    maxBackoffMs: 800,
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('connection URL', () => {
  it('builds /ws/site/{site_id} with the real confirmed path and encodes the site id', () => {
    const socket = makeSocket({})
    socket.connect()
    expect(FakeWebSocket.instances[0].url).toBe('ws://fake-host/ws/site/vit-vellore')
    socket.close()
  })

  it('strips a trailing slash from the base URL', () => {
    FakeWebSocket.reset()
    const socket = new SiteSocket('vit-vellore', 'ws://fake-host/', {}, {
      WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    })
    socket.connect()
    expect(FakeWebSocket.instances[0].url).toBe('ws://fake-host/ws/site/vit-vellore')
    socket.close()
  })
})

describe('status transitions', () => {
  it('reports connecting -> open on a clean connect', () => {
    const statuses: ConnectionStatus[] = []
    const socket = makeSocket({ onStatusChange: (s) => statuses.push(s) })
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()
    expect(statuses).toEqual(['connecting', 'open'])
    socket.close()
  })

  it('reports closed (not reconnecting) when close() was called by the caller', () => {
    const statuses: ConnectionStatus[] = []
    const socket = makeSocket({ onStatusChange: (s) => statuses.push(s) })
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()
    socket.close()
    expect(statuses.at(-1)).toBe('closed')
  })
})

describe('event parsing — the three real contract event types', () => {
  it('routes a real sensor_assimilated event (the only one any backend actually sends today)', () => {
    const events: SiteSocketEvent[] = []
    const socket = makeSocket({ onEvent: (e) => events.push(e) })
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()
    FakeWebSocket.instances[0].simulateMessage({
      type: 'sensor_assimilated',
      payload: { sensor_id: 'esp32-vellore-demo-01', updated_region: { node_ids: ['n_0_0'] } },
    })
    expect(events).toHaveLength(1)
    expect(events[0].type).toBe('sensor_assimilated')
    socket.close()
  })

  it('routes simulation_update and ranking_update too (future-proof, even though no backend emits them today)', () => {
    const events: SiteSocketEvent[] = []
    const socket = makeSocket({ onEvent: (e) => events.push(e) })
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()
    FakeWebSocket.instances[0].simulateMessage({
      type: 'simulation_update',
      payload: { node_states: [], envelope: {} },
    })
    FakeWebSocket.instances[0].simulateMessage({ type: 'ranking_update', payload: [] })
    expect(events.map((e) => e.type)).toEqual(['simulation_update', 'ranking_update'])
    socket.close()
  })

  it('ignores an unrecognized event type instead of throwing', () => {
    const events: SiteSocketEvent[] = []
    const errors: unknown[] = []
    const socket = makeSocket({ onEvent: (e) => events.push(e), onError: (e) => errors.push(e) })
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()
    expect(() =>
      FakeWebSocket.instances[0].simulateMessage({ type: 'some_future_event', payload: {} }),
    ).not.toThrow()
    expect(events).toHaveLength(0)
    expect(errors).toHaveLength(0) // logged via console.warn, not treated as an error
    socket.close()
  })

  it('reports malformed JSON via onError rather than throwing', () => {
    const errors: unknown[] = []
    const socket = makeSocket({ onError: (e) => errors.push(e) })
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()
    FakeWebSocket.instances[0].onmessage?.({ data: '{not valid json' })
    expect(errors).toHaveLength(1)
    socket.close()
  })
})

describe('auto-reconnect (TRD TNFR-5) — no page reload required', () => {
  it('reconnects after the server drops the connection, without close() being called', () => {
    const statuses: ConnectionStatus[] = []
    const socket = makeSocket({ onStatusChange: (s) => statuses.push(s) })
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()

    FakeWebSocket.instances[0].simulateServerDrop() // a real drop, not socket.close()
    expect(statuses.at(-1)).toBe('reconnecting')
    expect(FakeWebSocket.instances).toHaveLength(1) // hasn't reconnected yet -- still backing off

    vi.advanceTimersByTime(100) // the configured initialBackoffMs
    expect(FakeWebSocket.instances).toHaveLength(2) // a real second socket was opened
    FakeWebSocket.instances[1].simulateOpen()
    expect(statuses.at(-1)).toBe('open')

    socket.close()
  })

  it('backs off exponentially and caps at maxBackoffMs, never giving up', () => {
    const socket = makeSocket({})
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()

    // Drop 1 -> reconnect after 100ms
    FakeWebSocket.instances[0].simulateServerDrop()
    vi.advanceTimersByTime(100)
    expect(FakeWebSocket.instances).toHaveLength(2)

    // Drop 2 (before this new one ever opens) -> backoff doubles to 200ms
    FakeWebSocket.instances[1].simulateServerDrop()
    vi.advanceTimersByTime(199)
    expect(FakeWebSocket.instances).toHaveLength(2) // not yet
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(3)

    // Drop repeatedly without ever succeeding -- backoff must cap at 800ms,
    // not grow unbounded (1000 would exceed maxBackoffMs).
    FakeWebSocket.instances[2].simulateServerDrop() // -> 400ms
    vi.advanceTimersByTime(400)
    FakeWebSocket.instances[3].simulateServerDrop() // -> 800ms (capped)
    vi.advanceTimersByTime(800)
    FakeWebSocket.instances[4].simulateServerDrop() // stays at 800ms, never 1600ms
    vi.advanceTimersByTime(800)
    expect(FakeWebSocket.instances).toHaveLength(6)

    socket.close()
  })

  it('resets backoff to the initial delay after a real successful reconnect', () => {
    const socket = makeSocket({})
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()

    FakeWebSocket.instances[0].simulateServerDrop()
    vi.advanceTimersByTime(100)
    FakeWebSocket.instances[1].simulateOpen() // real success -- backoff should reset

    FakeWebSocket.instances[1].simulateServerDrop()
    vi.advanceTimersByTime(99)
    expect(FakeWebSocket.instances).toHaveLength(2) // not yet -- confirms it reset to 100ms, not 200ms
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(3)

    socket.close()
  })

  it('does NOT reconnect after an explicit close()', () => {
    const socket = makeSocket({})
    socket.connect()
    FakeWebSocket.instances[0].simulateOpen()
    socket.close()
    vi.advanceTimersByTime(60000)
    expect(FakeWebSocket.instances).toHaveLength(1) // no reconnect attempt was ever made
  })
})
