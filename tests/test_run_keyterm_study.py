"""Tests for the real-audio study runner. No network: fake run_pilot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_keyterm_pilot import ARM_NAMES, PilotResult
from scripts.run_keyterm_study import load_manifest, run_study


def _manifest(tmp_path: Path, calls=None) -> Path:
    ref = tmp_path / "c01.txt"
    ref.write_text("mera UPI fail hua", encoding="utf-8")
    payload = {
        "study_id": "study-1",
        "calls": calls
        or [
            {
                "call_id": "c01",
                "audio": str(tmp_path / "c01.wav"),
                "reference": str(ref),
                "call_type": "mandate_fail",
                "utterances": 5,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _scored_result(call_id: str) -> PilotResult:
    arms = []
    for name in ARM_NAMES:
        rows = [
            {
                "call_id": call_id,
                "term_id": "UPI",
                "origin": "real",
                "hit": True,
                "insertion": False,
                "in_denom": True,
            },
            {
                "call_id": call_id,
                "real_recall": {"num": 1, "den": 1},
                "insertions_per_utterance": {"num": 0, "den": 5},
                "wer": 0.1,
            },
        ]
        arms.append(
            {
                "name": name,
                "rows": rows,
                "metrics": {
                    "real_recall": {"num": 1, "den": 1},
                    "insertions_per_utterance": {"num": 0, "den": 5},
                    "wer": 0.1,
                },
            }
        )
    return PilotResult(dry_run=False, arms={}, scored_arms=arms)


def test_load_manifest_rejects_missing_study_id(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"calls": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="study_id"):
        load_manifest(path)


def test_load_manifest_requires_reference(tmp_path):
    path = _manifest(
        tmp_path,
        calls=[{"call_id": "c01", "audio": "a.wav", "utterances": 1}],
    )
    with pytest.raises(ValueError, match="reference"):
        load_manifest(path)


def test_dry_run_never_builds_a_report(tmp_path):
    manifest = load_manifest(_manifest(tmp_path))
    calls = []

    def fake_pilot(call_id, audio, glossary, **kwargs):
        calls.append((call_id, kwargs))
        return PilotResult(dry_run=True, arms={})

    result = run_study(
        manifest,
        [],
        execute=False,
        out_dir=tmp_path / "runs",
        run_pilot_fn=fake_pilot,
    )

    assert result.dry_run is True
    assert len(result.call_results) == 1
    assert calls[0][0] == "c01"
    assert calls[0][1]["reference_text"] == "mera UPI fail hua"
    assert (tmp_path / "runs" / "study-1" / "summary.json").exists()
    assert not (tmp_path / "runs" / "study-1" / "report.md").exists()


def test_execute_aggregates_two_calls(tmp_path):
    calls = [
        {
            "call_id": "c01",
            "audio": "a1.wav",
            "reference_text": "mera UPI fail hua",
            "call_type": "mandate_fail",
            "utterances": 5,
        },
        {
            "call_id": "c02",
            "audio": "a2.wav",
            "reference_text": "mera UPI fail hua",
            "call_type": "mandate_fail",
            "utterances": 5,
        },
    ]
    manifest = load_manifest(_manifest(tmp_path, calls=calls))

    def fake_pilot(call_id, audio, glossary, **kwargs):
        return _scored_result(call_id)

    result = run_study(
        manifest,
        [],
        execute=True,
        out_dir=tmp_path / "runs",
        run_pilot_fn=fake_pilot,
    )

    assert result.dry_run is False
    assert result.summary["n_calls"] == 2
    assert result.summary["verdict"] in {"PASS", "FAIL", "INCONCLUSIVE"}
    assert "Term-level appendix" in result.report_markdown
    assert result.report_path is not None and result.report_path.exists()
