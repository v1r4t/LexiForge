"""Tests for the synthetic recording generator. No network."""

from __future__ import annotations

import io
import wave

import numpy as np

from scripts.synthesize_recording_pack import synthesize_call


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        samples = (np.sin(np.linspace(0, 20, 8000)) * 2000).astype("<i2")
        handle.writeframes(samples.tobytes())
    return buffer.getvalue()


class FakeTTS:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, *, voice=None, language=None, sample_rate=8000):
        self.calls.append((text, voice, language))
        from lexiforge.tts.client import TTSResult

        return TTSResult(audio=_wav_bytes(), fmt="wav", sample_rate=8000, voice=voice or "")


def test_synthesizes_two_roles_and_telephony_processes(tmp_path):
    script = {
        "call_id": "c00",
        "turns": [
            {"idx": 1, "speaker": "AGT", "text": "Namaste ji."},
            {"idx": 2, "speaker": "CUS", "text": "Mera NEFT fail hua."},
        ],
    }
    client = FakeTTS()
    out = tmp_path / "c00.wav"
    summary = synthesize_call("c00", script, client=client, out_path=out, gap_s=0.1)

    assert out.exists()
    assert summary["seconds"] > 0
    assert summary["voices"] == ["Deepak", "Poorvi"]
    assert client.calls[0][1:] == ("Deepak", "hi-IN")
    assert client.calls[1][1:] == ("Poorvi", "hi-en")
    assert "mu_law_encode_decode" in summary["chain"]

    with wave.open(str(out), "rb") as handle:
        assert handle.getframerate() == 8000
        assert handle.getnchannels() == 1
        assert handle.getnframes() > 0
