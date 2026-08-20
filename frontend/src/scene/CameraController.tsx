/**
 * Camera controller (T4B.8).
 *
 * Implements the User Flow doc's own §3.2 description verbatim: "A
 * single click ... smoothly flies the camera down into the scanned
 * 50m×50m site — this transition is deliberately slow and cinematic
 * (roughly 2 seconds), not an instant cut, because the continuity of
 * that motion is what visually proves 'this is one system'."
 *
 * (Real, disclosed discrepancy, not silently reconciled: the doc's own
 * "50m×50m" figure doesn't match this project's actual registered site
 * patch — `site_terrain_half_span_m=150.0` in `backend/stage4/config.py`
 * means a real ~300m×300m local patch. This component flies to the REAL
 * site extent Terrain/SiteMesh already render, not a fabricated 50m one.)
 *
 * MECHANICS
 * ---------------------------------------------------------------
 * Owns BOTH the camera's real resting poses (the wide "opens wide"
 * regional view and the close site-local view) and the ~2s eased
 * transition between them, driven by `trigger` (an incrementing number a
 * caller bumps to fire one flight — toggling regional<->site each time,
 * so the same control doubles as "fly in" and "fly back out"). Drei's
 * `OrbitControls` (mounted as a sibling with `makeDefault`) is briefly
 * disabled mid-flight so a stray drag can't fight the animated
 * `camera.position`/`controls.target` — re-enabled the instant the
 * flight completes.
 *
 * Renders nothing itself; it only drives `useThree()`'s real camera and
 * `controls` objects imperatively inside `useFrame`, per the standard
 * react-three-fiber pattern for camera animation confirmed in-session
 * against the current `@react-three/fiber`/`three-stdlib` APIs.
 */

import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'

/**
 * Standard ease-in-out cubic — accelerates out of the wide view,
 * decelerates into the site, rather than a linear (visually mechanical)
 * pan. Exported (and unit-tested separately) for the same reason
 * `terrainGeometry.ts`/`waterGeometry.ts` split their real maths out of
 * the mounted component: it's checkable without a WebGL context.
 */
export function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
}

export interface CameraPose {
  position: [number, number, number]
  target: [number, number, number]
}

export interface CameraControllerProps {
  /** The scene's wide "opens wide" resting pose. */
  regional: CameraPose
  /** The close, site-local pose the fly-in lands on. */
  site: CameraPose
  /** Bump this (e.g. `setTrigger((n) => n + 1)`) to fire one flight —
   *  toggles between `regional` and `site` on each real change. */
  trigger: number
  /** ~2000ms, per the User Flow's own "roughly 2 seconds ... not an
   *  instant cut" — the one number this component's whole existence is
   *  built to honor, so it is a named default, not a magic number. */
  durationMs?: number
  /** Real, eased progress (0..1) + which direction — lets a caller (e.g.
   *  a VERIFY harness) confirm a flight is genuinely mid-transition. */
  onProgress?: (progress: number, flyingToSite: boolean) => void
}

interface Flight {
  startedAt: number
  fromPosition: THREE.Vector3
  fromTarget: THREE.Vector3
  toPosition: THREE.Vector3
  toTarget: THREE.Vector3
  flyingToSite: boolean
}

export function CameraController({
  regional,
  site,
  trigger,
  durationMs = 2000,
  onProgress,
}: CameraControllerProps) {
  const camera = useThree((state) => state.camera)
  const controls = useThree((state) => state.controls) as OrbitControlsImpl | null

  const initializedRef = useRef(false)
  const atSiteRef = useRef(false)
  const flightRef = useRef<Flight | null>(null)
  const lastTriggerRef = useRef(trigger)

  // Real one-time initial pose ("opens wide") -- not itself an animated
  // transition, just establishing the resting state T4B.3's own camera
  // prop used to set directly.
  useEffect(() => {
    if (initializedRef.current || !controls) return
    initializedRef.current = true
    camera.position.set(...regional.position)
    controls.target.set(...regional.target)
    controls.update()
    // Intentionally only on controls becoming available -- regional's
    // own identity may change reference every render (a fresh object
    // literal from the caller), and re-running this on every such
    // "change" would snap the camera back mid-session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controls])

  useEffect(() => {
    if (trigger === lastTriggerRef.current || !controls) return
    lastTriggerRef.current = trigger

    const flyingToSite = !atSiteRef.current
    atSiteRef.current = flyingToSite
    const to = flyingToSite ? site : regional

    controls.enabled = false
    flightRef.current = {
      startedAt: performance.now(),
      fromPosition: camera.position.clone(),
      fromTarget: controls.target.clone(),
      toPosition: new THREE.Vector3(...to.position),
      toTarget: new THREE.Vector3(...to.target),
      flyingToSite,
    }
  }, [trigger, camera, controls, regional, site])

  useFrame(() => {
    const flight = flightRef.current
    if (!flight || !controls) return

    const elapsed = performance.now() - flight.startedAt
    const linear = Math.min(1, elapsed / durationMs)
    const eased = easeInOutCubic(linear)

    camera.position.lerpVectors(flight.fromPosition, flight.toPosition, eased)
    controls.target.lerpVectors(flight.fromTarget, flight.toTarget, eased)
    controls.update()

    onProgress?.(eased, flight.flyingToSite)

    if (linear >= 1) {
      flightRef.current = null
      controls.enabled = true
    }
  })

  return null
}

export default CameraController
