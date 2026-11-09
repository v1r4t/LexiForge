"""Tests for the consistent pilot-script generator."""

from __future__ import annotations

import json
from pathlib import Path

from lexiforge.canon import canon
from scripts.build_pilot_scripts import build_scripts

ROOT = Path(__file__).resolve().parents[1]


def _glossary() -> dict[str, dict]:
    entries = json.loads((ROOT / "data" / "glossary.json").read_text(encoding="utf-8"))
    return {entry["term_id"]: entry for entry in entries}


def test_expected_ids_exist_and_surface():
    glossary = _glossary()
    scripts = build_scripts(("c00", "c01", "c02", "c03"))
    for call_id, script in scripts.items():
        assert len(script["turns"]) == 5
        assert [t["speaker"] for t in script["turns"]] == ["AGT", "CUS", "AGT", "CUS", "AGT"]
        assert script["turns"][0]["glossary_terms"] == []
        assert all(len(t["glossary_terms"]) <= 2 for t in script["turns"])

        for term_id in script["expected_real"] + script["expected_fictional"]:
            assert term_id in glossary, (call_id, term_id)
        text = canon(" ".join(t["text"] for t in script["turns"]))
        for term_id in script["expected_real"] + script["expected_fictional"]:
            assert canon(glossary[term_id]["canonical"]) in text, (call_id, term_id)


def test_assignment_counts_are_respected():
    scripts = build_scripts(("c00", "c01", "c02", "c03"))
    for script in scripts.values():
        assert 4 <= len(script["expected_real"]) <= 5
        assert 3 <= len(script["expected_fictional"]) <= 4
