"""Tests for the ``static-head-200`` context arm (design §2, §4 step 1).

The static head arm is one fixed glossary list, identical for every call and
every hypothesis, used as the practice/secondary comparator against
``baseline``. It is drawn from the frozen core-200 ids and padded from the
glossary in a deterministic sorted order — never from ASR output, references
or scripts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lexiforge.contexts.static_arm import (
    ARM_NAME,
    static_head_from_file,
    static_head_terms,
)

ROOT = Path(__file__).resolve().parents[1]


def _entry(tid: str, surface: str, category: str = "payments") -> dict:
    return {
        "term_id": tid,
        "canonical": surface,
        "category": category,
        "freq_band": "head",
        "origin": "real",
        "scoring_aliases": [],
        "script_variants": {},
        "spoken_forms": [],
    }


GLOSSARY = [
    _entry("T000", "Alpha"),
    _entry("T001", "Bravo"),
    _entry("T002", "Cobra"),
    _entry("T003", "Delta"),
    _entry("T004", "Eagle"),
    _entry("T005", "Foxtrot"),
    _entry("T006", "Golf"),
    _entry("T007", "Hotel"),
    _entry("T008", "India"),
    _entry("T009", "Juliet"),
]


def test_arm_label_is_static_head_200() -> None:
    assert ARM_NAME == "static-head-200"


def test_exact_budget_with_default_real_data() -> None:
    payload = json.loads((ROOT / "data" / "core200.json").read_text("utf-8"))
    out = static_head_terms(payload, json.loads(
        (ROOT / "data" / "glossary.json").read_text("utf-8")
    ))
    assert len(out) == 200
    assert len({term.casefold() for term in out}) == 200


def test_exact_budget_small_fixture() -> None:
    out = static_head_terms({"term_ids": ["T003", "T000"]}, GLOSSARY, budget=5)
    assert len(out) == 5
    assert out[:2] == ["Delta", "Alpha"]


def test_identical_for_every_call_and_glossary_order() -> None:
    payload = {"term_ids": ["T003", "T000"]}
    first = static_head_terms(payload, GLOSSARY, budget=6)
    second = static_head_terms(payload, list(reversed(GLOSSARY)), budget=6)
    third = static_head_terms(payload, GLOSSARY, budget=6)
    assert first == second == third


def test_padding_order_is_sorted_and_after_core_ids() -> None:
    out = static_head_terms({"term_ids": ["T003", "T000"]}, GLOSSARY, budget=5)
    assert out[:2] == ["Delta", "Alpha"]
    assert out[2:] == ["Bravo", "Cobra", "Eagle"]


def test_unknown_core200_id_raises() -> None:
    with pytest.raises(ValueError, match="F9999"):
        static_head_terms({"term_ids": ["T000", "F9999"]}, GLOSSARY, budget=2)


def test_core200_payload_accepts_bare_list() -> None:
    assert static_head_terms(["T001"], GLOSSARY, budget=2) == ["Bravo", "Alpha"]


def test_underfilled_glossary_raises() -> None:
    with pytest.raises(ValueError):
        static_head_terms({"term_ids": ["T000"]}, GLOSSARY, budget=99)


def test_from_file_matches_in_memory(tmp_path: Path) -> None:
    core_path = tmp_path / "core200.json"
    glossary_path = tmp_path / "glossary.json"
    core_path.write_text(
        json.dumps({"term_ids": ["T003", "T000"], "seed": 0}), encoding="utf-8"
    )
    glossary_path.write_text(
        json.dumps(GLOSSARY, ensure_ascii=False), encoding="utf-8"
    )
    direct = static_head_terms({"term_ids": ["T003", "T000"]}, GLOSSARY, budget=4)
    loaded = static_head_from_file(
        core200_path=str(core_path),
        glossary_path=str(glossary_path),
        budget=4,
    )
    assert loaded == direct


def test_deterministic_across_processes() -> None:
    script = (
        "import json\n"
        "from lexiforge.contexts.static_arm import static_head_terms\n"
        f"g = json.loads({json.dumps(GLOSSARY)!r})\n"
        "payload = {'term_ids': ['T003', 'T000']}\n"
        "print(json.dumps(static_head_terms(payload, g, budget=7)))\n"
    )
    outputs = []
    for seed in ("0", "1"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(result.stdout.strip())
    assert outputs[0] == outputs[1]
