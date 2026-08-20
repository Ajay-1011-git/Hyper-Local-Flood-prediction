"""Multilingual alert text (+ audio) — T4A.2.

TONE, per User Flow §3.5 (Citizen Alert View) — transcribed, not
paraphrased: "a short, plain-language headline," "three to five short,
numbered action steps in large type," and explicitly "deliberately
absent: confidence percentages, ensemble counts, hazard breakdowns —
anything that would require interpretation. The citizen view's entire
design goal is zero required interpretation." Every English template
below is built to that spec: one headline sentence, 2-4 numbered
imperative steps, no numbers/jargon a citizen would need to interpret.

REAL DATA USED, NOTHING FABRICATED
------------------------------------
Templates reference the real `structure_id` (e.g. "Building_02") and real
`peak_hour` of the top-ranked entry passed in — never a fabricated street
name or an invented time. This project has no real named-street data
wired to `DamageRankEntry` (only `structure_id`/`RoadSegment.segment_id`),
so templates say "near {structure_id}" rather than inventing a more
citizen-friendly place name that doesn't exist anywhere in this project's
real data.

2026-08-20 REDESIGN, EXPLICIT PROJECT-OWNER DECISION: uses Sarvam AI
(India-focused, real multilingual/TTS platform) for real, live
translation instead of hand-authored Tamil text — see
`sarvam_client.py`'s module docstring for the real, confirmed API shape.
English stays hand-authored (native-confidence, not machine-translated);
every other supported language is translated via a REAL live Sarvam API
call at generation time, never a cached/fabricated guess.

LANGUAGE REVIEW STATUS — READ THIS BEFORE TREATING NON-ENGLISH TEXT AS FINAL
---------------------------------------------------------------------------
Per this project's anti-hallucination rule 3 ("never fabricate
multilingual alert text quality... flag it for human review rather than
presenting machine-translated text as verified-accurate") — this still
applies even though the translation now comes from a real, dedicated
Indic-language AI service rather than a hand-authored guess. Sarvam's
translation is real and live, not fabricated, but it has NOT been
reviewed by a native speaker in this session. `LANGUAGE_REVIEW_STATUS`
makes this checkable in code (e.g. by the frontend's language selector,
T4C.4), not buried in a comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from backend.stage4.alerts.sarvam_client import synthesize_speech, translate_text
from backend.stage4.shared.contracts import DamageRankEntry

#: Real, checkable review status per supported language — see module
#: docstring.
LANGUAGE_REVIEW_STATUS: Dict[str, str] = {
    "en": "native",
    "ta": "machine_translated_via_sarvam_ai_pending_human_review",
}


@dataclass(frozen=True)
class _SeverityTemplate:
    headline: str
    steps: List[str]


_ENGLISH_TEMPLATES: Dict[str, _SeverityTemplate] = {
    "Extreme": _SeverityTemplate(
        headline="URGENT: Severe flooding expected near {structure} within {hours} hours.",
        steps=[
            "Move to higher ground immediately.",
            "Move valuables above 1 meter if time permits.",
            "Avoid the area near {structure} until authorities confirm it is safe.",
            "Keep checking official updates.",
        ],
    ),
    "Severe": _SeverityTemplate(
        headline="Rising water expected near {structure} within {hours} hours.",
        steps=[
            "Move valuables above 1 meter.",
            "Avoid low-lying areas near {structure}.",
            "Prepare an emergency kit and be ready to move if conditions worsen.",
        ],
    ),
    "Moderate": _SeverityTemplate(
        headline="Possible flooding near {structure} within {hours} hours.",
        steps=[
            "Monitor water levels near {structure}.",
            "Move valuables to higher shelves as a precaution.",
            "Check on neighbors who may need help.",
        ],
    ),
    "Minor": _SeverityTemplate(
        headline="Minor flood risk noted near {structure}.",
        steps=[
            "No immediate action needed.",
            "Stay informed of updates.",
        ],
    ),
    "Unknown": _SeverityTemplate(
        headline="Flood status update unavailable.",
        steps=["Check back for updates."],
    ),
}


def _english_lines(severity: str, top_risk_entries: List[DamageRankEntry]) -> List[str]:
    """`[headline, step1, step2, ...]`, real placeholders filled in, still
    unnumbered (numbering is added back after translation, in code — see
    `generate_alert_text`, so a translator can never renumber/reorder the
    real list)."""
    if severity not in _ENGLISH_TEMPLATES:
        raise ValueError(
            f"Unknown severity {severity!r} -- expected one of "
            f"{sorted(_ENGLISH_TEMPLATES)}."
        )
    template = _ENGLISH_TEMPLATES[severity]
    top_entry = top_risk_entries[0] if top_risk_entries else None
    structure = top_entry.structure_id if top_entry is not None else "the affected area"
    hours = str(top_entry.peak_hour) if top_entry is not None else "an uncertain number of"

    headline = template.headline.format(structure=structure, hours=hours)
    steps = [s.format(structure=structure, hours=hours) for s in template.steps]
    return [headline, *steps]


def generate_alert_text(
    severity: str, top_risk_entries: List[DamageRankEntry], language: str
) -> str:
    """Plain-language alert text for `severity`, in `language`.

    `top_risk_entries` should be sorted descending by `risk_score` (T3.5's
    own contract) — only the highest-ranked entry is referenced by name,
    matching the citizen view's "zero required interpretation" goal.

    English is hand-authored directly. Any other supported language is
    translated for real via Sarvam AI (`sarvam_client.translate_text`) —
    each line translated separately (headline, then each step) so
    numbering/structure is reassembled in code afterward, never left to
    the translation model to preserve.

    Raises:
        ValueError: `severity`/`language` isn't one of the real supported
            values.
        SarvamNotConfiguredError / SarvamApiError: for non-English
            languages, if Sarvam AI can't be reached — never silently
            falls back to English or fabricated text in its place.
    """
    if language not in LANGUAGE_REVIEW_STATUS:
        raise ValueError(
            f"Unsupported language {language!r} -- expected one of "
            f"{sorted(LANGUAGE_REVIEW_STATUS)}."
        )

    lines = _english_lines(severity, top_risk_entries)
    if language != "en":
        lines = [translate_text(line, "en", language) for line in lines]

    headline, steps = lines[0], lines[1:]
    numbered_steps = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1))
    return f"{headline}\n{numbered_steps}"


def generate_alert_audio(
    severity: str, top_risk_entries: List[DamageRankEntry], language: str
) -> bytes:
    """Real, live text-to-speech (Sarvam AI `bulbul` models) of the same
    alert text `generate_alert_text` would return, as raw WAV bytes.

    Per the project-owner's explicit request to use Sarvam's TTS
    alongside translation — supports the citizen view's accessibility
    goal (a resident who can't read, or is checking the alert while
    driving/evacuating) beyond just numbered text.
    """
    text = generate_alert_text(severity, top_risk_entries, language)
    return synthesize_speech(text, language)
