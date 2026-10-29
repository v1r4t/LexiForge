"""Tests for glossary validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lexiforge.glossary import validate, validate_or_raise


def test_clean_tiny_glossary_passes():
    entries = [
        {
            "term_id": "NEFT",
            "canonical": "NEFT",
            "aliases": ["NEFT"],
            "alias_provenance": {"NEFT": "S1"},
        },
        {
            "term_id": "UPI",
            "canonical": "UPI",
            "aliases": ["UPI"],
            "alias_provenance": {"UPI": "S2"},
        },
    ]
    real_lexicon = [
        {"term": "NEFT"},
        {"term": "UPI"},
    ]
    violations = validate(entries, real_lexicon, brand_blocklist=[])
    assert violations == []


def test_v1_unique_term_id_and_unique_canonical():
    entries = [
        {"term_id": "T1", "canonical": "NEFT", "aliases": ["NEFT"], "alias_provenance": {"NEFT": "S1"}},
        {"term_id": "T1", "canonical": "UPI", "aliases": ["UPI"], "alias_provenance": {"UPI": "S1"}},  # duplicate term_id
    ]
    violations = validate(entries, [], brand_blocklist=[])
    assert "V1" in violations
    
    entries2 = [
        {"term_id": "T1", "canonical": "NEFT", "aliases": ["NEFT"], "alias_provenance": {"NEFT": "S1"}},
        {"term_id": "T2", "canonical": "NEFT", "aliases": ["N E F T"], "alias_provenance": {"N E F T": "S1"}},  # same canonical
    ]
    violations2 = validate(entries2, [], brand_blocklist=[])
    assert "V1" in violations2


def test_v2_no_alias_collision_across_entries():
    entries = [
        {"term_id": "T1", "canonical": "NEFT", "aliases": ["NEFT", "fastpay"], "alias_provenance": {"NEFT": "S1", "fastpay": "S1"}},
        {"term_id": "T2", "canonical": "IMPS", "aliases": ["fastpay"], "alias_provenance": {"fastpay": "S2"}},  # alias collision
    ]
    violations = validate(entries, [], brand_blocklist=[])
    assert "V2" in violations


def test_v3_fictional_names_not_equal_or_within_levenshtein_1_of_brand_blocklist():
    entries = [
        {
            "term_id": "F1",
            "canonical": "Paytm",
            "aliases": ["Paytm"],
            "fictional": True,
            "nonce_root": "pay",
            "alias_provenance": {"Paytm": "S1"},
        },
    ]
    violations = validate(entries, [{"term": "NEFT"}], brand_blocklist=["Paytm"])
    assert "V3" in violations
    
    # within levenshtein 1
    entries2 = [
        {
            "term_id": "F2",
            "canonical": "Paytmm",  # Levenshtein 1 from Paytm
            "aliases": ["Paytmm"],
            "fictional": True,
            "nonce_root": "pay",
            "alias_provenance": {"Paytmm": "S1"},
        },
    ]
    violations2 = validate(entries2, [{"term": "NEFT"}], brand_blocklist=["Paytm"])
    assert "V3" in violations2


def test_v4_required_fields_present_enums_valid():
    entries = [
        {"term_id": "", "canonical": "NEFT"},  # missing/empty required
    ]
    violations = validate(entries, [], brand_blocklist=[])
    assert "V4" in violations


def test_v5_fictional_entries_carry_nonce_root_and_ge3_edits_from_every_real_lexicon_entry():
    # Missing nonce root
    entries = [
        {
            "term_id": "F1",
            "canonical": "ArthSathiXyz",
            "aliases": ["ArthSathiXyz"],
            "fictional": True,
            "alias_provenance": {"ArthSathiXyz": "S1"},
        },
    ]
    violations = validate(entries, [{"term": "NEFT"}], brand_blocklist=[])
    assert "V5" in violations
    
    # Too close to real lexicon entry
    entries2 = [
        {
            "term_id": "F2",
            "canonical": "NEFTA",  # Levenshtein 1 from NEFT
            "aliases": ["NEFTA"],
            "fictional": True,
            "nonce_root": "neft",
            "alias_provenance": {"NEFTA": "S1"},
        },
    ]
    violations2 = validate(entries2, [{"term": "NEFT"}], brand_blocklist=[])
    assert "V5" in violations2


def test_v6_generated_terms_pairwise_ge3_edits_apart():
    entries = [
        {
            "term_id": "G1",
            "canonical": "AbcDefGhi",
            "aliases": ["AbcDefGhi"],
            "generated": True,
            "alias_provenance": {"AbcDefGhi": "S1"},
        },
        {
            "term_id": "G2",
            "canonical": "AbcDefGhj",  # Levenshtein 1 from G1
            "aliases": ["AbcDefGhj"],
            "generated": True,
            "alias_provenance": {"AbcDefGhj": "S2"},
        },
    ]
    violations = validate(entries, [], brand_blocklist=[])
    assert "V6" in violations


def test_v7_no_angle_brackets_pipe_in_canonical():
    entries = [
        {"term_id": "T1", "canonical": "bad<|term", "aliases": ["bad<|term"], "alias_provenance": {"bad<|term": "S1"}},
    ]
    violations = validate(entries, [], brand_blocklist=[])
    assert "V7" in violations
    
    entries2 = [
        {"term_id": "T2", "canonical": "bad|>term", "aliases": ["bad|>term"], "alias_provenance": {"bad|>term": "S1"}},
    ]
    violations2 = validate(entries2, [], brand_blocklist=[])
    assert "V7" in violations2


def test_v8_alias_provenance_present_source_in_s1_s2_s3():
    entries = [
        {"term_id": "T1", "canonical": "NEFT", "aliases": ["NEFT"]},  # no provenance
    ]
    violations = validate(entries, [], brand_blocklist=[])
    assert "V8" in violations
    
    entries2 = [
        {"term_id": "T2", "canonical": "UPI", "aliases": ["UPI"], "alias_provenance": {"UPI": "S4"}},  # bad source
    ]
    violations2 = validate(entries2, [], brand_blocklist=[])
    assert "V8" in violations2


def test_validate_or_raise():
    entries = [
        {"term_id": "T1", "canonical": "NEFT", "aliases": ["NEFT"]},  # will trigger V8
    ]
    with pytest.raises(Exception):
        validate_or_raise(entries, [], [])


def test_cli_exit_code(tmp_path):
    bad = {
        "entries": [
            {"term_id": "T1", "canonical": "NEFT", "aliases": ["NEFT"]}  # V8
        ],
        "real_lexicon": [],
        "brand_blocklist": []
    }
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps(bad), encoding="utf-8")
    
    # Run as module
    result = subprocess.run(
        [sys.executable, "-m", "lexiforge.glossary.validate", str(bad_file)],
        cwd=str(Path(__file__).parent.parent),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    # Should print violations
    assert "V8" in result.stdout or "V8" in result.stderr
