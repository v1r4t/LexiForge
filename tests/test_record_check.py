"""Tests for the real-audio manifest checker."""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path

import pytest

from scripts.record_check import check_manifest, main


def _wav(
    path: Path,
    frames: int = 8000,
    fill: int = 1000,
    *,
    rate: int = 8000,
    channels: int = 1,
) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack("<h", fill) * frames * channels)
    return path


def _wav24(path: Path, frames: int = 8000, fill: int = 1_000_000) -> Path:
    payload = b"".join(int(fill).to_bytes(3, "little", signed=True) for _ in range(frames))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(3)
        handle.setframerate(8000)
        handle.writeframes(payload)
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


def test_valid_wav_reports_audio_metrics(tmp_path):
    audio = _wav(tmp_path / "c01.wav")
    report = check_manifest(_manifest(tmp_path, audio))
    assert report["ok"] is True
    assert report["errors"] == []
    call = report["calls"][0]
    assert call["duration_s"] == 1.0
    assert call["sample_rate"] == 8000
    assert call["channels"] == 1
    assert call["clipping_ratio"] == 0.0
    assert call["dc_offset"] == pytest.approx(1000 / 32768)
    assert call["silence_ratio"] == 0.0


def test_silent_audio_fails(tmp_path):
    audio = _wav(tmp_path / "c01.wav", fill=0)
    report = check_manifest(_manifest(tmp_path, audio))
    assert report["ok"] is False
    assert any("silent" in error for error in report["errors"])
    assert report["calls"][0]["silence_ratio"] == 1.0


def test_missing_audio_fails(tmp_path):
    report = check_manifest(_manifest(tmp_path, tmp_path / "missing.wav"))
    assert report["ok"] is False
    assert any("audio not found" in error for error in report["errors"])


def test_zero_frame_audio_fails(tmp_path):
    audio = _wav(tmp_path / "c01.wav", frames=0)
    report = check_manifest(_manifest(tmp_path, audio))
    assert report["ok"] is False
    assert any("zero frames" in error for error in report["errors"])


def test_duplicate_call_ids_fail(tmp_path):
    audio = _wav(tmp_path / "c01.wav")
    path = _manifest(tmp_path, audio)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["calls"].append(dict(payload["calls"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = check_manifest(path)
    assert report["ok"] is False
    assert any("duplicate call_id" in error for error in report["errors"])


def test_empty_reference_fails(tmp_path):
    audio = _wav(tmp_path / "c01.wav")
    path = _manifest(tmp_path, audio)
    (tmp_path / "c01.txt").write_text("   \n", encoding="utf-8")
    report = check_manifest(path)
    assert report["ok"] is False
    assert any("reference is empty" in error for error in report["errors"])


def test_clipping_is_a_warning(tmp_path):
    audio = _wav(tmp_path / "c01.wav", fill=32767)
    report = check_manifest(_manifest(tmp_path, audio))
    assert report["ok"] is True
    assert report["calls"][0]["clipping_ratio"] == 1.0
    assert any("clipping" in warning for warning in report["warnings"])


def test_low_sample_rate_warns_and_strict_fails(tmp_path):
    audio = _wav(tmp_path / "c01.wav", rate=4000)
    path = _manifest(tmp_path, audio)
    report = check_manifest(path)
    assert report["ok"] is True
    assert any("below 8 kHz" in warning for warning in report["warnings"])

    strict = check_manifest(path, strict=True)
    assert strict["ok"] is False
    assert strict["errors"] == []
    assert any("below 8 kHz" in warning for warning in strict["warnings"])


def test_duration_outside_bounds_warns_and_strict_fails(tmp_path):
    audio = _wav(tmp_path / "c01.wav", frames=4000)
    path = _manifest(tmp_path, audio)
    report = check_manifest(path)
    assert report["ok"] is True
    assert any("outside 8-60 s" in warning for warning in report["warnings"])

    strict = check_manifest(path, strict=True)
    assert strict["ok"] is False


def test_non_wav_is_accepted_with_warning(tmp_path):
    audio = tmp_path / "c01.mp3"
    audio.write_bytes(b"not really mp3")
    path = _manifest(tmp_path, audio)
    report = check_manifest(path)
    assert report["ok"] is True
    assert any("non-WAV" in warning for warning in report["warnings"])
    assert check_manifest(path, strict=True)["ok"] is False


def test_24_bit_wav_is_decoded_without_array_endianness(tmp_path):
    audio = _wav24(tmp_path / "c01.wav")
    report = check_manifest(_manifest(tmp_path, audio))
    assert report["ok"] is True
    call = report["calls"][0]
    assert call["clipping_ratio"] == 0.0
    assert call["silence_ratio"] == 0.0
    assert call["dc_offset"] == pytest.approx(1_000_000 / 8388608)


def test_json_output_is_ascii_and_exit_code_tracks_errors(tmp_path, capsys):
    audio = _wav(tmp_path / "c01.wav")
    path = _manifest(tmp_path, audio)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["study_id"] = "study-\u092b"
    payload["calls"][0].pop("reference")
    payload["calls"][0]["reference_text"] = "mera UPI \u092b\u0947\u0932 hua"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert main([str(path), "--json"]) == 0
    output = capsys.readouterr().out
    assert "\\u092b" in output
    output.encode("ascii")

    payload["calls"][0]["reference_text"] = "   "
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert main([str(path), "--json"]) == 1


def test_main_strict_promotes_warnings_to_failure(tmp_path):
    audio = _wav(tmp_path / "c01.wav", frames=4000)
    path = _manifest(tmp_path, audio)
    assert main([str(path), "--json"]) == 0
    assert main([str(path), "--json", "--strict"]) == 1
