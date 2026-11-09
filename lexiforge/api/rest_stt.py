"""Synchronous REST STT client with the BatchClient interface.

Batch transcription is asynchronous and can queue indefinitely. This adapter
lets the pilot/study code run against ``POST /stt/v3`` instead:

- ``create_job`` transcribes immediately and stores the result under a job id;
- ``start_job`` and ``wait`` are no-ops;
- ``fetch_all_transcripts`` returns the stored transcript.

WAV files longer than the REST limit are split into chunks; later chunks carry
the previous transcript as ``previous_text``.
"""

from __future__ import annotations

import io
import json
import time
import uuid
import wave
from pathlib import Path

import httpx

from lexiforge.api.client import BatchApiError

__all__ = ["RestSttClient"]

_RETRY_STATUS = {429, 500, 502, 503, 504}


def _form_fields(config: dict) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in ("model", "language_code", "format"):
        value = config.get(key)
        if value is not None:
            fields[key] = str(value)
    keyterms = config.get("keyterms")
    if keyterms:
        fields["keyterms"] = json.dumps(list(keyterms), ensure_ascii=False)
    for key in ("topic", "previous_text"):
        value = config.get(key)
        if value:
            fields[key] = str(value)
    speakers = config.get("speaker_names")
    if speakers:
        fields["speaker_names"] = json.dumps(list(speakers), ensure_ascii=False)
    if config.get("enable_substitution"):
        fields["enable_substitution"] = "true"
        mapping = config.get("substitution_map")
        if mapping:
            fields["substitution_map"] = json.dumps(mapping, ensure_ascii=False)
    return fields


def _wav_chunks(payload: bytes, max_seconds: float) -> list[bytes]:
    """Split a WAV into <= max_seconds chunks; return the original if short."""
    try:
        with wave.open(io.BytesIO(payload), "rb") as handle:
            params = handle.getparams()
            rate = handle.getframerate()
            frames = handle.getnframes()
            if not rate or frames <= rate * max_seconds:
                return [payload]
            raw = handle.readframes(frames)
    except wave.Error:
        return [payload]

    chunk_frames = max(1, int(rate * max_seconds))
    chunks = []
    for start in range(0, frames, chunk_frames):
        take = min(chunk_frames, frames - start)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setparams(params)
            out.writeframes(raw[start * params.sampwidth * params.nchannels : (start + take) * params.sampwidth * params.nchannels])
        chunks.append(buffer.getvalue())
    return chunks


class RestSttClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        transport=None,
        timeout: float = 120.0,
        max_chunk_seconds: float = 29.0,
        attempts: int = 3,
        backoff_base: float = 2.0,
    ) -> None:
        import os

        if api_key is None:
            api_key = os.environ.get("GNANI_API_KEY")
        if base_url is None:
            base_url = os.environ.get("GNANI_BASE_URL") or "https://api.vachana.ai"
        if not api_key:
            raise BatchApiError("API key is missing (GNANI_API_KEY).", status_code=401)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_chunk_seconds = max_chunk_seconds
        self.attempts = attempts
        self.backoff_base = backoff_base
        self._http = httpx.Client(transport=transport, timeout=timeout)
        self._results: dict[str, dict] = {}

    def _post(self, fields: dict[str, str], audio: bytes, name: str) -> dict:
        last: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = self._http.post(
                    f"{self.base_url}/stt/v3",
                    headers={"X-API-Key-ID": self.api_key},
                    data=fields,
                    files={"audio_file": (name, audio, "audio/wav")},
                )
            except httpx.HTTPError as exc:
                last = exc
                if attempt < self.attempts - 1:
                    time.sleep(self.backoff_base * (2**attempt))
                    continue
                raise BatchApiError(f"rest transcription failed: {exc}") from exc
            if response.status_code < 400:
                return response.json()
            if response.status_code in _RETRY_STATUS and attempt < self.attempts - 1:
                time.sleep(self.backoff_base * (2**attempt))
                continue
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            code = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    code = error.get("type")
            raise BatchApiError(
                f"rest transcription failed: HTTP {response.status_code}",
                status_code=response.status_code,
                code=code,
                payload=payload,
            )
        raise BatchApiError(f"rest transcription failed: {last}")

    def create_job(self, config: dict, files: list[Path]) -> str:
        if len(files) != 1:
            raise ValueError("REST transcription accepts exactly one file per job")
        path = Path(files[0])
        chunks = _wav_chunks(path.read_bytes(), self.max_chunk_seconds)
        fields = _form_fields(config)
        parts: list[str] = []
        detected = None
        for index, chunk in enumerate(chunks):
            call_fields = dict(fields)
            if index > 0:
                previous = " ".join(parts)[-600:]
                if previous:
                    call_fields["previous_text"] = previous
            body = self._post(call_fields, chunk, f"{path.stem}_{index}.wav")
            text = body.get("transcript", "") if isinstance(body, dict) else ""
            parts.append(str(text))
            if isinstance(body, dict) and body.get("detected_language_code"):
                detected = body["detected_language_code"]
        job_id = f"rest-{uuid.uuid4().hex}"
        self._results[job_id] = {
            path.name: {
                "text": " ".join(part for part in parts if part),
                "detected_language_code": detected,
                "segments": [],
            }
        }
        return job_id

    def start_job(self, job_id: str) -> None:
        return None

    def wait(self, job_id: str, timeout_s: float = 1800, poll_interval=None) -> str:
        return "COMPLETED" if job_id in self._results else "FAILED"

    def fetch_all_transcripts(self, job_id: str, status: str = "COMPLETED") -> dict:
        return dict(self._results.get(job_id, {}))

    def close(self) -> None:
        self._http.close()
