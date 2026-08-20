/**
 * CapXmlViewer — the Alert Composer's left column (T4C.3, User Flow
 * §3.4): "Rendered in a monospace, syntax-highlighted block, showing the
 * actual generated schema fields ... shown raw and unstyled deliberately
 * ... because seeing the actual schema output is what makes
 * 'SACHET-compatible' a checkable claim rather than an assertion."
 *
 * Renders the REAL `Alert.cap_xml` string byte-for-byte (via
 * `tokenizeXml`'s real round-trip guarantee — its own test suite proves
 * concatenating every token reproduces the input exactly), just colored
 * by real XML structure. Never reformats, pretty-prints, or truncates it.
 */

import { tokenizeXml, type XmlTokenKind } from './highlightXml'

const TOKEN_COLORS: Record<XmlTokenKind, string> = {
  markup: 'var(--ops-text-dim)',
  tagname: 'var(--pixel-accent)',
  attrname: 'var(--pixel-amber)',
  attrvalue: 'var(--sev-watch)',
  text: 'var(--ops-text)',
}

export interface CapXmlViewerProps {
  xml: string
}

export function CapXmlViewer({ xml }: CapXmlViewerProps) {
  const tokens = tokenizeXml(xml)

  return (
    <pre
      data-testid="cap-xml-viewer"
      className="font-data"
      style={{
        margin: 0,
        fontSize: '0.75rem',
        lineHeight: 1.5,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        maxHeight: '70vh',
        overflowY: 'auto',
      }}
    >
      {tokens.map((token, i) => (
        <span key={i} style={{ color: TOKEN_COLORS[token.kind] }}>
          {token.text}
        </span>
      ))}
    </pre>
  )
}

export default CapXmlViewer
