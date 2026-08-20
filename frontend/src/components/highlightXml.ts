/**
 * Pure CAP-XML tokenizer (T4C.3) — "rendered in a monospace,
 * syntax-highlighted block ... shown raw and unstyled deliberately,
 * because seeing the actual schema output is what makes
 * 'SACHET-compatible' a checkable claim rather than an assertion" (User
 * Flow §3.4). Split out for the same reason every pure-logic module in
 * this project is: real, unit-testable without mounting a component.
 *
 * A real (if minimal) XML tokenizer — tag markup, tag names, attribute
 * names/values, and text content each get their own token kind — not a
 * full XML parser (this only needs to color real bytes, never to
 * validate or restructure them; `cap_generator.py`'s own lxml.etree
 * validation is the real schema check, this is presentation only).
 *
 * A STATEFUL SCANNER, NOT ONE FLAT REGEX
 * ---------------------------------------------------------------
 * An earlier version tried a single alternation regex and got it
 * genuinely wrong: with no "am I inside a tag" state, its own text
 * alternative greedily swallowed `" xmlns=\"...\">"` whole (everything
 * up to the next `<`) instead of recognizing the attribute inside it —
 * caught by this module's own round-trip test, not by inspection. A
 * small explicit in-tag/in-text scanner has no such ambiguity.
 */

export type XmlTokenKind = 'markup' | 'tagname' | 'attrname' | 'attrvalue' | 'text'

export interface XmlToken {
  text: string
  kind: XmlTokenKind
}

const TAG_NAME = /^[a-zA-Z][\w:.-]*/
const WHITESPACE = /^\s+/
const ATTRIBUTE = /^([a-zA-Z][\w:.-]*)(=)("[^"]*"|'[^']*')/

export function tokenizeXml(xml: string): XmlToken[] {
  const tokens: XmlToken[] = []
  let i = 0
  const n = xml.length

  while (i < n) {
    if (xml[i] !== '<') {
      const nextLt = xml.indexOf('<', i)
      const end = nextLt === -1 ? n : nextLt
      tokens.push({ text: xml.slice(i, end), kind: 'text' })
      i = end
      continue
    }

    const closing = xml[i + 1] === '/'
    const bracket = closing ? '</' : '<'
    tokens.push({ text: bracket, kind: 'markup' })
    i += bracket.length

    const nameMatch = TAG_NAME.exec(xml.slice(i))
    if (nameMatch) {
      tokens.push({ text: nameMatch[0], kind: 'tagname' })
      i += nameMatch[0].length
    }

    // Attributes (and the whitespace between them) until the tag closes.
    while (i < n && xml[i] !== '>' && !(xml[i] === '/' && xml[i + 1] === '>')) {
      const rest = xml.slice(i)
      const wsMatch = WHITESPACE.exec(rest)
      if (wsMatch) {
        tokens.push({ text: wsMatch[0], kind: 'markup' })
        i += wsMatch[0].length
        continue
      }
      const attrMatch = ATTRIBUTE.exec(rest)
      if (attrMatch) {
        tokens.push({ text: attrMatch[1], kind: 'attrname' })
        tokens.push({ text: attrMatch[2], kind: 'markup' })
        tokens.push({ text: attrMatch[3], kind: 'attrvalue' })
        i += attrMatch[0].length
        continue
      }
      // Real malformed/unexpected byte -- consume it as markup rather
      // than looping forever or throwing on input this isn't meant to
      // validate.
      tokens.push({ text: xml[i], kind: 'markup' })
      i += 1
    }

    if (xml[i] === '/' && xml[i + 1] === '>') {
      tokens.push({ text: '/>', kind: 'markup' })
      i += 2
    } else if (xml[i] === '>') {
      tokens.push({ text: '>', kind: 'markup' })
      i += 1
    }
  }

  return tokens
}
