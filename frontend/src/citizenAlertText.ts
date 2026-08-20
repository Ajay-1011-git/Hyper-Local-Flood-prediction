/**
 * Pure parsing of Stage 4's real `Alert.text_by_language` strings
 * (T4C.4) — a real, confirmed shape, not guessed: `multilingual.py`'s
 * own `generate_alert_text` always returns `f"{headline}\n{numbered_steps}"`
 * where `numbered_steps` is `"1. ...\n2. ...\n..."` (see that module's own
 * source — headline first, "numbering added back after translation, in
 * code," per its own docstring). This module un-does exactly that real
 * format, never inventing a different one.
 */

export interface ParsedAlertText {
  headline: string
  /** Real step text with its "N. " prefix stripped — the number is
   *  reapplied by the renderer as a real ordered list, not baked into
   *  the displayed string twice. */
  steps: string[]
}

const NUMBERED_STEP = /^\d+\.\s*/

export function parseAlertText(text: string): ParsedAlertText {
  const lines = text.split('\n').filter((line) => line.trim().length > 0)
  const [headline = '', ...rest] = lines
  const steps = rest.map((line) => line.replace(NUMBERED_STEP, ''))
  return { headline, steps }
}
