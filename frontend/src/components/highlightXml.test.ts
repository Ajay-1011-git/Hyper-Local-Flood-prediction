import { describe, expect, it } from 'vitest'

import { tokenizeXml } from './highlightXml'

describe('tokenizeXml', () => {
  it('tokenizes an opening tag with an attribute', () => {
    const tokens = tokenizeXml('<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">')
    expect(tokens).toEqual([
      { text: '<', kind: 'markup' },
      { text: 'alert', kind: 'tagname' },
      { text: ' ', kind: 'markup' },
      { text: 'xmlns', kind: 'attrname' },
      { text: '=', kind: 'markup' },
      { text: '"urn:oasis:names:tc:emergency:cap:1.2"', kind: 'attrvalue' },
      { text: '>', kind: 'markup' },
    ])
  })

  it('tokenizes a closing tag', () => {
    expect(tokenizeXml('</alert>')).toEqual([
      { text: '</', kind: 'markup' },
      { text: 'alert', kind: 'tagname' },
      { text: '>', kind: 'markup' },
    ])
  })

  it('tokenizes real text content between tags', () => {
    const tokens = tokenizeXml('<severity>Critical</severity>')
    expect(tokens.map((t) => t.kind)).toEqual(['markup', 'tagname', 'markup', 'text', 'markup', 'tagname', 'markup'])
    expect(tokens.find((t) => t.kind === 'text')?.text).toBe('Critical')
  })

  it('tokenizes a self-closing tag with multiple attributes', () => {
    const tokens = tokenizeXml('<point lat="12.9" lon="79.1"/>')
    expect(tokens.filter((t) => t.kind === 'attrname').map((t) => t.text)).toEqual(['lat', 'lon'])
    expect(tokens.filter((t) => t.kind === 'attrvalue').map((t) => t.text)).toEqual(['"12.9"', '"79.1"'])
    expect(tokens.at(-1)).toEqual({ text: '/>', kind: 'markup' })
  })

  it('round-trips: concatenating every token text reproduces the real input', () => {
    const xml = '<alert xmlns="cap"><info><severity>Critical</severity></info></alert>'
    const tokens = tokenizeXml(xml)
    expect(tokens.map((t) => t.text).join('')).toBe(xml)
  })

  it('round-trips a real multi-attribute self-closing tag with mixed spacing', () => {
    const xml = '<point   lat="12.9"  lon="79.1" />'
    const tokens = tokenizeXml(xml)
    expect(tokens.map((t) => t.text).join('')).toBe(xml)
  })
})
