"""Sarvam AI client — real translation + text-to-speech, confirmed
in-session (2026-08-20), per explicit project-owner decision to use
Sarvam AI for multilingual alert text/audio instead of hand-authored
translations.

REAL, CONFIRMED API SHAPE (fetched directly from docs.sarvam.ai this
session, not assumed or recalled from memory)
---------------------------------------------------------------------------
Auth: header `api-subscription-key: <SARVAM_API_KEY>` on every request
(confirmed identical for both endpoints below via a real curl example in
Sarvam's own ElevenLabs-migration guide).

POST https://api.sarvam.ai/translate
  Request:  {"input": str, "source_language_code": str,
             "target_language_code": str}  (model/mode/etc. all optional
             -- omitted here, using the API's own defaults rather than
             guessing which named model variant is "best")
  Response: {"request_id": str, "translated_text": str,
             "source_language_code": str}

POST https://api.sarvam.ai/text-to-speech
  Request:  {"text": str, "language_code": str}  (speaker/model/pace/etc.
             all optional -- omitted, using the API's own defaults)
  Response: {"audios": [str, ...]}  -- base64-encoded WAV strings

Language codes are BCP-47-style, confirmed real values used across
Sarvam's docs: `en-IN`, `ta-IN` (and others this project doesn't use yet).
This project's own `language` parameter elsewhere is the shorter "en"/"ta"
(matching `SUPPORTED_LANGUAGES` in config.py) -- `_SARVAM_LANGUAGE_CODE`
maps between the two; never passes the short code directly to the API.
"""

from __future__ import annotations

import base64
from typing import Dict

import requests

from backend.stage4.config import settings

SARVAM_BASE_URL = "https://api.sarvam.ai"

#: 2026-08-20 addition, per explicit project-owner request: Hindi, Telugu,
#: Malayalam, Kannada added alongside English/Tamil. All four real codes
#: confirmed directly against Sarvam's own docs this session (the same
#: fetch that confirmed en-IN/ta-IN originally listed the full real set:
#: "hi-IN, bn-IN, kn-IN, ml-IN, mr-IN, od-IN, pa-IN, ta-IN, te-IN, en-IN,
#: gu-IN") -- not guessed or assumed from general BCP-47 convention.
_SARVAM_LANGUAGE_CODE: Dict[str, str] = {
    "en": "en-IN",
    "ta": "ta-IN",
    "hi": "hi-IN",
    "te": "te-IN",
    "ml": "ml-IN",
    "kn": "kn-IN",
}

_REQUEST_TIMEOUT_S = 30


class SarvamApiError(Exception):
    """Raised when a Sarvam AI request fails or returns an unexpected shape."""


class SarvamNotConfiguredError(SarvamApiError):
    """Raised when `SARVAM_API_KEY` isn't set -- never silently falls
    back to fabricated/untranslated text in its place."""


def _headers() -> dict:
    if not settings.sarvam_api_key:
        raise SarvamNotConfiguredError(
            "SARVAM_API_KEY is not configured (see backend/stage4/.env) -- "
            "cannot call Sarvam AI."
        )
    return {
        "api-subscription-key": settings.sarvam_api_key,
        "Content-Type": "application/json",
    }


def sarvam_language_code(language: str) -> str:
    """Map this project's short language code ("en"/"ta") to Sarvam's
    real BCP-47-style code. Raises `ValueError` for an unsupported one --
    never guesses a code that might not be real."""
    if language not in _SARVAM_LANGUAGE_CODE:
        raise ValueError(
            f"No Sarvam language code mapping for {language!r} -- expected "
            f"one of {sorted(_SARVAM_LANGUAGE_CODE)}."
        )
    return _SARVAM_LANGUAGE_CODE[language]


def translate_text(text: str, source_language: str, target_language: str) -> str:
    """Real, live translation via Sarvam AI's `/translate` endpoint.

    `source_language`/`target_language` are this project's short codes
    ("en"/"ta"), mapped internally to Sarvam's real BCP-47-style codes.

    Raises:
        SarvamNotConfiguredError: no API key set.
        SarvamApiError: the API call failed or returned an unexpected shape.
    """
    if source_language == target_language:
        return text  # no real translation needed; never call the API for a no-op

    payload = {
        "input": text,
        "source_language_code": sarvam_language_code(source_language),
        "target_language_code": sarvam_language_code(target_language),
    }
    try:
        response = requests.post(
            f"{SARVAM_BASE_URL}/translate",
            json=payload,
            headers=_headers(),
            timeout=_REQUEST_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise SarvamApiError(
            f"Sarvam /translate failed (HTTP {response.status_code}): {response.text[:300]}"
        ) from exc
    except requests.RequestException as exc:
        raise SarvamApiError(f"Sarvam /translate request failed: {exc}") from exc

    body = response.json()
    if "translated_text" not in body:
        raise SarvamApiError(
            f"Sarvam /translate response missing 'translated_text': {body!r}"
        )
    return str(body["translated_text"])


def synthesize_speech(text: str, language: str) -> bytes:
    """Real, live text-to-speech via Sarvam AI's `/text-to-speech`
    endpoint. Returns raw WAV audio bytes (decoded from the API's
    base64-encoded response, not the base64 string itself).

    Raises:
        SarvamNotConfiguredError: no API key set.
        SarvamApiError: the API call failed or returned an unexpected shape.
    """
    payload = {
        "text": text,
        "language_code": sarvam_language_code(language),
    }
    try:
        response = requests.post(
            f"{SARVAM_BASE_URL}/text-to-speech",
            json=payload,
            headers=_headers(),
            timeout=_REQUEST_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise SarvamApiError(
            f"Sarvam /text-to-speech failed (HTTP {response.status_code}): {response.text[:300]}"
        ) from exc
    except requests.RequestException as exc:
        raise SarvamApiError(f"Sarvam /text-to-speech request failed: {exc}") from exc

    body = response.json()
    audios = body.get("audios")
    if not audios:
        raise SarvamApiError(f"Sarvam /text-to-speech response has no 'audios': {body!r}")
    return base64.b64decode(audios[0])
