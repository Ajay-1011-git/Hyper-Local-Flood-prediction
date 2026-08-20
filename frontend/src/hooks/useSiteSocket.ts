/**
 * Wires T4B.1's `SiteSocket` into the scene store — never done anywhere
 * in the app until now (confirmed: `SiteSocket` had no real caller
 * outside `websocket.ts`/its own tests — the store's `applySocketEvent`
 * existed since T4B.2 but nothing ever fed it a real event).
 *
 * Without this, T4B.6's uncertainty envelope has no real
 * `sensor_assimilated` event to ever narrow on.
 */

import { useEffect } from 'react'

import { SiteSocket } from '../api/websocket'
import { useSceneStore } from '../store/sceneStore'

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? 'ws://127.0.0.1:8765'

export function useSiteSocket(siteId: string): void {
  const applySocketEvent = useSceneStore((s) => s.applySocketEvent)
  const setConnectionStatus = useSceneStore((s) => s.setConnectionStatus)

  useEffect(() => {
    const socket = new SiteSocket(siteId, WS_BASE_URL, {
      onEvent: applySocketEvent,
      onStatusChange: setConnectionStatus,
      onError: (error) => {
        // Real connection errors are expected whenever the WS backend
        // isn't up (common outside a live demo) -- logged, never thrown,
        // matching SiteSocket's own "never crash the page" contract.
        // eslint-disable-next-line no-console
        console.warn('[useSiteSocket] error', error)
      },
    })
    socket.connect()
    return () => socket.close()
  }, [siteId, applySocketEvent, setConnectionStatus])
}

export default useSiteSocket
