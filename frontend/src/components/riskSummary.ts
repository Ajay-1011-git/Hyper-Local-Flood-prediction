/**
 * Pure "hazard summary" text (T4C.1's risk-ranking row: "1.2m depth,
 * fast flow, rising" per User Flow §3.2) — derived entirely from real
 * `DamageRankEntry` peak fields, no invented adjectives beyond named,
 * documented thresholds.
 */

import type { DamageRankEntry } from '../api/types'

/** Real, named thresholds (m/s) — not tuned per screenshot. */
const FAST_FLOW_MPS = 1.0
const MODERATE_FLOW_MPS = 0.3

function flowDescriptor(velocityMps: number): string {
  if (velocityMps >= FAST_FLOW_MPS) return 'fast flow'
  if (velocityMps >= MODERATE_FLOW_MPS) return 'moderate flow'
  return 'calm flow'
}

/** A real rate_of_rise of exactly 0 reads as "steady" rather than
 *  forcing it into rising/falling. */
function trendDescriptor(rateOfRise: number): string {
  if (rateOfRise > 0) return 'rising'
  if (rateOfRise < 0) return 'falling'
  return 'steady'
}

/** Real depth, at a precision that doesn't erase it.
 *
 * `toFixed(1)` rendered every sub-decimetre depth as "0.0m" — including
 * a real 7cm of standing water on a road, which is a genuine, rankable
 * hazard, and made distinct structures look identical. Switches to
 * centimetres below 10cm rather than padding decimals onto deep water. */
export function depthLabel(depthM: number): string {
  if (depthM < 0.1) return `${Math.round(depthM * 100)}cm`
  return `${depthM.toFixed(1)}m`
}

export function hazardSummary(entry: DamageRankEntry): string {
  return `${depthLabel(entry.peak_depth_m)} depth, ${flowDescriptor(entry.peak_velocity_mps)}, ${trendDescriptor(entry.peak_rate_of_rise)}`
}

/** "41 of 50 forecast scenarios place this structure above the critical
 *  threshold" (User Flow §3.3's own plain-language confidence phrasing)
 *  — `confidence` IS that real fraction (`DamageRankEntry.confidence`,
 *  sourced from `ensemble_agreement_fraction`), never re-derived. */
export function confidencePercent(entry: DamageRankEntry): number {
  return Math.round(entry.confidence * 100)
}
