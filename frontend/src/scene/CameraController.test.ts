import { describe, expect, it } from 'vitest'

import { easeInOutCubic } from './CameraController'

describe('easeInOutCubic', () => {
  it('starts at 0 and ends at 1', () => {
    expect(easeInOutCubic(0)).toBe(0)
    expect(easeInOutCubic(1)).toBe(1)
  })

  it('is exactly 0.5 at the midpoint (symmetric ease)', () => {
    expect(easeInOutCubic(0.5)).toBeCloseTo(0.5, 6)
  })

  it('is monotonically increasing (no real backward jump mid-flight)', () => {
    const samples = Array.from({ length: 21 }, (_, i) => easeInOutCubic(i / 20))
    for (let i = 1; i < samples.length; i += 1) {
      expect(samples[i]).toBeGreaterThanOrEqual(samples[i - 1])
    }
  })

  it('accelerates out of the start and decelerates into the end (not linear)', () => {
    // A linear tween would put t=0.25 at progress 0.25 exactly -- the
    // whole point of easing is that early/late progress moves slower
    // than the midpoint, which is what "cinematic, not an instant cut"
    // actually depends on.
    expect(easeInOutCubic(0.25)).toBeLessThan(0.25)
    expect(easeInOutCubic(0.75)).toBeGreaterThan(0.75)
  })
})
