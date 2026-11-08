"""Tests for the real-audio manifest checker."""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path

from scripts.record_check import check_manifest


def _wav(path: Path, frames: int = 8000, fill: int = 0) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(struct.pack("<h", fill) * frames)
    return path


def _manifest(tmp_path: Path, audio: Path, call_id: str = "c01") -> Path:
    reference = tmp_path / "c01.txt"
    reference.write_text("mera UPI fail hua", encoding="utf-8")
    payload = {
        "study_id": "study-1",
        "calls": [
            {
                "call_id": call_id,
                "audio": str(audio),
                "reference": str(reference),
                "call_type": "mandate_fail",
                "utterances": 1,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_valid_wav_passes_with_duration_and_rate(tmp_path):
    audio = _wav(tmp_path / "c01.wav")
    report = check_manifest(_manifest(tmp_path, audio))
    assert report["ok"] is True
    assert report["errors"] == []
    assert report["calls"][0]["duration_s"] == 1.0
    assert report["calls"][0]["sample_rate"] == 8000


def test_missing_audio_fails(tmp_path):
    report = check_manifest(_manifest(tmp_path, tmp_path / "missing.wav"))
    assert report["ok"] is False
    assert any("audio not found" in error for error in report["errors"])


def test_duplicate_call_ids_fail(tmp_path):
    audio = _wav(tmp_path / "c01.wav")
    path = _manifest(tmp_path, audio)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["calls"].append(dict(payload["calls"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = check_manifest(path)
    assert report["ok"] is False
    assert any("duplicate call_id" in error for error in report["errors"])


def test_clipping_is_a_warning(tmp_path):
    audio = _wav(tmp_path / "c01.wav", fill=32767)
    report = check_manifest(_manifest(tmp_path, audio))
    assert report["ok"] is True
    assert any("clipping" in warning for warning in report["warnings"])


def test_non_wav_is_accepted_with_warning(tmp_path):
    audio = tmp_path / "c01.mp3"
    audio.write_bytes(b"not really mp3")
    report = check_manifest(_manifest(tmp_path, audio))
    assert report["ok"] is True
    assert any("non-WAV" in warning for warning in report["warnings"])
