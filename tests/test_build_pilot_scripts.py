"""Tests for the consistent pilot-script generator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lexiforge.canon import canon
from scripts.build_pilot_scripts import build_scripts, main

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "data" / "scripts"
ASSIGNMENT_PATH = ROOT / "data" / "assignment.json"
GLOSSARY_PATH = ROOT / "data" / "glossary.json"

ALL_CALLS = tuple(f"c{index:02d}" for index in range(20))

# c00-c03 are frozen: their committed bytes must never change.
FROZEN_C00_C03 = {
    "c00": "1d6be86568dc41252c4d21837df096246718b9dedd3fb60b906e1d1494e012ff",
    "c01": "e258ac981930234e31500001d7d4fdfce1dd3fc80b9000b599df30b415231e22",
    "c02": "55f4c06eaf75823fc3c99e89de7215f136a0e20850a06a109b1e92f6f9152d93",
    "c03": "68da43b594adb9e64eda8a6899afdf9ef6c368c5d1240d2ffce460f6a365baed",
}


def _glossary() -> dict[str, dict]:
    entries = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    return {entry["term_id"]: entry for entry in entries}


def _assignment() -> dict[str, dict]:
    return json.loads(ASSIGNMENT_PATH.read_text(encoding="utf-8-sig"))


def _normalised(path: Path) -> bytes:
    """Compare content bytes independent of git's checkout line endings."""
    return path.read_bytes().replace(b"\r\n", b"\n")


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


def test_all_twenty_calls_are_generated_by_default():
    scripts = build_scripts()
    assert tuple(scripts) == ALL_CALLS


def test_every_term_id_resolves():
    glossary = _glossary()
    for call_id, script in build_scripts().items():
        ids = set(script["expected_real"] + script["expected_fictional"])
        ids |= {tid for turn in script["turns"] for tid in turn["glossary_terms"]}
        assert ids <= glossary.keys(), (call_id, sorted(ids - glossary.keys()))


def test_every_script_has_the_expected_shape():
    glossary = _glossary()
    for call_id, script in build_scripts().items():
        assert len(script["turns"]) == 5, call_id
        assert [t["speaker"] for t in script["turns"]] == [
            "AGT",
            "CUS",
            "AGT",
            "CUS",
            "AGT",
        ], call_id
        assert script["turns"][0]["glossary_terms"] == [], call_id
        assert all(len(t["glossary_terms"]) <= 2 for t in script["turns"]), call_id
        assert 4 <= len(script["expected_real"]) <= 5, call_id
        assert 3 <= len(script["expected_fictional"]) <= 4, call_id

        text = canon(" ".join(t["text"] for t in script["turns"]))
        for term_id in script["expected_real"] + script["expected_fictional"]:
            assert canon(glossary[term_id]["canonical"]) in text, (call_id, term_id)


def test_call_id_maps_to_its_assignment_key():
    assignment = _assignment()
    for call_id in ("c04", "c07", "c19"):
        script = build_scripts((call_id,))[call_id]
        entry = assignment[str(int(call_id[1:]))]
        assert script["call_type"] == entry["call_type"]
        assert script["expected_real"] == entry["real"]
        assert set(script["expected_fictional"]) <= set(entry["fictional"])


def test_mismatched_domain_is_a_real_category():
    real_categories = {entry["call_type"] for entry in _assignment().values()}
    for call_id, script in build_scripts().items():
        mismatched = script["mismatched_domain"]
        assert isinstance(mismatched, str), call_id
        assert mismatched in real_categories, (call_id, mismatched)
        assert mismatched != script["call_type"], call_id


def test_oov_is_copied_from_assignment():
    assignment = _assignment()
    for call_id, script in build_scripts().items():
        expected = assignment[str(int(call_id[1:]))]["oov"]
        assert script["oov"] == expected, call_id


def test_regeneration_is_byte_identical(tmp_path):
    assert (
        main(
            [
                "--calls",
                ",".join(ALL_CALLS),
                "--assignment",
                str(ASSIGNMENT_PATH),
                "--glossary",
                str(GLOSSARY_PATH),
                "--out-dir",
                str(tmp_path),
                "--write",
            ]
        )
        == 0
    )
    for call_id in ALL_CALLS:
        assert _normalised(tmp_path / f"{call_id}.json") == _normalised(
            SCRIPTS_DIR / f"{call_id}.json"
        ), call_id


def test_write_is_idempotent(tmp_path):
    argv = [
        "--calls",
        ",".join(ALL_CALLS),
        "--assignment",
        str(ASSIGNMENT_PATH),
        "--glossary",
        str(GLOSSARY_PATH),
        "--out-dir",
        str(tmp_path),
        "--write",
    ]
    main(argv)
    first = {p.name: _normalised(p) for p in tmp_path.glob("*.json")}
    main(argv)
    second = {p.name: _normalised(p) for p in tmp_path.glob("*.json")}
    assert first == second


def test_frozen_c00_c03_bytes_do_not_change():
    for call_id, digest in FROZEN_C00_C03.items():
        actual = hashlib.sha256(_normalised(SCRIPTS_DIR / f"{call_id}.json")).hexdigest()
        assert actual == digest, call_id
