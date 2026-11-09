"""Tests for the offline study reproduction script (design §7, P18).

The fixture writes P01-style arm transcripts plus the study ``summary.json``.
``reproduce`` must re-score the transcripts locally, never call the network,
and treat the recorded verdict as a comparison target rather than evidence.
"""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from lexiforge.canon import CANON_VERSION
from scripts.reproduce_study import MissingTranscript, main, reproduce

ARMS = ("baseline", "selected-200", "mismatched-200", "hard-negative-200")
GLOSSARY = [
    {"term_id": "T0001", "canonical": "UPI", "origin": "real"},
    {"term_id": "F0001", "canonical": "NirSathi", "origin": "fictional"},
]
REFERENCE = "mera UPI fail hua aur NirSathi ne madad ki"


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _transcript(call_id: str, arm: str, text: str) -> dict:
    return {
        "call_id": call_id,
        "arm": arm,
        "text": text,
        "rows": {"f0": {"text": text}},
        "config": {"model": "prisma-v3.0", "format": "transcribe"},
        "status": "COMPLETED",
        "job_id": f"job-{call_id}-{arm}",
        "detected_language_code": "hi-IN",
        "canon_version": CANON_VERSION,
    }


def _fixture(
    tmp_path: Path,
    *,
    call_ids=("c01", "c02"),
    texts: dict[str, str] | None = None,
    summary_verdict: str | None = "PASS",
    arms=ARMS,
) -> dict[str, Path]:
    """Build manifest, glossary, plans, transcripts and summary.json."""
    runs = tmp_path / "runs"
    manifest_calls = []
    for call_id in call_ids:
        manifest_calls.append(
            {
                "call_id": call_id,
                "audio": f"audio/{call_id}.wav",
                "reference_text": REFERENCE,
                "call_type": "mandate_fail",
                "utterances": 2,
            }
        )
        call_dir = runs / call_id
        _write_json(
            call_dir / "plan.json",
            {
                "call_id": call_id,
                "arms": {arm: ["UPI"] for arm in arms},
                "jobs": {},
            },
        )
        for arm in arms:
            hypothesis = (texts or {}).get(f"{call_id}/{arm}", REFERENCE)
            _write_json(
                call_dir / f"{arm}.transcript.json",
                _transcript(call_id, arm, hypothesis),
            )

    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {"study_id": "study-1", "calls": manifest_calls},
    )
    glossary = tmp_path / "glossary.json"
    _write_json(glossary, GLOSSARY)
    study_dir = runs / "study-1"
    study_dir.mkdir(parents=True, exist_ok=True)
    if summary_verdict is not None:
        _write_json(
            study_dir / "summary.json",
            {
                "study_id": "study-1",
                "calls": len(call_ids),
                "dry_run": False,
                "verdict": summary_verdict,
                "n_calls": len(call_ids),
            },
        )
    return {
        "manifest": manifest,
        "glossary": glossary,
        "runs": runs,
        "out": tmp_path / "reproduce.json",
    }


