"""Gnani Timbre TTS client.

Contract verified against
https://docs.gnani.ai/api/TTS/tts-inference.md:

    POST https://api.vachana.ai/api/v1/tts/inference
    X-API-Key-ID: <key>
    JSON body: text, voice, model, language, speed?, audio_config
    Response: raw binary audio in the requested container.

Defaults target the Hinglish telephony pilot: Timbre v2.5 voice ``Poorvi``,
``language="hi-en"``, 8 kHz mono 16-bit WAV.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import (
    TTSAuthError,
    TTSRateLimitError,
    TTSUnavailableError,
    TTSValidationError,
)

SYNTHESIZE_PATH = "/api/v1/tts/inference"
DEFAULT_BASE_URL = "https://api.vachana.ai"
DEFAULT_MODEL = "timbre-v2.5"
DEFAULT_VOICE = "Poorvi"  # Timbre v2.5 Hinglish voice
DEFAULT_LANGUAGE = "hi-en"
DEFAULT_SAMPLE_RATE = 8000


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
            base_url = (
                os.environ.get("GNANI_TTS_BASE_URL")
                or os.environ.get("GNANI_BASE_URL")
                or DEFAULT_BASE_URL
            )
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
        model: str = DEFAULT_MODEL,
        language: str = DEFAULT_LANGUAGE,
        fmt: str = "wav",
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        speed: float | None = None,
    ) -> TTSResult:
        if not text or not text.strip():
            raise TTSValidationError("text is empty")
        if voice is None:
            voice = os.environ.get("GNANI_TTS_VOICE") or DEFAULT_VOICE

        audio_config: dict[str, Any] = {
            "sample_rate": sample_rate,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": fmt,
        }
        payload: dict[str, Any] = {
            "text": text,
            "voice": voice,
            "model": model,
            "language": language,
            "audio_config": audio_config,
        }
        if speed is not None:
            payload["speed"] = speed

        url = self.base_url + SYNTHESIZE_PATH
        headers = {"X-API-Key-ID": self.api_key}
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
            raise TTSValidationError(_error_message(response))
        if response.status_code >= 500:
            raise TTSUnavailableError(
                f"server error: HTTP {response.status_code}: {_error_message(response)}"
            )

        return TTSResult(
            audio=normalize_wav(response.content) if fmt == "wav" else response.content,
            fmt=fmt,
            sample_rate=sample_rate,
            voice=voice,
        )


def normalize_wav(audio: bytes) -> bytes:
    """Patch streaming WAV headers whose RIFF/data sizes are ``0xFFFFFFFF``.

    Gnani Timbre returns a WAV with unknown-length markers; Python's ``wave``
    module (and batch upload validation) needs real sizes.
    """
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return audio
    data = bytearray(audio)
    data[4:8] = struct.pack("<I", len(data) - 8)
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = bytes(data[pos : pos + 4])
        size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        if chunk_id == b"data":
            data[pos + 4 : pos + 8] = struct.pack("<I", len(data) - (pos + 8))
            break
        pos += 8 + size + (size & 1)
    return bytes(data)


def _error_message(response: httpx.Response) -> str:
    """Best-effort error text without echoing credentials."""
    try:
        body = response.json()
    except Exception:
        return response.text[:200]
    if isinstance(body, dict):
        for key in ("message", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:300]
    return str(body)[:300]
