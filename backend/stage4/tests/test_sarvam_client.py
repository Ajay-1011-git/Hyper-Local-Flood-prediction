"""Tests for `alerts/sarvam_client.py` (T4A.2).

External network is mocked throughout (per this project's T1B.12/T1A.12
convention), except one real live call at the bottom, gated behind
`requires_live_host` (skips automatically if offline or
`SKIP_LIVE_NETWORK_TESTS=1`) -- the actual proof this integration works
against the real Sarvam API, not just a mock of it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from backend.stage4.alerts.sarvam_client import (
    SarvamApiError,
    SarvamNotConfiguredError,
    sarvam_language_code,
    synthesize_speech,
    translate_text,
)
from backend.stage4.config import settings
from backend.stage4.tests.conftest import requires_live_host


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text or str(json_body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self._json_body


def test_sarvam_language_code_maps_real_short_codes():
    assert sarvam_language_code("en") == "en-IN"
    assert sarvam_language_code("ta") == "ta-IN"
    assert sarvam_language_code("hi") == "hi-IN"
    assert sarvam_language_code("te") == "te-IN"
    assert sarvam_language_code("ml") == "ml-IN"
    assert sarvam_language_code("kn") == "kn-IN"


def test_sarvam_language_code_rejects_unsupported_language():
    with pytest.raises(ValueError):
        sarvam_language_code("fr")


def test_translate_text_no_op_when_source_equals_target():
    """Never calls the API for a real no-translation-needed case."""
    with patch("backend.stage4.alerts.sarvam_client.requests.post") as mock_post:
        result = translate_text("hello", "en", "en")
    assert result == "hello"
    mock_post.assert_not_called()


def test_translate_text_raises_when_not_configured():
    with patch.object(settings, "sarvam_api_key", None):
        with pytest.raises(SarvamNotConfiguredError):
            translate_text("hello", "en", "ta")


def test_translate_text_sends_real_confirmed_request_shape():
    captured = {}

    def _fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"request_id": "r1", "translated_text": "வணக்கம்", "source_language_code": "en-IN"})

    with patch.object(settings, "sarvam_api_key", "fake-key"):
        with patch("backend.stage4.alerts.sarvam_client.requests.post", side_effect=_fake_post):
            result = translate_text("hello", "en", "ta")

    assert result == "வணக்கம்"
    assert captured["url"] == "https://api.sarvam.ai/translate"
    assert captured["json"] == {
        "input": "hello",
        "source_language_code": "en-IN",
        "target_language_code": "ta-IN",
    }
    assert captured["headers"]["api-subscription-key"] == "fake-key"


def test_translate_text_raises_typed_error_on_http_failure():
    def _fake_post(url, json, headers, timeout):
        return _FakeResponse(401, {}, text="Unauthorized")

    with patch.object(settings, "sarvam_api_key", "bad-key"):
        with patch("backend.stage4.alerts.sarvam_client.requests.post", side_effect=_fake_post):
            with pytest.raises(SarvamApiError):
                translate_text("hello", "en", "ta")


def test_synthesize_speech_decodes_real_base64_response():
    import base64

    real_wav_bytes = b"RIFF....WAVEfmt "
    encoded = base64.b64encode(real_wav_bytes).decode("ascii")

    def _fake_post(url, json, headers, timeout):
        assert url == "https://api.sarvam.ai/text-to-speech"
        assert json == {"text": "hello", "language_code": "en-IN"}
        return _FakeResponse(200, {"audios": [encoded]})

    with patch.object(settings, "sarvam_api_key", "fake-key"):
        with patch("backend.stage4.alerts.sarvam_client.requests.post", side_effect=_fake_post):
            result = synthesize_speech("hello", "en")

    assert result == real_wav_bytes


def test_synthesize_speech_raises_when_not_configured():
    with patch.object(settings, "sarvam_api_key", None):
        with pytest.raises(SarvamNotConfiguredError):
            synthesize_speech("hello", "en")


# --------------------------------------------------------- real, live call


@requires_live_host("api.sarvam.ai")
def test_real_live_translate_call():
    if not settings.sarvam_api_key:
        pytest.skip("SARVAM_API_KEY not configured locally")
    result = translate_text("Rising water expected within 5 hours.", "en", "ta")
    assert isinstance(result, str)
    assert len(result) > 0
    assert result != "Rising water expected within 5 hours."  # a real translation happened


@requires_live_host("api.sarvam.ai")
@pytest.mark.parametrize("language", ["hi", "te", "ml", "kn"])
def test_real_live_translate_call_for_each_new_language(language):
    """2026-08-20 addition: Hindi/Telugu/Malayalam/Kannada, per explicit
    project-owner request -- each verified against the real live API,
    not just the code-mapping unit test above."""
    if not settings.sarvam_api_key:
        pytest.skip("SARVAM_API_KEY not configured locally")
    result = translate_text("Rising water expected within 5 hours.", "en", language)
    assert isinstance(result, str)
    assert len(result) > 0
    assert result != "Rising water expected within 5 hours."
