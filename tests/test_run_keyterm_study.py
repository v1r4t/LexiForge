"""Tests for the real-audio study runner. No network: fake run_pilot."""

from __future__ import annotations

import json
import os
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


def _three_call_manifest(tmp_path: Path) -> dict:
    calls = [
        {
            "call_id": f"c{index:02d}",
            "audio": f"a{index}.wav",
            "reference_text": "mera UPI fail hua",
            "call_type": "mandate_fail",
            "utterances": 5,
        }
        for index in (1, 2, 3)
    ]
    return load_manifest(_manifest(tmp_path, calls=calls))


def _write_transcripts(run_dir: Path, call_id: str, text: str = "mera UPI fail hua") -> None:
    """Write the four P01-shaped arm transcripts a resumed call would leave."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ARM_NAMES:
        payload = {
            "call_id": call_id,
            "arm": name,
            "text": text,
            "rows": {"0": {"text": text}},
            "config": {},
            "status": "COMPLETED",
        }
        (run_dir / f"{name}.transcript.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )


def _age(path: Path, seconds: float) -> None:
    stamp = path.stat().st_mtime - seconds
    os.utime(path, (stamp, stamp))


def test_one_raising_call_is_logged_and_the_rest_merge(tmp_path):
    manifest = _three_call_manifest(tmp_path)

    def fake_pilot(call_id, audio, glossary, **kwargs):
        if call_id == "c02":
            raise RuntimeError("boom for c02")
        return _scored_result(call_id)

    result = run_study(
        manifest,
        [],
        execute=True,
        out_dir=tmp_path / "runs",
        run_pilot_fn=fake_pilot,
    )

    assert result.failed_calls == ["c02"]
    assert result.skipped_calls == []
    assert len(result.call_results) == 2
    assert result.summary["n_calls"] == 2
    assert result.summary["failures"][0]["call_id"] == "c02"
    assert "boom for c02" in result.summary["failures"][0]["error"]
    logged = json.loads(
        (tmp_path / "runs" / "study-1" / "summary.json").read_text(encoding="utf-8")
    )
    assert logged["failures"][0]["call_id"] == "c02"
    assert result.report_path is not None and result.report_path.exists()


def test_continue_on_error_false_raises(tmp_path):
    manifest = _three_call_manifest(tmp_path)

    def fake_pilot(call_id, audio, glossary, **kwargs):
        raise RuntimeError("stop here")

    with pytest.raises(RuntimeError, match="stop here"):
        run_study(
            manifest,
            [],
            execute=True,
            out_dir=tmp_path / "runs",
            continue_on_error=False,
            run_pilot_fn=fake_pilot,
        )


def test_resume_skips_only_calls_with_newer_transcripts(tmp_path):
    manifest = _three_call_manifest(tmp_path)
    runs = tmp_path / "runs"
    fresh_dir = runs / "c01"
    stale_dir = runs / "c02"
    for run_dir in (fresh_dir, stale_dir):
        run_dir.mkdir(parents=True)
        plan = run_dir / "plan.json"
        plan.write_text(json.dumps({"call_id": run_dir.name}), encoding="utf-8")
        _write_transcripts(run_dir, run_dir.name)
        _age(plan, 100)
    _age(stale_dir / "baseline.transcript.json", 200)

    called = []

    def fake_pilot(call_id, audio, glossary, **kwargs):
        called.append(call_id)
        return _scored_result(call_id)

    glossary = [{"term_id": "UPI", "term": "UPI", "origin": "real"}]
    result = run_study(
        manifest,
        glossary,
        execute=True,
        out_dir=runs,
        resume=True,
        run_pilot_fn=fake_pilot,
    )

    assert called == ["c02", "c03"]
    assert result.skipped_calls == ["c01"]
    assert result.failed_calls == []
    # The resumed call is still observed in the pooled report.
    resumed_rows = [
        row
        for arm in result.call_results[0].scored_arms
        for row in arm.get("rows") or []
        if row.get("call_id") == "c01"
    ]
    assert resumed_rows
    assert result.summary["n_calls"] == 3


def test_resume_false_reruns_every_call(tmp_path):
    manifest = _three_call_manifest(tmp_path)
    fresh_dir = tmp_path / "runs" / "c01"
    fresh_dir.mkdir(parents=True)
    plan = fresh_dir / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    _write_transcripts(fresh_dir, "c01")
    _age(plan, 100)

    called = []

    def fake_pilot(call_id, audio, glossary, **kwargs):
        called.append(call_id)
        return _scored_result(call_id)

    run_study(
        manifest,
        [],
        execute=True,
        out_dir=tmp_path / "runs",
        resume=False,
        run_pilot_fn=fake_pilot,
    )

    assert called == ["c01", "c02", "c03"]


def test_unknown_arm_raises(tmp_path):
    manifest = _three_call_manifest(tmp_path)
    with pytest.raises(ValueError, match="unknown arm"):
        run_study(
            manifest,
            [],
            execute=False,
            out_dir=tmp_path / "runs",
            arms=["baseline", "nope-200"],
            run_pilot_fn=lambda *a, **k: _scored_result("c01"),
        )


def test_extra_arms_are_accepted_and_merged(tmp_path):
    manifest = _three_call_manifest(tmp_path)

    def fake_pilot(call_id, audio, glossary, **kwargs):
        assert "oracle-200" in kwargs["arms"]
        result = _scored_result(call_id)
        result.scored_arms.append(
            {
                "name": "oracle-200",
                "rows": [{"call_id": call_id, "real_recall": {"num": 1, "den": 1}}],
                "metrics": {"real_recall": {"num": 1, "den": 1}},
            }
        )
        return result

    result = run_study(
        manifest,
        [],
        execute=True,
        out_dir=tmp_path / "runs",
        arms=["baseline", "selected-200", "mismatched-200", "hard-negative-200", "oracle-200"],
        run_pilot_fn=fake_pilot,
    )

    merged = {arm["name"] for arm in result.call_results[0].scored_arms}
    assert "oracle-200" in merged
    assert "oracle-200" in result.report_markdown
    assert result.failed_calls == []