def _no_network(monkeypatch) -> None:
    def guard(*_args, **_kwargs):
        raise AssertionError("reproduction must not use the network")

    monkeypatch.setenv("DEMO_MODE", "precomputed")
    monkeypatch.setattr(socket, "socket", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


def test_reproduces_a_pass_offline_with_recorded_hashes(tmp_path, monkeypatch):
    paths = _fixture(tmp_path, texts={})
    _no_network(monkeypatch)

    result = reproduce(
        paths["manifest"],
        paths["runs"],
        paths["out"],
        glossary_path=paths["glossary"],
    )

    assert result["verdict"] == "PASS"
    assert result["matches_summary"] is True
    assert result["recorded_verdict"] == "PASS"
    assert result["canon_version"] == CANON_VERSION
    assert result["n_calls"] == 2
    assert set(result["per_arm"]) == set(ARMS)
    assert {"real_recall", "insertions_per_utterance"} <= set(result["deltas"])
    assert result["deltas"]["real_recall"]["n"] == 2
    assert paths["out"].is_file()

    manifest_bytes = paths["manifest"].read_bytes()
    glossary_bytes = paths["glossary"].read_bytes()
    assert result["inputs"]["manifest"]["sha256"] == hashlib.sha256(
        manifest_bytes
    ).hexdigest()
    assert result["inputs"]["glossary"]["sha256"] == hashlib.sha256(
        glossary_bytes
    ).hexdigest()
    assert result["inputs"]["transcripts"]["c01/baseline"]["sha256"] == hashlib.sha256(
        (paths["runs"] / "c01" / "baseline.transcript.json").read_bytes()
    ).hexdigest()

    written = json.loads(paths["out"].read_text(encoding="utf-8"))
    assert written == result
    assert "\\u" not in paths["out"].read_text(encoding="utf-8")
    assert result["analysis"]["n_calls"] == 2


def test_single_call_is_inconclusive(tmp_path):
    paths = _fixture(tmp_path, call_ids=("c01",), summary_verdict="INCONCLUSIVE")

    result = reproduce(
        paths["manifest"],
        paths["runs"],
        paths["out"],
        glossary_path=paths["glossary"],
    )

    assert result["verdict"] == "INCONCLUSIVE"
    assert result["matches_summary"] is True
    assert result["analysis"]["n_calls"] == 1


def test_missing_transcript_raises_and_cli_exits_2(tmp_path, capsys):
    paths = _fixture(tmp_path, call_ids=("c01",))
    (paths["runs"] / "c01" / "mismatched-200.transcript.json").unlink()

    with pytest.raises(MissingTranscript, match="mismatched-200"):
        reproduce(
            paths["manifest"],
            paths["runs"],
            paths["out"],
            glossary_path=paths["glossary"],
        )
    assert not paths["out"].exists()

    code = main(
        [
            str(paths["manifest"]),
            "--runs-dir",
            str(paths["runs"]),
            "--glossary",
            str(paths["glossary"]),
            "--out",
            str(paths["out"]),
        ]
    )
    assert code == 2
    assert "mismatched-200" in capsys.readouterr().err


def test_tampering_changes_the_recomputed_verdict(tmp_path):
    paths = _fixture(
        tmp_path,
        texts={
            "c01/selected-200": "mera fail hua",
            "c02/selected-200": "mera fail hua",
        },
        summary_verdict="PASS",
    )

    result = reproduce(
        paths["manifest"],
        paths["runs"],
        paths["out"],
        glossary_path=paths["glossary"],
    )

    assert result["verdict"] == "FAIL"
    assert result["recorded_verdict"] == "PASS"
    assert result["matches_summary"] is False
    assert result["deltas"]["real_recall"]["mean"] < -0.05
    # The tampered transcript is visible through its content hash.
    assert result["inputs"]["transcripts"]["c01/selected-200"]["sha256"] != hashlib.sha256(
        (paths["runs"] / "c01" / "baseline.transcript.json").read_bytes()
    ).hexdigest()


def test_recorded_verdict_is_never_trusted(tmp_path):
    paths = _fixture(tmp_path, summary_verdict="FAIL")

    result = reproduce(
        paths["manifest"],
        paths["runs"],
        paths["out"],
        glossary_path=paths["glossary"],
    )

    assert result["verdict"] == "PASS"
    assert result["recorded_verdict"] == "FAIL"
    assert result["matches_summary"] is False


def test_positive_control_has_ci_but_no_p_value(tmp_path):
    arms = (*ARMS, "oracle-200")
    paths = _fixture(tmp_path, arms=arms)

    result = reproduce(
        paths["manifest"],
        paths["runs"],
        paths["out"],
        glossary_path=paths["glossary"],
    )

    control = result["analysis"]["positive_control"]
    assert control["status"] == "present"
    assert control["ci_low"] is not None
    assert control["ci_high"] is not None
    assert "p_value" not in control


def test_cli_prints_ascii_and_writes_the_artifact(tmp_path, capsys):
    paths = _fixture(tmp_path)

    code = main(
        [
            str(paths["manifest"]),
            "--runs-dir",
            str(paths["runs"]),
            "--glossary",
            str(paths["glossary"]),
            "--out",
            str(paths["out"]),
            "--seed",
            "0",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    captured.out.encode("ascii")
    assert "PASS" in captured.out
    assert paths["out"].exists()
