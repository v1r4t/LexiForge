"""Tests for the recording-pack generator."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_recording_pack import build_pack, render_call_sheet

ROOT = Path(__file__).resolve().parents[1]


def _summary(tmp_path: Path, calls=("c00", "c01")):
    return build_pack(
        list(calls),
        out_dir=tmp_path / "recording",
        glossary_path=ROOT / "data" / "glossary.json",
        scripts_dir=ROOT / "data" / "scripts",
    )


def test_builds_sheets_refs_and_manifest(tmp_path):
    summary = _summary(tmp_path)
    out = tmp_path / "recording"

    for call in ("c00", "c01"):
        assert (out / "scripts" / f"{call}.md").exists()
        assert (out / "refs" / f"{call}.txt").read_text(encoding="utf-8").strip()
    assert (out / "README.md").exists()
    assert (out / "consent.md").exists()
    assert (out / "qc-checklist.md").exists()
    assert (out / "sidecar.template.json").exists()

    manifest = json.loads((out / "manifest.template.json").read_text(encoding="utf-8"))
    assert manifest["study_id"] == "gnani-bfsi-recording-1"
    assert [call["call_id"] for call in manifest["calls"]] == ["c00", "c01"]
    assert manifest["calls"][0]["utterances"] == 5
    assert manifest["calls"][0]["reference"].endswith("refs/c00.txt")
    assert summary["calls"] == ["c00", "c01"]


def test_sheet_resolves_known_terms_and_flags_missing_ones(tmp_path):
    _summary(tmp_path)
    out = tmp_path / "recording"
    glossary = {
        entry["term_id"]: entry
        for entry in json.loads(
            (ROOT / "data" / "glossary.json").read_text(encoding="utf-8")
        )
    }

    c01_script = json.loads(
        (ROOT / "data" / "scripts" / "c01.json").read_text(encoding="utf-8")
    )
    c01_term = glossary[c01_script["expected_fictional"][0]]["canonical"]
    c01 = (out / "scripts" / "c01.md").read_text(encoding="utf-8")
    assert "Call c01" in c01
    assert c01_term in c01
    assert "MISSING" not in c01

    c00 = (out / "scripts" / "c00.md").read_text(encoding="utf-8")
    assert "MISSING" not in c00


def test_reference_text_is_the_dialogue(tmp_path):
    _summary(tmp_path)
    script = json.loads(
        (ROOT / "data" / "scripts" / "c00.json").read_text(encoding="utf-8")
    )
    ref = (tmp_path / "recording" / "refs" / "c00.txt").read_text(encoding="utf-8")
    assert script["turns"][0]["text"] in ref
    assert script["turns"][-1]["text"] in ref


def test_render_call_sheet_is_deterministic(tmp_path):
    script = json.loads((ROOT / "data" / "scripts" / "c01.json").read_text(encoding="utf-8"))
    glossary = {
        "F0013": {"canonical": "RuvNivesh", "origin": "fictional", "category": "loans_credit"}
    }
    first = render_call_sheet("c01", script, glossary)
    second = render_call_sheet("c01", script, glossary)
    assert first == second
    assert "| 2 | CUS |" in first
