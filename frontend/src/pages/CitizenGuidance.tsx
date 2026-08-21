/**
 * Citizen Guidance sub-page (`/citizen/guidance`) — T4C.5.
 *
 * Per User Flow §3.6: "A calmer, secondary page reachable from the main
 * citizen alert — general flood-safety guidance not tied to the live
 * event, for someone who wants to prepare ahead of an active warning.
 * Same visual language as 3.5, lower urgency tone."
 *
 * NOT TIED TO THE LIVE EVENT — NO ALERT FETCH, NO SEVERITY COLOR
 * ---------------------------------------------------------------
 * Unlike `CitizenView.tsx`, this page fetches nothing from Stage 4 — its
 * whole point (per the doc) is general guidance independent of any live
 * alert. The status band is deliberately calm/neutral, never one of the
 * four alarm severity colors, per "lower urgency tone."
 *
 * ENGLISH ONLY — A DISCLOSED LIMITATION, NOT A FABRICATED TRANSLATION
 * ---------------------------------------------------------------
 * This project's real translation path (Sarvam AI, `multilingual.py`)
 * only translates the LIVE alert text Stage 4 generates — there is no
 * real backend endpoint that translates this page's own static
 * guidance content. Hand-writing "confident" translations of
 * life-safety instructions into five languages without a real,
 * reviewed translation is exactly the kind of unreviewed-text-presented-
 * as-accurate this project's own anti-hallucination rules forbid
 * (`multilingual.py`'s own module docstring: "never fabricate
 * multilingual alert text quality"). Stated honestly below rather than
 * silently shipping unreviewed guidance in languages nobody checked.
 */

import BackLink from '../components/BackLink'

const BEFORE_STEPS = [
  'Know your area’s flood risk and evacuation routes ahead of time.',
  'Keep an emergency kit ready: water, non-perishable food, flashlight, first-aid, medications, phone charger.',
  'Store important documents (ID, insurance, medical records) in a waterproof bag.',
  'Know how to safely turn off electricity, gas, and water at the mains.',
  'Agree on a family meeting point in case you get separated.',
]

const DURING_STEPS = [
  'Move to higher ground immediately if water is rising near you.',
  'Never walk or drive through moving flood water — 15cm can knock you down, 30cm can float a car.',
  'Avoid contact with flood water where possible; it may be contaminated or electrically live.',
  'Stay off bridges over fast-moving water.',
  'Keep a battery or hand-crank radio for updates if power/network is down.',
]

const AFTER_STEPS = [
  'Do not return home until local authorities say it is safe.',
  'Avoid flood water — check for structural damage, gas leaks, and exposed wiring before re-entering.',
  'Throw away food and water that may have contacted flood water.',
  'Document damage with photos before cleaning up, for insurance/aid claims.',
  'Check on neighbors, especially elderly or disabled residents.',
]

function GuidanceSection({ title, steps }: { title: string; steps: string[] }) {
  return (
    <section style={{ marginBottom: '2rem' }}>
      <h2 className="font-pixel-body" style={{ fontSize: '1.5rem', color: 'var(--citizen-text)', margin: '0 0 0.75rem' }}>
        {title}
      </h2>
      <ul style={{ margin: 0, paddingLeft: '1.2rem' }}>
        {steps.map((step, i) => (
          <li key={i} className="font-pixel-body" style={{ fontSize: '1.2rem', marginBottom: '0.6rem', lineHeight: 1.4 }}>
            {step}
          </li>
        ))}
      </ul>
    </section>
  )
}

export function CitizenGuidance() {
  return (
    <main
      style={{ minHeight: '100vh', background: 'var(--citizen-bg)', color: 'var(--citizen-text)' }}
      className="font-sans"
    >
      <div style={{ padding: '0.75rem 1rem' }}>
        <BackLink to="/citizen" label="Back to alert" tone="light" />
      </div>

      {/* Calm, neutral band -- deliberately NOT one of the four alarm
          severity colors, per the doc's own "lower urgency tone." */}
      <div style={{ background: 'var(--citizen-panel)', borderBottom: '3px solid var(--citizen-border)', padding: '1.25rem 1rem' }}>
        <h1 className="font-pixel-body" style={{ fontSize: 'clamp(1.4rem, 5vw, 1.8rem)', margin: 0 }}>
          General Flood Safety Guidance
        </h1>
        <p className="font-pixel-body" style={{ fontSize: '1.1rem', color: 'var(--citizen-text-dim)', margin: '0.4rem 0 0' }}>
          For preparing ahead of time — not tied to a current warning.
        </p>
      </div>

      <div style={{ padding: '1.25rem 1rem', maxWidth: 640 }}>
        <GuidanceSection title="Before a flood" steps={BEFORE_STEPS} />
        <GuidanceSection title="During a flood" steps={DURING_STEPS} />
        <GuidanceSection title="After a flood" steps={AFTER_STEPS} />

        <p
          className="font-pixel-body"
          style={{ fontSize: '0.95rem', color: 'var(--citizen-text-dim)', marginTop: '1.5rem' }}
        >
          This guidance is currently available in English only — it hasn't been through the same
          real, reviewed translation path as your live alert text.
        </p>
      </div>
    </main>
  )
}

export default CitizenGuidance
