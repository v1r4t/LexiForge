"""Tests for the glossary alias / transliteration audit (design §4.1, §5)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lexiforge.canon import CANON_VERSION, canon
from lexiforge.score.alias_audit import ALLOWED_ALIAS_SOURCES, audit_glossary
from scripts import audit_aliases

REPO = Path(__file__).resolve().parents[1]


def _script(path: Path, call_id: str, terms: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "call_id": call_id,
        "turns": [{"idx": 1, "text": "test", "glossary_terms": terms}],
        "expected_real": [],
        "expected_fictional": [],
        "oov": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_collision_is_reported_pairwise() -> None:
    glossary = [
        {"term_id": "R1", "canonical": "UPI"},
        {"term_id": "R2", "canonical": "upi"},
    ]

    result = audit_glossary(glossary)

    assert result["collisions"] == [
        {
            "canon_key": "upi",
            "terms": [
                {"term_id": "R1", "surface": "UPI", "field": "canonical"},
                {"term_id": "R2", "surface": "upi", "field": "canonical"},
            ],
        }
    ]
    assert result["summary"]["n_collisions"] == 1
    assert result["summary"]["ok"] is False


def test_alias_across_fields_collides() -> None:
    glossary = [
        {"term_id": "R1", "canonical": "NEFT", "scoring_aliases": ["neft transfer"]},
        {"term_id": "R2", "canonical": "neft-transfer"},
    ]

    result = audit_glossary(glossary)

    assert [c["canon_key"] for c in result["collisions"]] == ["neft transfer"]
    fields = sorted(t["field"] for t in result["collisions"][0]["terms"])
    assert fields == ["canonical", "scoring_alias"]


def test_glossary_is_not_mutated() -> None:
    glossary = [
        {
            "term_id": "F1",
            "canonical": "NirSathi",
            "scoring_aliases": ["Nir Sathi"],
            "script_variants": {"deva": "नइरसअतहइ", "latn": "NirSathi"},
            "spoken_forms": [],
        }
    ]
    before = copy.deepcopy(glossary)

    audit_glossary(glossary)

    assert glossary == before


def test_deterministic_order() -> None:
    first = [
        {"term_id": "B2", "canonical": "zee"},
        {"term_id": "A1", "canonical": "ZEE"},
        {"term_id": "D4", "canonical": "abc"},
        {"term_id": "C3", "canonical": "ABC"},
    ]
    second = list(reversed(first))

    dump_a = json.dumps(audit_glossary(first), ensure_ascii=False, sort_keys=True)
    dump_b = json.dumps(audit_glossary(second), ensure_ascii=False, sort_keys=True)

    assert dump_a == dump_b
    keys = [c["canon_key"] for c in audit_glossary(first)["collisions"]]
    assert keys == ["abc", "zee"]


def test_asr_derived_surface_raises() -> None:
    glossary = [
        {
            "term_id": "R1",
            "canonical": "NEFT",
            "script_variants": {
                "deva": {"surface": "नेफ्ट", "source": "asr output"},
            },
        }
    ]

    with pytest.raises(ValueError, match="asr output"):
        audit_glossary(glossary)


def test_structured_allowed_source_is_accepted() -> None:
    glossary = [
        {
            "term_id": "R1",
            "canonical": "NEFT",
            "aliases": [{"surface": "NEFT transfer", "source": "pre-freeze attested"}],
        }
    ]

    result = audit_glossary(glossary)

    assert result["collisions"] == []
    assert result["summary"]["ok"] is True


def test_empty_glossary() -> None:
    result = audit_glossary([])

    assert result["collisions"] == []
    assert result["missing_spoken_forms"] == []
    assert result["cross_script_dupes"] == []
    assert result["proposed_aliases"] == []
    assert result["summary"] == {
        "n_terms": 0,
        "n_collisions": 0,
        "n_missing_spoken_forms": 0,
        "n_cross_script_dupes": 0,
        "n_proposed_aliases": 0,
        "ok": True,
        "canon_version": CANON_VERSION,
    }


def test_missing_spoken_forms_is_usage_driven(tmp_path: Path) -> None:
    glossary = [
        {"term_id": "A", "canonical": "Alpha", "spoken_forms": []},
        {"term_id": "B", "canonical": "Beta", "spoken_forms": ["beeta"]},
        {"term_id": "C", "canonical": "Gamma", "spoken_forms": []},
    ]
    scripts = tmp_path / "scripts"
    _script(scripts / "c00.json", "c00", ["A", "B"])
    _script(scripts / "c01.json", "c01", ["A"])

    result = audit_glossary(glossary, scripts_dir=scripts)

    assert result["missing_spoken_forms"] == [
        {"term_id": "A", "canonical": "Alpha", "calls": ["c00", "c01"]}
    ]
    assert result["summary"]["n_missing_spoken_forms"] == 1


def test_cross_script_dupe_detected() -> None:
    glossary = [
        {"term_id": "R1", "canonical": "nirsathi"},
        {"term_id": "F1", "canonical": "नइरसअतहइ"},
    ]

    result = audit_glossary(glossary)

    assert result["collisions"] == []
    assert result["cross_script_dupes"] == [
        {
            "translit_key": "nirsathi",
            "terms": [
                {"term_id": "F1", "surface": "नइरसअतहइ", "script": "deva"},
                {"term_id": "R1", "surface": "nirsathi", "script": "latn"},
            ],
        }
    ]
    assert result["summary"]["ok"] is False


def test_proposals_use_allowed_sources(tmp_path: Path) -> None:
    glossary = [
        {
            "term_id": "F1",
            "canonical": "NirSathi",
            "scoring_aliases": ["Nir Sathi"],
            "script_variants": {"deva": "नइरसअतहइ", "latn": "NirSathi"},
            "spoken_forms": [],
        }
    ]
    scripts = tmp_path / "scripts"
    _script(scripts / "c00.json", "c00", ["F1"])

    result = audit_glossary(glossary, scripts_dir=scripts)

    proposals = result["proposed_aliases"]
    assert [(p["term_id"], p["surface"], p["canon_key"]) for p in proposals] == [
        ("F1", "नइरसअतहइ", "नइरसअतहइ")
    ]
    assert all(p["source"] in ALLOWED_ALIAS_SOURCES for p in proposals)


def test_cli_writes_json_and_exit_codes(tmp_path: Path, capsys) -> None:
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps([{"term_id": "R1", "canonical": "UPI"}]), encoding="utf-8")
    out = tmp_path / "runs" / "alias-audit.json"

    code = audit_aliases.main(["--glossary", str(clean), "--out", str(out)])

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["ok"] is True
    assert "OK" in capsys.readouterr().out

    broken = tmp_path / "broken.json"
    broken.write_text(
        json.dumps(
            [
                {"term_id": "R1", "canonical": "UPI"},
                {"term_id": "R2", "canonical": "upi"},
            ]
        ),
        encoding="utf-8",
    )
    out2 = tmp_path / "runs" / "broken.json"

    code = audit_aliases.main(["--glossary", str(broken), "--out", str(out2)])

    assert code == 1
    stdout = capsys.readouterr().out
    stdout.encode("ascii")  # CLI stdout must stay CP1252-safe
    assert "collision" in stdout.lower()


def test_committed_glossary_is_clean() -> None:
    from lexiforge.score.match import load_glossary

    result = audit_glossary(
        load_glossary(REPO / "data" / "glossary.json"),
        scripts_dir=REPO / "data" / "scripts",
    )

    assert result["collisions"] == []
    assert result["cross_script_dupes"] == []
    assert result["summary"]["ok"] is True
    assert canon("NEFT") == "neft"
