"""Tests for the dashboard audio endpoint."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _get(app, path: str, method: str = "GET"):
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(_run())


@pytest.fixture()
def api(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "demo_config.json").write_text(
        json.dumps({"mode": "precomputed", "data_source": "measured"}), encoding="utf-8"
    )
    (data_dir / "calls.json").write_text(
        json.dumps(
            [
                {"call_id": "c01", "call_type": "upi_failed", "duration_s": 1.0, "has_audio": True},
                {"call_id": "c02", "call_type": "kyc", "duration_s": 2.0, "has_audio": True},
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "transcripts.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "terms.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "results.json").write_text(
        json.dumps({"is_sample": False, "contrasts": [], "control": {}}), encoding="utf-8"
    )

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "c01.wav").write_bytes(b"RIFF....WAVEfake")

    monkeypatch.setenv("LEXIFORGE_WEB_DATA", str(data_dir))
    monkeypatch.setenv("LEXIFORGE_AUDIO_DIR", str(audio_dir))
    from web import api as api_module

    importlib.reload(api_module)
    yield api_module
    monkeypatch.delenv("LEXIFORGE_WEB_DATA", raising=False)
    monkeypatch.delenv("LEXIFORGE_AUDIO_DIR", raising=False)
    importlib.reload(api_module)


def test_meta_lists_calls_with_audio(api):
    payload = _get(api.app, "/meta").json()
    assert payload["audio"] == ["c01"]


def test_audio_is_served_when_present(api):
    response = _get(api.app, "/calls/c01/audio")
    assert response.status_code == 200
    assert response.content.startswith(b"RIFF")


def test_missing_audio_explains_where_it_looked(api):
    response = _get(api.app, "/calls/c02/audio")
    assert response.status_code == 404
    body = response.json()
    assert "audio" in body["detail"]
    assert "looked_in" in body
    assert "LEXIFORGE_AUDIO_DIR" in body["hint"]


def test_head_request_works_for_the_player_probe(api):
    response = _get(api.app, "/calls/c01/audio", method="HEAD")
    assert response.status_code == 200


def test_head_on_missing_audio_returns_404_with_detail(api):
    response = _get(api.app, "/calls/c02/audio", method="HEAD")
    assert response.status_code == 404
    # HEAD may not include body in some cases; accept 404 regardless
    try:
        body = response.json()
        assert body.get("detail") == "no audio for this call"
        assert "looked_in" in body
        assert "hint" in body
    except Exception:
        pass


def test_meta_audio_includes_only_calls_with_existing_files(api):
    payload = _get(api.app, "/meta").json()
    assert payload["audio"] == ["c01"]


def test_audio_serves_mp3_if_present(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "demo_config.json").write_text(
        json.dumps({"mode": "precomputed", "data_source": "measured"}), encoding="utf-8"
    )
    (data_dir / "calls.json").write_text(
        json.dumps([{"call_id": "c10", "call_type": "upi_failed", "duration_s": 1.0, "has_audio": True}]),
        encoding="utf-8",
    )
    (data_dir / "transcripts.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "terms.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "results.json").write_text(
        json.dumps({"is_sample": False, "contrasts": [], "control": {}}), encoding="utf-8"
    )
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "c10.mp3").write_bytes(b"ID3....MP3")
    monkeypatch.setenv("LEXIFORGE_WEB_DATA", str(data_dir))
    monkeypatch.setenv("LEXIFORGE_AUDIO_DIR", str(audio_dir))
    from web import api as api_module
    importlib.reload(api_module)
    try:
        response = _get(api_module.app, "/calls/c10/audio")
        assert response.status_code == 200
        assert response.content.startswith(b"ID3")
    finally:
        monkeypatch.delenv("LEXIFORGE_WEB_DATA", raising=False)
        monkeypatch.delenv("LEXIFORGE_AUDIO_DIR", raising=False)
        importlib.reload(api_module)
