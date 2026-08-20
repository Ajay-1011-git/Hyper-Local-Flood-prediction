/**
 * Citizen Guidance sub-page (`/citizen/guidance`) — PLACEHOLDER, not yet
 * T4C.5.
 *
 * Per User Flow §3.6: "A calmer, secondary page reachable from the main
 * citizen alert — general flood-safety guidance not tied to the live
 * event ... same visual language as 3.5, lower urgency tone." Exists now
 * only so Citizen View's real link (T4C.4) lands somewhere honest.
 */

import ComingSoonPage from './ComingSoonPage'

export function CitizenGuidance() {
  return (
    <ComingSoonPage
      title="Flood Safety Guidance"
      note="General flood-safety guidance isn't built yet — check back soon."
    />
  )
}

export default CitizenGuidance
