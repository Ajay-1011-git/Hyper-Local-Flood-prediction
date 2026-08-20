import { describe, expect, it } from 'vitest'

import { parseAlertText } from './citizenAlertText'

describe('parseAlertText', () => {
  it('splits the real multilingual.py format into a headline + stripped steps', () => {
    const text = 'Rising water expected near Building_02 within 24 hours.\n1. Move valuables above 1 meter.\n2. Avoid low-lying areas near Building_02.'
    expect(parseAlertText(text)).toEqual({
      headline: 'Rising water expected near Building_02 within 24 hours.',
      steps: ['Move valuables above 1 meter.', 'Avoid low-lying areas near Building_02.'],
    })
  })

  it('handles a single-line alert with no steps (the real "Unknown" severity template)', () => {
    expect(parseAlertText('Flood status update unavailable.')).toEqual({
      headline: 'Flood status update unavailable.',
      steps: [],
    })
  })

  it('never throws on an empty string', () => {
    expect(parseAlertText('')).toEqual({ headline: '', steps: [] })
  })
})
