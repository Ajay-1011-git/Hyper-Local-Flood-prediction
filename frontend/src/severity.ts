/**
 * Shared four-state severity language — transcribed verbatim from
 * `Flood_system_finial/flood_system_user_flow.md` §1's own table:
 *
 * | State      | Color  | Meaning                                          |
 * |------------|--------|---------------------------------------------------|
 * | Monitoring | Blue   | No elevated risk detected                          |
 * | Watch      | Amber  | Elevated probability, still distant in time        |
 * | Warning    | Orange | Significant probability, action window open       |
 * | Critical   | Red    | High-confidence, near-term hazard                  |
 *
 * "Shared severity language across both [views] ... used consistently
 * everywhere in the app so a color never means something different
 * depending on which screen you're looking at" (same doc, §1) — this
 * module is the ONE place that vocabulary lives, so `DamageOverlay.tsx`
 * (T4B.7) and later T4C components (SeverityBadge, RiskRankingList,
 * Citizen View) all import from here rather than each picking their own
 * colors.
 *
 * NOT the same vocabulary as CAP's own severity/urgency enums
 * (Extreme/Severe/Moderate/Minor, Immediate/Expected/Future — see
 * `backend/stage4/alerts/cap_generator.py`'s `derive_severity`/
 * `derive_urgency`). Those are the CAP-XML schema's required enum
 * values; this is the app's own UI language. Real, and separate.
 */

export type SeverityState = 'Monitoring' | 'Watch' | 'Warning' | 'Critical'

/** Ordered low -> high, for comparisons ("is this worse than that"). */
export const SEVERITY_ORDER: readonly SeverityState[] = ['Monitoring', 'Watch', 'Warning', 'Critical']

export const SEVERITY_COLORS: Record<SeverityState, string> = {
  Monitoring: '#3b82f6', // Blue
  Watch: '#f5b301', // Amber
  Warning: '#f97316', // Orange
  Critical: '#ef4444', // Red
}

/** Real human-facing label — "never communicated by color alone" per the
 *  same doc's §7 accessibility rule; every caller pairs this with the color. */
export const SEVERITY_LABELS: Record<SeverityState, string> = {
  Monitoring: 'Monitoring',
  Watch: 'Watch',
  Warning: 'Warning',
  Critical: 'Critical',
}

/**
 * Real `DamageRankEntry` fields this module reads — imported as a subset
 * so it doesn't need the full API type, and so its own unit tests don't
 * need to construct one.
 */
export interface RiskEntryLike {
  risk_score: number
  peak_hour: number
}

/**
 * Maps one structure's real `DamageRankEntry` to a `SeverityState`, GATED
 * on the timeline having reached its real `peak_hour` — per T4B.7's own
 * instruction ("as the timeline advances past each structure's peak-risk
 * hour") and the User Flow's own narrative device (§4.2: "notices the
 * ranking list reordering as the timeline advances past different
 * structures' risk thresholds"). Before `peak_hour`, a structure is
 * `Monitoring` regardless of its eventual risk_score — the palette
 * reveals real risk as the timeline reaches it, not before.
 *
 * FLAGGED JUDGMENT CALL (same convention as cap_generator.py's own
 * `derive_severity`/`derive_urgency`): `risk_score` = `hazard_score *
 * exposure_score * vulnerability_score` (stage3/ranking/risk_ranking.py)
 * is an UNBOUNDED, real-building-footprint-area-dependent number — there
 * is no universal absolute risk_score threshold that means "Critical"
 * across arbitrary structures of arbitrary size. Rather than invent one,
 * this normalizes each entry's risk_score against the MAXIMUM real
 * risk_score in the SAME ranking (this site's own worst structure at its
 * own worst hour), then reuses cap_generator.py's own 0.25/0.5/0.75
 * breakpoint convention (already established for vulnerability_score) —
 * one consistent tiering rule across CAP severity and this UI palette,
 * not a second, arbitrarily different one. MUST be confirmed/corrected
 * by whoever owns the User Flow spec if literal absolute risk_score
 * thresholds were actually intended.
 */
export function severityForEntry(
  entry: RiskEntryLike,
  currentHour: number,
  maxRiskScoreInRanking: number,
): SeverityState {
  if (currentHour < entry.peak_hour) return 'Monitoring'
  if (maxRiskScoreInRanking <= 0) return 'Monitoring'

  const normalized = Math.min(1, Math.max(0, entry.risk_score / maxRiskScoreInRanking))
  if (normalized >= 0.75) return 'Critical'
  if (normalized >= 0.5) return 'Warning'
  if (normalized >= 0.25) return 'Watch'
  return 'Monitoring'
}

/**
 * Maps a real CAP severity enum value (Extreme/Severe/Moderate/Minor/
 * Unknown — `backend/stage4/alerts/cap_generator.py::derive_severity`)
 * to this app's own four-state UI vocabulary, for display in the
 * Citizen View (T4C.4) and Alert Composer (T4C.3) previews.
 *
 * A DISCLOSED, PRESENTATION-ONLY MAPPING, NOT CAP's OWN FIELD
 * ---------------------------------------------------------------
 * CAP's severity enum and this app's Monitoring/Watch/Warning/Critical
 * vocabulary are two real, different, independently-defined taxonomies
 * (see this file's own module docstring) — this mapping exists only so
 * a real `Alert.severity` value has SOME real color/label to show in UI
 * built around the app's own palette. Both `AlertComposer.tsx` and
 * `CitizenView.tsx` import this SAME function rather than each picking
 * their own mapping, so the two previews of "what a citizen would see"
 * can never independently disagree.
 */
export function capSeverityToUiSeverity(capSeverity: string): SeverityState {
  switch (capSeverity) {
    case 'Extreme':
      return 'Critical'
    case 'Severe':
      return 'Warning'
    case 'Moderate':
      return 'Watch'
    default:
      return 'Monitoring'
  }
}
