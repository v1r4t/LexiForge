"""Tests for per-arm transcript persistence (design §5, "Stamped provenance")."""

from __future__ import annotations

import json

import pytest

from lexiforge.canon import CANON_VERSION
from lexiforge.score.store import (
    iter_arm_transcripts,
    read_arm_transcript,
    write_arm_transcript,
)

CALL = "c00"
ROWS = {
    "f1": {"text": "mera UPI fail hua", "detected_language_code": "hi-IN"},
}
CONFIG = {
    "model": "prisma-v3.0",
    "format": "transcribe",
    "language_code": "hi-IN,en-IN",
    "keyterms": ["UPI"],
}


def _write(run_dir, arm="baseline", **overrides):
    kwargs = {
        "text": "mera UPI fail hua",
        "rows": ROWS,
        "config": CONFIG,
        "status": "COMPLETED",
        "job_id": "job-1",
        "detected_language_code": "hi-IN",
    }
    kwargs.update(overrides)
    return write_arm_transcript(run_dir, CALL, arm, **kwargs)


def test_write_creates_arm_named_file_and_round_trips(tmp_path):
    path = _write(tmp_path)

    assert path == tmp_path / "baseline.transcript.json"
    assert path.is_file()
    data = read_arm_transcript(path)
    assert data == {
        "call_id": CALL,
        "arm": "baseline",
        "text": "mera UPI fail hua",
        "rows": ROWS,
        "config": CONFIG,
        "status": "COMPLETED",
        "job_id": "job-1",
        "detected_language_code": "hi-IN",
        "canon_version": CANON_VERSION,
    }
    # The reference script is never persisted: re-scoring reads it from the
    # manifest so an arm cannot leak the answer into its own transcript.
    assert "reference" not in data
    assert "reference_text" not in data


def test_round_trip_is_exact_for_unicode(tmp_path):
    text = "मेरा यूपीआई फेल हुआ — NEFT नहीं चला"
    rows = {"f1": {"text": text, "segments": [{"text": "मेरा यूपीआई"}]}}
    path = _write(tmp_path, text=text, rows=rows)

    raw = path.read_bytes()
    assert "मेरा".encode("utf-8") in raw
    assert b"\\u" not in raw  # ensure_ascii=False
    assert read_arm_transcript(path)["text"] == text
    assert read_arm_transcript(path)["rows"] == rows


def test_reference_keyword_is_rejected(tmp_path):
    with pytest.raises(TypeError):
        write_arm_transcript(
            tmp_path,
            CALL,
            "baseline",
            text="x",
            rows={},
            config={},
            status="COMPLETED",
            reference="the answer",
        )

    assert list(tmp_path.iterdir()) == []


def test_dump_failure_leaves_no_partial_file(tmp_path):
    with pytest.raises(TypeError):
        _write(tmp_path, config={"unserialisable": object()})

    assert list(tmp_path.iterdir()) == []


def test_write_leaves_no_temp_file(tmp_path):
    _write(tmp_path)

    assert [entry.name for entry in tmp_path.iterdir()] == ["baseline.transcript.json"]


def test_atomic_replace_is_used(tmp_path, monkeypatch):
    from lexiforge.score import store

    replaced = []
    real_replace = store.os.replace

    def recording_replace(src, dst):
        replaced.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", recording_replace)
    path = _write(tmp_path)

    assert len(replaced) == 1
    src, dst = replaced[0]
    assert str(dst) == str(path)
    assert str(src).endswith(".tmp")


def test_iter_arm_transcripts_is_sorted_and_complete(tmp_path):
    _write(tmp_path, arm="selected-200")
    _write(tmp_path, arm="baseline", job_id=None, detected_language_code=None)

    transcripts = list(iter_arm_transcripts(tmp_path))

    assert [row["arm"] for row in transcripts] == ["baseline", "selected-200"]
    assert transcripts[0]["job_id"] is None
    assert transcripts[0]["detected_language_code"] is None


def test_iter_arm_transcripts_ignores_other_json_and_missing_dir(tmp_path):
    _write(tmp_path)
    (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.json").write_text("[]", encoding="utf-8")

    assert len(list(iter_arm_transcripts(tmp_path))) == 1
    assert list(iter_arm_transcripts(tmp_path / "absent")) == []


def test_read_rejects_non_object_json(tmp_path):
    path = tmp_path / "baseline.transcript.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        read_arm_transcript(path)


def test_write_creates_missing_run_dir(tmp_path):
    path = _write(tmp_path / "runs" / CALL)

    assert path.is_file()
    assert path.parent == tmp_path / "runs" / CALL
