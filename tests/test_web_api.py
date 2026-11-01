"""Tests for web/api.py: provenance, reload, and shape.

The dashboard must be able to say whether it is showing measured data or the
hand-written sample, and it must pick up a re-export without a restart.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _get(app, path: str):
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(_run())


@pytest.fixture()
def api(tmp_path: Path, monkeypatch):
    """Reload web.api pointed at a temporary data directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "demo_config.json").write_text(
        json.dumps({"mode": "precomputed", "data_source": "measured"}), encoding="utf-8"
    )
    (data_dir / "calls.json").write_text(
        json.dumps([{"call_id": "c01", "call_type": "upi_failed", "duration_s": 1.0, "has_audio": True}]),
        encoding="utf-8",
    )
    (data_dir / "transcripts.json").write_text(
        json.dumps({"c01": {"baseline": [{"text": "mera", "status": "same"}]}}),
        encoding="utf-8",
    )
    (data_dir / "terms.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "results.json").write_text(
        json.dumps({"is_sample": False, "contrasts": [], "control": {}}), encoding="utf-8"
    )

    monkeypatch.setenv("LEXIFORGE_WEB_DATA", str(data_dir))
    from web import api as api_module

    importlib.reload(api_module)
    yield api_module, data_dir
    monkeypatch.delenv("LEXIFORGE_WEB_DATA", raising=False)
    importlib.reload(api_module)


def test_meta_reports_measured_source(api):
    api_module, _ = api
    payload = _get(api_module.app, "/meta").json()
    assert payload["is_sample"] is False
    assert payload["data_source"] == "measured"
    assert payload["call_count"] == 1
    assert payload["conditions"] == ["baseline"]


def test_sample_dataset_is_flagged(api):
    api_module, data_dir = api
    (data_dir / "demo_config.json").write_text(
        json.dumps({"mode": "precomputed", "data_source": "illustrative_sample"}),
        encoding="utf-8",
    )
    payload = _get(api_module.app, "/meta").json()
    assert payload["is_sample"] is True


def test_reload_picks_up_new_files_without_restart(api):
    api_module, data_dir = api
    assert _get(api_module.app, "/calls").json()[0]["call_id"] == "c01"

    (data_dir / "calls.json").write_text(
        json.dumps(
            [
                {"call_id": "c01", "call_type": "upi_failed", "duration_s": 1.0, "has_audio": True},
                {"call_id": "c02", "call_type": "kyc", "duration_s": 2.0, "has_audio": True},
            ]
        ),
        encoding="utf-8",
    )
    # Touch mtime explicitly; some filesystems have coarse timestamps.
    os.utime(data_dir / "calls.json", (1e18, 1e18))

    calls = _get(api_module.app, "/calls").json()
    assert [c["call_id"] for c in calls] == ["c01", "c02"]

    reloaded = _get(api_module.app, "/meta").json()
    assert reloaded["call_count"] == 2


def test_transcripts_only_return_conditions_present(api):
    api_module, _ = api
    payload = _get(api_module.app, "/calls/c01/transcripts").json()
    assert set(payload) == {"baseline"}


def test_missing_call_returns_empty_structure(api):
    api_module, _ = api
    payload = _get(api_module.app, "/calls/zzz/transcripts").json()
    assert payload == {"baseline": [], "mismatched": [], "adaptive": [], "oracle": []}


def test_health_includes_data_source(api):
    api_module, _ = api
    payload = _get(api_module.app, "/health").json()
    assert payload["status"] == "ok"
    assert payload["data_source"] == "measured"


def test_exported_sample_directory_is_marked_as_sample():
    """The committed placeholder set must never claim to be measured."""
    from web import api as api_module

    config = json.loads(
        (Path(api_module.__file__).parent / "data" / "sample" / "demo_config.json").read_text(
            encoding="utf-8"
        )
    )
    assert config["data_source"] == "illustrative_sample"

    results = json.loads(
        (Path(api_module.__file__).parent / "data" / "sample" / "results.json").read_text(
            encoding="utf-8"
        )
    )
    assert results["is_sample"] is True
    assert all(contrast["verdict"] == "sample" for contrast in results["contrasts"])
