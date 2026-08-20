"""Tests for T4A.2 — multilingual alert text (+ audio).

`translate_text`/`synthesize_speech` (Sarvam AI calls) are mocked here --
`test_sarvam_client.py` covers the real API integration directly,
including one real live call. This file tests `multilingual.py`'s own
logic: template filling, structure preservation across "translation",
severity/language validation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.stage4.alerts.multilingual import (
    LANGUAGE_REVIEW_STATUS,
    generate_alert_audio,
    generate_alert_text,
)
from backend.stage4.shared.contracts import DamageRankEntry


def _entry(*, structure_id: str = "Building_02", peak_hour: int = 5) -> DamageRankEntry:
    return DamageRankEntry(
        structure_id=structure_id,
        structure_type="building",
        site_id="vit-vellore",
        hazard_score=6.1,
        exposure_score=300.0,
        vulnerability_score=0.82,
        vulnerability_source="USACE EGM 04-01 x AIDR 7-3",
        vulnerability_is_local_calibration=False,
        risk_score=1789.8,
        confidence=0.7,
        rank=1,
        peak_hour=peak_hour,
        peak_depth_m=1.8,
        peak_velocity_mps=2.1,
        peak_rate_of_rise=0.15,
    )


def test_language_review_status_flags_tamil_pending_review():
    assert LANGUAGE_REVIEW_STATUS["en"] == "native"
    assert "pending_human_review" in LANGUAGE_REVIEW_STATUS["ta"]


def test_language_review_status_covers_all_six_supported_languages():
    """2026-08-20: Hindi/Telugu/Malayalam/Kannada added alongside
    English/Tamil, per explicit project-owner request."""
    assert set(LANGUAGE_REVIEW_STATUS.keys()) == {"en", "ta", "hi", "te", "ml", "kn"}
    for lang in ("ta", "hi", "te", "ml", "kn"):
        assert "pending_human_review" in LANGUAGE_REVIEW_STATUS[lang]


def test_english_text_uses_real_structure_id_and_peak_hour():
    text = generate_alert_text("Extreme", [_entry(structure_id="Building_02", peak_hour=5)], "en")
    assert "Building_02" in text
    assert "5 hours" in text
    assert text.startswith("URGENT:")


def test_numbered_steps_are_sequential_starting_at_one():
    text = generate_alert_text("Severe", [_entry()], "en")
    lines = text.splitlines()
    steps = lines[1:]
    assert [line.split(".")[0] for line in steps] == [str(i) for i in range(1, len(steps) + 1)]


def test_empty_top_risk_entries_never_fabricates_a_structure_name():
    text = generate_alert_text("Moderate", [], "en")
    assert "the affected area" in text
    assert "Building_" not in text


def test_unknown_severity_raises_typed_error():
    with pytest.raises(ValueError):
        generate_alert_text("Catastrophic", [_entry()], "en")


def test_unsupported_language_raises_typed_error():
    with pytest.raises(ValueError):
        generate_alert_text("Extreme", [_entry()], "fr")


def test_non_english_translates_each_line_separately_preserving_structure():
    """Numbering/structure must be reassembled in code, never left to the
    translation call -- confirmed here by checking translate_text is
    called once per line (headline + N steps), not once for the whole
    block."""
    calls = []

    def _fake_translate(text, source, target):
        calls.append(text)
        return f"[TA]{text}"

    with patch("backend.stage4.alerts.multilingual.translate_text", side_effect=_fake_translate):
        result = generate_alert_text("Severe", [_entry()], "ta")

    assert len(calls) == 4  # 1 headline + 3 Severe steps
    assert result.startswith("[TA]")
    assert "1. [TA]" in result
    assert "3. [TA]" in result


def test_generate_alert_audio_calls_tts_with_the_same_text():
    with patch("backend.stage4.alerts.multilingual.synthesize_speech") as mock_tts:
        mock_tts.return_value = b"RIFF...WAVE"
        audio = generate_alert_audio("Extreme", [_entry()], "en")

    assert audio == b"RIFF...WAVE"
    text_arg, lang_arg = mock_tts.call_args[0]
    assert "URGENT:" in text_arg
    assert lang_arg == "en"
