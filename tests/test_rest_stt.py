"""Tests for the REST STT fallback client. No network."""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path

import httpx
import pytest

from lexiforge.api.client import BatchApiError
from lexiforge.api.rest_stt import RestSttClient


def _wav(path: Path, seconds: float) -> Path:
    frames = int(8000 * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(struct.pack("<h", 0) * frames)
    return path


def _client(handler) -> RestSttClient:
    return RestSttClient(
        api_key="k",
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
        attempts=2,
        backoff_base=0,
    )


def test_transcribes_and_stores_result(tmp_path):
    audio = _wav(tmp_path / "c00.wav", 1.0)
    seen = []

    def handler(request):
        seen.append(request.read())
        return httpx.Response(
            200,
            json={"transcript": "mera UPI fail hua", "detected_language_code": "hi-IN"},
        )

    client = _client(handler)
    job_id = client.create_job(
        {"model": "prisma-v3.0", "language_code": "hi-IN,en-IN", "format": "transcribe",
         "keyterms": ["UPI", "NEFT"]},
        [audio],
    )
    body = seen[0]
    assert b"keyterms" in body
    assert json.dumps(["UPI", "NEFT"], ensure_ascii=False).encode() in body
    assert b"prisma-v3.0" in body
    assert client.wait(job_id) == "COMPLETED"
    rows = client.fetch_all_transcripts(job_id)
    assert rows["c00.wav"]["text"] == "mera UPI fail hua"
    assert rows["c00.wav"]["detected_language_code"] == "hi-IN"


def test_long_wav_is_chunked_with_previous_text(tmp_path):
    audio = _wav(tmp_path / "c03.wav", 35.0)
    bodies = []

    def handler(request):
        bodies.append(request.read())
        return httpx.Response(
            200, json={"transcript": f"part{len(bodies)}", "detected_language_code": "hi-IN"}
        )

    client = _client(handler)
    job_id = client.create_job(
        {"model": "prisma-v3.0", "language_code": "hi-IN,en-IN", "format": "transcribe"},
        [audio],
    )
    assert len(bodies) == 2
    assert b"previous_text" in bodies[1]
    assert client.fetch_all_transcripts(job_id)["c03.wav"]["text"] == "part1 part2"


def test_invalid_context_raises_typed_error(tmp_path):
    audio = _wav(tmp_path / "c00.wav", 1.0)

    def handler(request):
        return httpx.Response(
            400, json={"success": False, "error": {"type": "INVALID_CONTEXT", "message": "bad"}}
        )

    client = _client(handler)
    with pytest.raises(BatchApiError) as info:
        client.create_job({"model": "prisma-v3.0", "language_code": "hi-IN"}, [audio])
    assert info.value.status_code == 400
    assert info.value.code == "INVALID_CONTEXT"
