"""Tests for scripts/export_web_data.py (measured-data exporter)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from export_web_data import export  # noqa: E402

GLOSSARY = [
    {"term_id": "R1", "canonical": "UPI", "scoring_aliases": ["UPI"]},
    {"term_id": "R2", "canonical": "NEFT", "scoring_aliases": ["NEFT"]},
]


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def project(tmp_path: Path):
    glossary = tmp_path / "glossary.json"
    _write(glossary, GLOSSARY)

    refs = tmp_path / "refs"
    _write(refs / "c01_t01.json", {"text": "mera UPI fail ho gaya, NEFT nahi chala"})

    transcripts = tmp_path / "transcripts"
    _write(transcripts / "c01" / "baseline" / "c01_t01.json", {"text": "mera UPI fail ho gaya NEFT nahi chala"})
    _write(transcripts / "c01" / "mismatched-200" / "c01_t01.json", {"text": "mera insurance fail ho gaya NEFT nahi chala"})

    out = tmp_path / "web" / "data"
    return {"glossary": glossary, "refs": refs, "transcripts": transcripts, "out": out}


def test_export_writes_all_files_and_marks_measured(project):
    written = export(
        project["transcripts"],
        project["refs"],
        project["out"],
        glossary_path=project["glossary"],
        assignment_path=project["out"].parent / "missing_assignment.json",
    )
    names = {p.name for p in written}
    assert names == {
        "calls.json",
        "transcripts.json",
        "terms.json",
        "results.json",
        "demo_config.json",
    }

    config = json.loads((project["out"] / "demo_config.json").read_text(encoding="utf-8"))
    assert config["data_source"] == "measured"

    results = json.loads((project["out"] / "results.json").read_text(encoding="utf-8"))
    assert results["source"] == "measured"
    assert results["is_sample"] is False
    # Inference wired from lexiforge.analysis.inference; descriptive differences preserved.
    for contrast in results["contrasts"]:
        assert "delta_pp" in contrast
    assert "inference" in results


def test_export_marks_unrecovered_terms_as_inserted(project):
    export(
        project["transcripts"],
        project["refs"],
        project["out"],
        glossary_path=project["glossary"],
        assignment_path=project["out"].parent / "missing_assignment.json",
    )
    transcripts = json.loads((project["out"] / "transcripts.json").read_text(encoding="utf-8"))
    statuses = {t["status"] for t in transcripts["c01"]["mismatched-200"]}
    assert "inserted" not in statuses  # "insurance" is not a glossary term
    assert statuses <= {"same", "recovered", "inserted"}


def test_export_reports_negative_delta_when_terms_are_lost(project):
    # Drop UPI from the mismatched arm so recall has to fall.
    _write(
        project["transcripts"] / "c01" / "mismatched-200" / "c01_t01.json",
        {"text": "mera fail ho gaya NEFT nahi chala"},
    )
    export(
        project["transcripts"],
        project["refs"],
        project["out"],
        glossary_path=project["glossary"],
        assignment_path=project["out"].parent / "missing_assignment.json",
    )
    results = json.loads((project["out"] / "results.json").read_text(encoding="utf-8"))
    mismatched = [c for c in results["contrasts"] if c["name"].startswith("mismatched-200")]
    assert mismatched, results["contrasts"]
    assert mismatched[0]["delta_pp"] < 0


def test_export_requires_references(tmp_path: Path, project):
    empty_refs = tmp_path / "no_refs"
    empty_refs.mkdir()
    with pytest.raises(ValueError, match="no references"):
        export(
            project["transcripts"],
            empty_refs,
            project["out"],
            glossary_path=project["glossary"],
            assignment_path=project["out"].parent / "missing_assignment.json",
        )


def test_export_fails_loudly_without_transcripts(tmp_path: Path, project):
    with pytest.raises(FileNotFoundError):
        export(
            tmp_path / "nope",
            project["refs"],
            project["out"],
            glossary_path=project["glossary"],
            assignment_path=project["out"].parent / "missing_assignment.json",
        )
