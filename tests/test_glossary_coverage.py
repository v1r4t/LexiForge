"""Tests for scripts.glossary_coverage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import glossary_coverage


def test_fixture_yields_exact_counts(tmp_path: Path) -> None:
    glossary_path = tmp_path / "glossary.json"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    # Create a small glossary with 4 terms
    glossary = [
        {"term_id": "F0001", "canonical": "A"},
        {"term_id": "F0002", "canonical": "B"},
        {"term_id": "F0003", "canonical": "C"},
        {"term_id": "R0001", "canonical": "D"},
    ]
    glossary_path.write_text(json.dumps(glossary), encoding="utf-8")

    # Script 1 uses F0001, F0002 via turns and expected
    s1 = {
        "call_id": "s1",
        "turns": [
            {"idx": 1, "glossary_terms": ["F0001"]},
            {"idx": 2, "glossary_terms": ["F0002", "F0001"]},  # duplicates
        ],
        "expected_real": ["R0001"],
        "expected_fictional": ["F0002"],
        "oov": ["OOV1"],  # must not be counted as glossary terms
    }
    (scripts_dir / "s1.json").write_text(json.dumps(s1), encoding="utf-8")

    # Script 2 uses F0003
    s2 = {
        "call_id": "s2",
        "turns": [{"idx": 1, "glossary_terms": ["F0003"]}],
        "expected_real": [],
        "expected_fictional": [],
        "oov": [],
    }
    (scripts_dir / "s2.json").write_text(json.dumps(s2), encoding="utf-8")

    result = glossary_coverage.audit_coverage(str(glossary_path), str(scripts_dir))

    assert result["total_terms"] == 4
    assert result["used_terms"] == 4  # F0001, F0002, R0001, F0003 all used
    assert result["unused_terms"] == 0
    assert result["fraction"] == 1.0
    assert "per_script" in result
    # per_script should have entries for scripts
    assert set(result["per_script"].keys()) >= {"s1.json", "s2.json"}


def test_real_audit_reports_actual_committed_total() -> None:
    result = glossary_coverage.audit_coverage()

    # Committed glossary has 1000 terms
    assert result["total_terms"] == 1000
    assert 0 < result["fraction"] < 1
    assert result["used_terms"] >= 0
    assert result["unused_terms"] == result["total_terms"] - result["used_terms"]


def test_repeated_runs_identical(tmp_path: Path) -> None:
    glossary_path = tmp_path / "glossary.json"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    glossary = [
        {"term_id": "F0001"},
        {"term_id": "F0002"},
    ]
    glossary_path.write_text(json.dumps(glossary), encoding="utf-8")

    s1 = {"turns": [{"glossary_terms": ["F0001"]}], "expected_real": [], "expected_fictional": [], "oov": []}
    (scripts_dir / "s1.json").write_text(json.dumps(s1), encoding="utf-8")

    r1 = glossary_coverage.audit_coverage(str(glossary_path), str(scripts_dir))
    r2 = glossary_coverage.audit_coverage(str(glossary_path), str(scripts_dir))
    assert r1 == r2


def test_missing_script_or_malformed_entry_raises_clearly(tmp_path: Path) -> None:
    glossary_path = tmp_path / "glossary.json"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    glossary = [{"term_id": "F0001"}]
    glossary_path.write_text(json.dumps(glossary), encoding="utf-8")

    # Malformed JSON
    (scripts_dir / "bad.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        glossary_coverage.audit_coverage(str(glossary_path), str(scripts_dir))
    assert str(exc_info.value)  # should have a clear message
