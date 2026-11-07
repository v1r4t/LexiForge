"""Gnani Timbre TTS client."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import (
    TTSAuthError,
    TTSRateLimitError,
    TTSUnavailableError,
    TTSValidationError,
)

SYNTHESIZE_PATH = "/v1/tts/synthesize"
DEFAULT_BASE_URL = "https://api.gnani.ai"


@dataclass(frozen=True)
class TTSResult:
    audio: bytes
    fmt: str
    sample_rate: int
    voice: str


class TimbreClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        transport=None,
        timeout: float = 60.0,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get("GNANI_API_KEY")
        if base_url is None:
            base_url = os.environ.get("GNANI_TTS_BASE_URL") or DEFAULT_BASE_URL
        if not api_key:
            raise TTSAuthError("API key is missing (GNANI_API_KEY).")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(transport=transport, timeout=timeout)

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str = "hi-IN",
        fmt: str = "wav",
    ) -> TTSResult:
        if not text or not text.strip():
            raise TTSValidationError("text is empty")
        if voice is None:
            voice = os.environ.get("GNANI_TTS_VOICE") or "default"

        url = self.base_url + SYNTHESIZE_PATH
        headers = {
            "X-API-Key-ID": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: dict[str, Any] = {
            "text": text,
            "voice": voice,
            "language": language,
            "format": fmt,
        }
        try:
            response = self._client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise TTSUnavailableError("request timed out") from exc
        except httpx.HTTPError as exc:
            raise TTSUnavailableError(f"request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise TTSAuthError(f"authentication failed: HTTP {response.status_code}")
        if response.status_code == 429:
            raise TTSRateLimitError("rate limited")
        if response.status_code == 400:
            raise TTSValidationError("validation error")
        if response.status_code >= 500:
            raise TTSUnavailableError(f"server error: HTTP {response.status_code}")

        audio = response.content
        sample_rate = 24000
        # Try to extract sample rate from headers if present
        if "x-sample-rate" in response.headers:
            try:
                sample_rate = int(response.headers["x-sample-rate"])
            except Exception:
                pass
        elif "sample-rate" in response.headers:
            try:
                sample_rate = int(response.headers["sample-rate"])
            except Exception:
                pass

        return TTSResult(audio=audio, fmt=fmt, sample_rate=sample_rate, voice=voice)
